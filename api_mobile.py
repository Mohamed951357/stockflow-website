from flask import Blueprint, request, jsonify, session, current_app, url_for, Response
from flask_login import login_user, login_required, current_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta, date, time
from dateutil.relativedelta import relativedelta
import pytz
import json
import math
import re
from html import escape
import requests # NEW: ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¥ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¥ط·آ·ط¢آ´ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ¸ط«â€ ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ©

try:
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False

# Web Client ID (from Google Cloud Console ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ OAuth 2.0 ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ Web Client)
GOOGLE_WEB_CLIENT_ID = '873268136156-i4oug6tmlp0mo0r8v7omn25e1f7431m2.apps.googleusercontent.com'

from sqlalchemy import or_, and_, not_, desc, func, extract
from fuzzywuzzy import fuzz, process
from utils import (
    resolve_invite_code_match,
    apply_invite_code_consumed,
    company_name_exists,
    find_company_for_login,
    normalize_company_name,
    update_company_client_context,
)

from models import (
    db, Company, Admin, ProductItem, ProductStockHistory, Appointment, 
    Notification, NotificationRead, FavoriteProduct, SystemSetting, 
    CommunityPost, PostLike, PostComment, PostView, CommunityNotification, PostReport,
    PrivateMessage, PrivateMessageEditLog, 
    CompanyStatus, CompanyStatusView, CompanyStatusReaction,
    ProductReminder, Survey, SurveyQuestion, SurveyResponse, SurveyAnswer, BlockedProduct, SearchLog, AdImage,
    CompanySurveyStatus, AdStory, ProductReportRequest, CompanyFollow, MessageBlock
)

api_mobile_bp = Blueprint('api_mobile', __name__, url_prefix='/api/mobile')

CAIRO_TIMEZONE = pytz.timezone('Africa/Cairo')


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on', 'y'}

# --- CORS Support for Mobile App ---
@api_mobile_bp.before_request
def update_last_active():
    if current_user.is_authenticated and isinstance(current_user, Company):
        try:
            current_user.last_active = datetime.utcnow()
            update_company_client_context(current_user, source_hint='android_app', commit=False)
            db.session.commit()
        except Exception:
            db.session.rollback()

@api_mobile_bp.after_request
def add_cors_headers(response):
    """Allow mobile app to talk to the API from any origin."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Cookie, X-Requested-With'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

@api_mobile_bp.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@api_mobile_bp.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    """Handle CORS preflight requests."""
    response = jsonify({'status': 'ok'})
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Cookie, X-Requested-With'
    response.headers['Access-Control-Max-Age'] = '86400'
    return response, 200
    
@api_mobile_bp.route('/update_push_token', methods=['POST'])
@login_required
def update_push_token():
    data = request.get_json() or {}
    token = (data.get('expo_push_token') or '').strip()
    if token:
        current_user.expo_push_token = token
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸ط«â€ ط·آ·ط¢آ¬ط·آ·ط¢آ¯ ط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ  ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ¸أ¢â‚¬â€چ.'}), 400
    
# --- Push Notification Helper ---
def send_push_notification(target_company_id, title, body, data=None):
    """
    Sends a push notification to a specific company using Expo's Push API.
    """
    company = Company.query.get(target_company_id)
    if not company or not company.expo_push_token:
        return False
    if not (
        str(company.expo_push_token).startswith('ExponentPushToken[')
        or str(company.expo_push_token).startswith('ExpoPushToken[')
    ):
        return False
        
    url = "https://exp.host/--/api/v2/push/send"
    payload = {
        "to": company.expo_push_token,
        "title": _repair_mojibake_text(title),
        "body": _repair_mojibake_text(body),
        "priority": "high",
        "sound": "default",
        "channelId": "stockflow_alerts_v4",
        "data": data or {}
    }
    
    try:
        response = requests.post(
            url,
            json=payload,
            timeout=10,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
                "Content-Type": "application/json",
            }
        )
        if response.status_code != 200:
            print(f"Push notification http error: {response.status_code} - {response.text[:300]}")
            return False

        result = response.json()
        ticket = (result.get('data') or [{}])[0] if isinstance(result.get('data'), list) else (result.get('data') or {})
        if ticket.get('status') == 'ok':
            return True

        error_code = (ticket.get('details') or {}).get('error')
        print(f"Push notification rejected: {ticket}")
        if error_code in ('DeviceNotRegistered', 'MismatchSenderId', 'InvalidCredentials'):
            try:
                company.expo_push_token = None
                db.session.commit()
            except Exception:
                db.session.rollback()
        return False
    except Exception as e:
        print(f"Push notification error: {e}")
        return False


def _send_telegram_text_message(text, disable_notification=False):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_STORAGE_CHAT_ID:
        return False

    try:
        response = requests.post(
            f"{TELEGRAM_API_BASE}/sendMessage",
            data={
                'chat_id': TELEGRAM_STORAGE_CHAT_ID,
                'text': text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
                'disable_notification': disable_notification,
            },
            timeout=20,
        )
        result = response.json()
        if not result.get('ok'):
            print(f"Telegram sendMessage failed: {result}")
            return False
        return True
    except Exception as e:
        print(f"Telegram sendMessage error: {e}")
        return False


def _get_message_block_state(user_id, other_id):
    blocked_by_me = MessageBlock.query.filter_by(blocker_id=user_id, blocked_id=other_id).first() is not None
    blocked_me = MessageBlock.query.filter_by(blocker_id=other_id, blocked_id=user_id).first() is not None
    return {
        'is_blocked_by_me': blocked_by_me,
        'has_blocked_me': blocked_me,
        'messaging_disabled': blocked_by_me or blocked_me,
    }


def _get_message_block_error(user_id, other_id):
    state = _get_message_block_state(user_id, other_id)
    if state['is_blocked_by_me']:
        return 'ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¯ ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ ط·آ·ط¢آ¨ط·آ·ط¢آ­ط·آ·ط¢آ¸ط·آ·ط¢آ± ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ°ط·آ¸أ¢â‚¬طŒ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ©ط·آ·ط¥â€™ ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¨ط·آ·ط¢آ¥ط·آ¸أ¢â‚¬â€چط·آ·ط·â€؛ط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ¸ط·آ·ط¢آ± ط·آ·ط¢آ£ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ ط·آ·ط¢آ¥ط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ·ط¢آ£ط·آ·ط¢آ±ط·آ·ط¢آ¯ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ­ط·آ·ط¢آ§ط·آ·ط¢آ¯ط·آ·ط¢آ«ط·آ·ط¢آ©.'
    if state['has_blocked_me']:
        return 'ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ°ط·آ¸أ¢â‚¬طŒ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ© ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ ط·آ·ط¢آ¨ط·آ·ط¢آ­ط·آ·ط¢آ¸ط·آ·ط¢آ±ط·آ¸ط¦â€™ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬â€چ ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ ط·آ¸ط¦â€™ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ§.'
    return None


_PHONE_DIGIT_MAP = str.maketrans({
    '\u0660': '0', '\u0661': '1', '\u0662': '2', '\u0663': '3', '\u0664': '4',
    '\u0665': '5', '\u0666': '6', '\u0667': '7', '\u0668': '8', '\u0669': '9',
    '\u06F0': '0', '\u06F1': '1', '\u06F2': '2', '\u06F3': '3', '\u06F4': '4',
    '\u06F5': '5', '\u06F6': '6', '\u06F7': '7', '\u06F8': '8', '\u06F9': '9',
})

_PHONE_HINT_TERMS = (
    'phone', 'mobile', 'tel', 'telephone', 'whatsapp', 'wa',
    '\u0631\u0642\u0645',
    '\u0645\u0648\u0628\u0627\u064a\u0644',
    '\u0645\u0648\u0628\u0627\u064a\u0644\u064a',
    '\u0647\u0627\u062a\u0641',
    '\u062a\u0644\u0641\u0648\u0646',
    '\u0648\u0627\u062a\u0633\u0627\u0628',
    '\u0627\u0644\u0627\u062a\u0635\u0627\u0644',
    '\u0627\u062a\u0635\u0644',
    '\u0643\u0644\u0645'
)


def _normalize_phone_detection_text(text):
    return str(text or '').translate(_PHONE_DIGIT_MAP).lower()


def _strip_reply_wrapper(text):
    return re.sub(r'^\[REPLY\|[^\]]*?\][\s\S]*?\[/REPLY\]', '', str(text or '')).strip()


def _is_structured_chat_payload(text):
    return re.match(r'^\[(image|video|voice|file)\][\s\S]*?\[/\1\]$', str(text or '').strip(), re.IGNORECASE) is not None


def _is_phone_like_digit_sequence(digits, has_hint=False):
    value = str(digits or '')
    if value.startswith('00'):
        value = value[2:]

    if re.match(r'^01\d{9}$', value):
        return True
    if re.match(r'^1\d{9}$', value):
        return True
    if re.match(r'^20?1\d{9}$', value):
        return True
    if has_hint and re.match(r'^\d{9,15}$', value):
        return True
    return False


def _contains_blocked_phone_number(text):
    content = _strip_reply_wrapper(text)
    if not content or _is_structured_chat_payload(content):
        return False

    normalized = _normalize_phone_detection_text(content)
    has_hint = any(term in normalized for term in _PHONE_HINT_TERMS)

    for candidate in re.findall(r'[\d+\-().\s/\\]{8,40}', normalized):
        digits_only = re.sub(r'\D', '', candidate)
        if 9 <= len(digits_only) <= 15 and _is_phone_like_digit_sequence(digits_only, has_hint):
            return True

    collapsed_digits = re.sub(r'\D', '', normalized)
    if len(collapsed_digits) >= 9:
        for i in range(len(collapsed_digits)):
            for length in range(9, 16):
                if i + length <= len(collapsed_digits) and _is_phone_like_digit_sequence(collapsed_digits[i:i + length], has_hint):
                    return True

    return False


PHONE_BLOCKED_SUBJECT_PREFIX = '[PHONE_BLOCKED]'
ANONYMOUS_DISPLAY_NAME = 'مستخدم مجهول'
ANONYMOUS_AVATAR = 'default-male'
MOJIBAKE_MARKERS = ('ط', 'ظ', 'Ø', 'Ù', 'Ú', 'Û', 'Ã', 'Â', 'â', 'ï', '�')


def _suspicious_text_score(value=''):
    text = str(value or '')
    return sum(text.count(marker) for marker in MOJIBAKE_MARKERS)


def _arabic_text_score(value=''):
    text = str(value or '')
    return sum(1 for char in text if '\u0600' <= char <= '\u06FF')


def _repair_mojibake_text(value):
    text = str(value or '')
    if not text or _suspicious_text_score(text) < 2:
        return text

    attempts = {text}
    frontier = {text}

    for _ in range(3):
        next_frontier = set()
        for candidate in frontier:
            for src, dst in (('cp1252', 'utf-8'), ('latin-1', 'utf-8')):
                try:
                    repaired = candidate.encode(src).decode(dst)
                except Exception:
                    continue
                if repaired and repaired not in attempts:
                    attempts.add(repaired)
                    next_frontier.add(repaired)
        if not next_frontier:
            break
        frontier = next_frontier

    best = text
    for candidate in attempts:
        candidate_score = (_suspicious_text_score(candidate), -_arabic_text_score(candidate), len(candidate))
        best_score = (_suspicious_text_score(best), -_arabic_text_score(best), len(best))
        if candidate_score < best_score:
            best = candidate

    return best


def _notification_preview(value, limit=80, fallback=''):
    text = ' '.join(str(value or '').split())
    if not text:
        return fallback
    return text[:limit] + ('...' if len(text) > limit else '')


def _community_notification_title(notification_type):
    titles = {
        'like': 'إعجاب جديد',
        'comment': 'تعليق جديد',
        'reply': 'رد جديد على تعليقك',
        'new_follower': 'متابع جديد',
        'poll_vote': 'تصويت جديد على استطلاعك',
        'new_post': 'منشور جديد من شركة تتابعها',
    }
    return titles.get(notification_type, 'إشعار جديد')


def _normalize_anonymous_entity(payload, name_keys=('company_name',), avatar_keys=('avatar',)):
    item = dict(payload or {})

    for key, value in list(item.items()):
        if isinstance(value, str):
            item[key] = _repair_mojibake_text(value)

    if item.get('is_anonymous'):
        for key in name_keys:
            if key in item:
                item[key] = ANONYMOUS_DISPLAY_NAME
        for key in avatar_keys:
            if key in item:
                item[key] = ANONYMOUS_AVATAR
        if 'is_premium' in item:
            item['is_premium'] = False
        if 'is_verified' in item:
            item['is_verified'] = False

    return item


def get_official_stockflow_account():
    return Company.query.filter(
        or_(
            Company.company_name.ilike('STOCK FLOW'),
            Company.username.ilike('STOCK FLOW')
        )
    ).first()


def ensure_following_official_account(company):
    if not company or not getattr(company, 'id', None):
        return None

    official = get_official_stockflow_account()
    if not official or official.id == company.id:
        return official

    existing = CompanyFollow.query.filter_by(
        follower_id=company.id,
        followed_id=official.id
    ).first()
    if existing:
        return official

    try:
        db.session.add(CompanyFollow(follower_id=company.id, followed_id=official.id))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return official


# --- Auth Endpoints ---

@api_mobile_bp.route('/users/<int:user_id>/status')
@login_required
def get_user_status(user_id):
    user = Company.query.get_or_404(user_id)
    # ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¹ط·آ·ط¹آ¾ط·آ·ط¢آ¨ط·آ·ط¢آ± ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬آ¦ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ·ط¢آµط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ ط·آ·ط¢آ¥ط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ¸ط¦â€™ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ¢ط·آ·ط¢آ®ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ·ط¢آ§ط·آ·ط¢آ· ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬طŒ ط·آ·ط¢آ®ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¢ط·آ·ط¢آ®ط·آ·ط¢آ± 2 ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬ع‘ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ©
    is_online = False
    if user.last_active:
        is_online = (datetime.utcnow() - user.last_active) < timedelta(minutes=2)
    
    return jsonify({
        'is_online': is_online,
        'last_seen': user.last_active.isoformat() if user.last_active else None
    })

@api_mobile_bp.route('/users/ping', methods=['POST'])
@login_required
def ping_status():
    # Because of @api_mobile_bp.before_request, current_user.last_active is already updated!
    return jsonify({'success': True, 'is_online': True})

@api_mobile_bp.route('/messages/typing', methods=['POST'])
@login_required
def send_typing_status():
    data = request.get_json()
    is_typing = data.get('is_typing', False)
    
    try:
        current_user.is_typing = is_typing
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@api_mobile_bp.route('/messages/typing/<int:user_id>')
@login_required
def get_typing_status(user_id):
    user = Company.query.get_or_404(user_id)
    # ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¹ط·آ·ط¹آ¾ط·آ·ط¢آ¨ط·آ·ط¢آ±ط·آ¸أ¢â‚¬طŒ ط·آ¸ط¸آ¹ط·آ¸ط¦â€™ط·آ·ط¹آ¾ط·آ·ط¢آ¨ ط·آ¸ط¸آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ· ط·آ·ط¢آ¥ط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ¸ط¦â€™ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ  ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ·ط¢آµط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ ط·آ·ط¢آ£ط·آ¸ط¸آ¹ط·آ·ط¢آ¶ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹
    is_online = False
    if user.last_active:
        is_online = (datetime.utcnow() - user.last_active) < timedelta(minutes=2)
        
    return jsonify({
        'is_typing': user.is_typing if is_online else False
    })

@api_mobile_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'يرجى إدخال البيانات المطلوبة.'}), 400
    
    identifier = (data.get('username') or data.get('identifier') or '').strip()
    password   = (data.get('password') or '').strip()
    remember_me = _coerce_bool(data.get('remember_me'), default=True)

    if not identifier or not password:
        return jsonify({'success': False, 'message': 'اسم المستخدم/رقم الهاتف وكلمة المرور مطلوبان.'}), 400

    user = find_company_for_login(identifier, password)

    if user:
        if user.is_active:
            session['user_type'] = 'company'
            session.permanent = True
            login_user(user, remember=remember_me, duration=timedelta(days=60) if remember_me else None)
            try:
                user.last_login = datetime.utcnow()
                update_company_client_context(user, source_hint='android_app', commit=False, force=True)
                db.session.commit()
            except Exception:
                db.session.rollback()
            return jsonify({
                'success': True,
                'message': 'تم تسجيل الدخول بنجاح.',
                'force_password_change': bool(user.force_password_change),
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'company_name': user.company_name,
                    'email': user.email,
                    'phone': user.phone,
                    'avatar': user.avatar,
                    'is_premium': user.is_premium
                }
            })
        else:
            return jsonify({'success': False, 'message': 'الحساب غير نشط. يرجى التواصل مع الإدارة.'}), 403

    return jsonify({'success': False, 'message': 'اسم المستخدم/رقم الهاتف أو كلمة المرور غير صحيحة.'}), 401

@api_mobile_bp.route('/signup_company', methods=['POST'])
def signup_company_api():
    """نقطة API لتسجيل شركة جديدة من تطبيق الموبايل - ترد بـ JSON"""
    from werkzeug.security import generate_password_hash
    from utils import resolve_invite_code_match, apply_invite_code_consumed

    data = request.get_json() or {}

    username = (data.get('username') or '').strip()
    password = (data.get('password') or '').strip()
    confirm_password = (data.get('confirm_password') or '').strip()
    company_name = (data.get('company_name') or '').strip()
    email = (data.get('email') or '').strip()
    phone = (data.get('phone') or '').strip()
    invite_code = (data.get('invite_code') or '').strip()

    # التحقق من الحقول الإلزامية
    if not username or not password or not company_name or not phone:
        return jsonify({'success': False, 'message': 'يرجى ملء جميع الحقول الإلزامية.'}), 400

    if password != confirm_password:
        return jsonify({'success': False, 'message': 'كلمة المرور وتأكيدها غير متطابقين.'}), 400

    if len(password) < 6:
        return jsonify({'success': False, 'message': 'كلمة المرور يجب أن تكون 6 أحرف على الأقل.'}), 400

    import re as _re
    if not _re.match(r'^01\d{9}$', phone):
        return jsonify({'success': False, 'message': 'رقم الهاتف يجب أن يتكون من 11 رقم ويبدأ بـ 01.'}), 400

    # التحقق من كود الدعوة
    current_setting = SystemSetting.query.filter_by(setting_key='invite_code').first()
    current_code = (current_setting.setting_value if current_setting else '') or ''

    if not current_code:
        return jsonify({'success': False, 'message': 'لم يتم إعداد كود دعوة من قبل الإدارة. يرجى التواصل معهم.'}), 400

    match_kind = resolve_invite_code_match(invite_code)
    if not match_kind:
        return jsonify({'success': False, 'message': 'كود الدعوة غير صحيح أو تم استخدامه مسبقاً.'}), 400

    # اسم المستخدم مسموح يتكرر، لكن اسم الشركة نفسه لا يتكرر.
    if company_name_exists(company_name):
        return jsonify({'success': False, 'message': 'اسم الشركة هذا مسجل بالفعل في النظام. إذا كنت صاحب هذه الشركة، تواصل مع الإدارة.'}), 400

    try:
        from views import _create_company_with_sequence_recovery
        hashed_password = generate_password_hash(password)
        new_company = _create_company_with_sequence_recovery(
            username=username,
            password=hashed_password,
            company_name=company_name,
            email=email if email else None,
            phone=phone if phone else None,
            is_active=True,
            invite_code_used=invite_code,
            created_at=datetime.utcnow()
        )
        apply_invite_code_consumed(match_kind)
        db.session.commit()
        ensure_following_official_account(new_company)

        return jsonify({
            'success': True,
            'message': 'تم تسجيل حساب الشركة بنجاح! يمكنك الآن تسجيل الدخول.'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ أثناء التسجيل: {str(e)}'}), 500




@api_mobile_bp.route('/forgot_password', methods=['POST'])
def forgot_password():
    """إرسال كلمة مرور مؤقتة عبر واتساب"""
    from werkzeug.security import generate_password_hash
    import random, string

    data = request.get_json() or {}
    identifier = (data.get('identifier') or data.get('phone') or data.get('username') or '').strip()

    if not identifier:
        return jsonify({'success': False, 'message': 'يرجى إدخال اسم المستخدم أو رقم الهاتف.'}), 400

    import re as _re
    if _re.match(r'^0\d{9,14}$', identifier):
        user = Company.query.filter_by(phone=identifier).first()
    else:
        username_matches = Company.query.filter_by(username=identifier).all()
        if len(username_matches) > 1:
            return jsonify({'success': False, 'message': 'اسم المستخدم موجود لأكثر من شركة. يرجى استخدام رقم الهاتف لاستعادة كلمة المرور.'}), 400
        user = username_matches[0] if username_matches else None
        if not user:
            user = Company.query.filter_by(phone=identifier).first()

    if not user:
        return jsonify({'success': False, 'message': 'لا يوجد حساب مرتبط بهذا الاسم أو الرقم.'}), 404

    if not user.is_active:
        return jsonify({'success': False, 'message': 'الحساب غير نشط. يرجى التواصل مع الإدارة.'}), 403

    if not user.phone:
        return jsonify({'success': False, 'message': 'لا يوجد رقم هاتف مسجل. يرجى التواصل مع الإدارة.'}), 400

    temp_password = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    try:
        user.password = generate_password_hash(temp_password)
        user.force_password_change = True
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ. يرجى المحاولة مرة أخرى.'}), 500

    phone_clean = user.phone.strip()
    if phone_clean.startswith('0'):
        wa_number = '2' + phone_clean[1:]
    elif phone_clean.startswith('+'):
        wa_number = phone_clean[1:]
    else:
        wa_number = phone_clean

    msg = (
        f"🔐 *STOCK FLOW - كلمة المرور المؤقتة*\n\n"
        f"مرحباً {user.company_name}،\n\n"
        f"كلمة المرور المؤقتة الخاصة بك:\n"
        f"*{temp_password}*\n\n"
        f"⚠️ يرجى تغييرها فور تسجيل الدخول.\n"
        f"📱 اسم المستخدم: {user.username}"
    )
    try:
        import urllib.parse
        wa_url = f"https://api.whatsapp.com/send/?phone={wa_number}&text={urllib.parse.quote(msg)}&type=phone_number&app_absent=0"
        requests.get(wa_url, timeout=8)
    except Exception:
        pass

    masked = user.phone[:4] + '****' + user.phone[-2:]
    return jsonify({
        'success': True,
        'message': f'تم إرسال كلمة المرور المؤقتة على رقم الهاتف ({masked}). سجّل الدخول بها ثم غيّرها فوراً.'
    })


@api_mobile_bp.route('/change_password', methods=['POST'])
@login_required
def change_password():
    """تغيير كلمة المرور"""
    from werkzeug.security import generate_password_hash

    data = request.get_json() or {}
    current_password = (data.get('current_password') or '').strip()
    new_password     = (data.get('new_password') or '').strip()
    confirm_password = (data.get('confirm_password') or '').strip()

    if not current_password or not new_password or not confirm_password:
        return jsonify({'success': False, 'message': 'يرجى ملء جميع الحقول.'}), 400

    if not check_password_hash(current_user.password, current_password):
        return jsonify({'success': False, 'message': 'كلمة المرور الحالية غير صحيحة.'}), 400

    if new_password != confirm_password:
        return jsonify({'success': False, 'message': 'كلمة المرور الجديدة وتأكيدها غير متطابقين.'}), 400

    if len(new_password) < 6:
        return jsonify({'success': False, 'message': 'كلمة المرور يجب أن تكون 6 أحرف على الأقل.'}), 400

    try:
        current_user.password = generate_password_hash(new_password)
        current_user.force_password_change = False
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم تغيير كلمة المرور بنجاح.'})
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء تغيير كلمة المرور.'}), 500


@api_mobile_bp.route('/change_password_forced', methods=['POST'])
@login_required
def change_password_forced():
    """تغيير كلمة المرور المؤقتة — لا يتطلب كلمة المرور الحالية لأن المستخدم دخل بكلمة مؤقتة"""
    from werkzeug.security import generate_password_hash

    # التأكد أن الحساب فعلاً في وضع تغيير إجباري
    if not current_user.force_password_change:
        return jsonify({'success': False, 'message': 'لا يمكن استخدام هذا المسار إلا عند تسجيل الدخول بكلمة مرور مؤقتة.'}), 403

    data = request.get_json() or {}
    new_password     = (data.get('new_password') or '').strip()
    confirm_password = (data.get('confirm_password') or '').strip()

    if not new_password or not confirm_password:
        return jsonify({'success': False, 'message': 'يرجى إدخال كلمة المرور الجديدة وتأكيدها.'}), 400

    if new_password != confirm_password:
        return jsonify({'success': False, 'message': 'كلمة المرور الجديدة وتأكيدها غير متطابقين.'}), 400

    if len(new_password) < 6:
        return jsonify({'success': False, 'message': 'كلمة المرور يجب أن تكون 6 أحرف على الأقل.'}), 400

    try:
        current_user.password = generate_password_hash(new_password)
        current_user.force_password_change = False
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم تغيير كلمة المرور بنجاح! يمكنك الآن استخدام التطبيق.'})
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'حدث خطأ أثناء تغيير كلمة المرور.'}), 500


@api_mobile_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    session.pop('user_type', None)
    return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¹آ¾ط·آ·ط¢آ³ط·آ·ط¢آ¬ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ®ط·آ·ط¢آ±ط·آ¸ط«â€ ط·آ·ط¢آ¬ ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ­.'})

@api_mobile_bp.route('/premium/activate_code_v2', methods=['POST'])
@login_required
def activate_premium_code_v2():
    """ط·آ·ط¹آ¾ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ² ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ"""
    import random
    if session.get('user_type') != 'company':
        return jsonify({'success': False, 'message': 'ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آµط·آ·ط¢آ±ط·آ·ط¢آ­.'}), 403

    if current_user.is_premium:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ¸ط¦â€™ ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ²!'}), 400

    data = request.get_json()
    code = (data.get('code') or '').strip()

    if not code:
        return jsonify({'success': False, 'message': 'ط·آ¸ط¸آ¹ط·آ·ط¢آ±ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ¥ط·آ·ط¢آ¯ط·آ·ط¢آ®ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ.'}), 400

    current_setting = SystemSetting.query.filter_by(setting_key='invite_code').first()
    current_code = (current_setting.setting_value if current_setting else '') or ''

    if not current_code:
        return jsonify({'success': False, 'message': 'ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¸آ¹ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¥ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ¯ ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ·ط¢آ¯ ط·آ·ط¢آ¯ط·آ·ط¢آ¹ط·آ¸ط«â€ ط·آ·ط¢آ© ط·آ·ط¢آ¨ط·آ·ط¢آ¹ط·آ·ط¢آ¯.'}), 400

    match_kind = resolve_invite_code_match(code)
    if not match_kind:
        return jsonify({'success': False, 'message': 'ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ·ط¢آµط·آ·ط¢آ­ط·آ¸ط¸آ¹ط·آ·ط¢آ­ ط·آ·ط¢آ£ط·آ¸ط«â€  ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬طŒ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹.'}), 400

    # ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¯ط·آ·ط¢آ¹ط·آ¸ط«â€ ط·آ·ط¢آ© ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ­ ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ 30 ط·آ¸ط¸آ¹ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ¦ (ط·آ·ط¢آ´ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ± ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آ­ط·آ·ط¢آ¯) ط·آ¸ط«â€ ط·آ¸ط¸آ¹ط·آ·ط¢آ­ط·آ·ط¢آ±ط·آ¸أ¢â‚¬ع‘ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ·ط¢آ¯
    premium_days = 30

    try:
        current_user.is_premium = True
        current_user.premium_activation_date = datetime.utcnow()
        # ط·آ·ط¢آ¥ط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ¸ط¦â€™ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬آ¦ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬طŒ ط·آ·ط¢آ§ط·آ·ط¢آ´ط·آ·ط¹آ¾ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸ط¦â€™ ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ¸ط¸آ¹ ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چط·آ·ط¥â€™ ط·آ¸أ¢â‚¬آ ط·آ¸أ¢â‚¬ع‘ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¨ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬طŒ
        if current_user.premium_end_date and current_user.premium_end_date > datetime.utcnow():
            current_user.premium_end_date = current_user.premium_end_date + timedelta(days=premium_days)
        else:
            current_user.premium_end_date = datetime.utcnow() + timedelta(days=premium_days)
            
        current_user.invite_code_used = code

        apply_invite_code_consumed(match_kind)

        return jsonify({
            'success': True,
            'message': f'ط¸â€¹ط¹ط›ط¹ع©أ¢â‚¬آ° ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¹آ¾ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ¸ط¦â€™ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ² ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ­ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¯ط·آ·ط¢آ© {premium_days} ط·آ¸ط¸آ¹ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¥ط·آ·ط¢آ¶ط·آ·ط¢آ§ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹.',
            'premium_end_date': current_user.premium_end_date.isoformat()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'ط·آ·ط¢آ­ط·آ·ط¢آ¯ط·آ·ط¢آ« ط·آ·ط¢آ®ط·آ·ط¢آ·ط·آ·ط¢آ£ ط·آ·ط¢آ£ط·آ·ط¢آ«ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ: {str(e)}'}), 500

@api_mobile_bp.route('/check_session', methods=['GET'])
def check_session():
    if current_user.is_authenticated and session.get('user_type') == 'company':
        return jsonify({
            'authenticated': True,
            'user': {
                'id': current_user.id,
                'username': current_user.username,
                'company_name': current_user.company_name,
                'is_premium': current_user.is_premium
            }
        })
    return jsonify({'authenticated': False}), 401

# --- Global App Configuration Endpoints ---
@api_mobile_bp.route('/auth/google/link', methods=['POST'])
@login_required
def link_google_account():
    if not GOOGLE_AUTH_AVAILABLE:
        return jsonify({'success': False, 'message': 'Google Auth module not installed on server'}), 500

    data = request.get_json()
    token = data.get('id_token')
    if not token:
        return jsonify({'success': False, 'message': 'Missing id_token'}), 400

    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            GOOGLE_WEB_CLIENT_ID  # Validate the token was issued for our app
        )
        google_id = idinfo['sub']
        google_email = idinfo.get('email')
        
        # Check if another company already linked this Google ID
        existing = Company.query.filter_by(google_id=google_id).first()
        if existing and existing.id != current_user.id:
            return jsonify({'success': False, 'message': 'ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ ط·آ·ط¢آ¬ط·آ¸ط«â€ ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬â€چ ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ±ط·آ·ط¢آ¨ط·آ¸ط«â€ ط·آ·ط¢آ· ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¨ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ ط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ© ط·آ·ط¢آ¢ط·آ·ط¢آ®ط·آ·ط¢آ±.'}), 400
            
        current_user.google_id = google_id
        # ط·آ·ط¢آ­ط·آ¸ط¸آ¾ط·آ·ط¢آ¸ google_email ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ (ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ³ ط·آ¸ط¸آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ· ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€  ط·آ¸ط¦â€™ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ  ط·آ¸ط¸آ¾ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ·ط·â€؛ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹)
        if google_email:
            current_user.google_email = google_email
            if not current_user.email:
                current_user.email = google_email
        db.session.commit()
        return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ±ط·آ·ط¢آ¨ط·آ·ط¢آ· ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ ط·آ·ط¢آ¬ط·آ¸ط«â€ ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ­.', 'email': current_user.email, 'google_email': current_user.google_email})

    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
        
@api_mobile_bp.route('/auth/google/signin', methods=['POST'])
def google_signin():
    if not GOOGLE_AUTH_AVAILABLE:
        return jsonify({'success': False, 'message': 'Google Auth module not installed'}), 500

    data = request.get_json()
    token = data.get('id_token')
    if not token:
        return jsonify({'success': False, 'message': 'Missing token'}), 400

    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            GOOGLE_WEB_CLIENT_ID  # Validate the token was issued for our app
        )
        google_id = idinfo.get('sub')
        google_email = idinfo.get('email')
        
        user = Company.query.filter_by(google_id=google_id).first()
        if user:
            if not user.is_active:
                return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ·ط¢آ·. ط·آ¸ط¸آ¹ط·آ·ط¢آ±ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آµط·آ¸أ¢â‚¬â€چ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¥ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ·ط¢آ©.'}), 403
                
            session['user_type'] = 'company'
            login_user(user, remember=True, duration=timedelta(days=60))
            session.permanent = True
            
            try:
                user.last_login = datetime.utcnow()
                update_company_client_context(user, source_hint='android_app', commit=False, force=True)
                if google_email and not user.email:
                    user.email = google_email
                db.session.commit()
            except Exception:
                db.session.rollback()
                
            return jsonify({
                'success': True,
                'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¹آ¾ط·آ·ط¢آ³ط·آ·ط¢آ¬ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¯ط·آ·ط¢آ®ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ­.',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'company_name': user.company_name,
                    'email': user.email,
                    'phone': user.phone,
                    'avatar': user.avatar,
                    'is_premium': user.is_premium
                }
            })
        else:
            return jsonify({'success': False, 'message': 'ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¸آ¹ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ±ط·آ·ط¢آ¨ط·آ·ط¢آ· ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ ط·آ·ط¢آ¨ط·آ¸أ¢â€ڑآ¬ Google ط·آ·ط¢آ¨ط·آ·ط¢آ¹ط·آ·ط¢آ¯. ط·آ¸ط¸آ¹ط·آ·ط¢آ±ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ° ط·آ·ط¹آ¾ط·آ·ط¢آ³ط·آ·ط¢آ¬ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¯ط·آ·ط¢آ®ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ ط·آ·ط¢آ«ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ±ط·آ·ط¢آ¨ط·آ·ط¢آ· ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ¸ط¦â€™.'}), 404

    except ValueError as e:
        print(f'[Google SignIn] Token verification failed: {e}')
        return jsonify({'success': False, 'message': f'ط·آ·ط¹آ¾ط·آ·ط¢آ¹ط·آ·ط¢آ°ط·آ·ط¢آ± ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ­ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬ع‘ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ Google. ({str(e)[:80]})'}), 400

@api_mobile_bp.route('/auth/google/unlink', methods=['POST'])
@login_required
def unlink_google_account():
    if not current_user.google_id:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ¸ط¦â€™ ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ±ط·آ·ط¹آ¾ط·آ·ط¢آ¨ط·آ·ط¢آ· ط·آ·ط¢آ¨ط·آ·ط¢آ¬ط·آ¸ط«â€ ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬â€چ.'}), 400
    try:
        current_user.google_id = None
        current_user.google_email = None
        db.session.commit()
        return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¸آ¾ط·آ¸ط¦â€™ ط·آ·ط¢آ±ط·آ·ط¢آ¨ط·آ·ط¢آ· ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ ط·آ·ط¢آ¬ط·آ¸ط«â€ ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ­.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@api_mobile_bp.route('/app_config', methods=['GET'])
def get_app_config():
    min_v = SystemSetting.query.filter_by(setting_key='min_android_version').first()
    update_link = SystemSetting.query.filter_by(setting_key='app_download_link').first()
    
    return jsonify({
        'success': True,
        'min_app_version': min_v.setting_value if min_v else '1.0.0',
        'update_url': update_link.setting_value if update_link else 'https://www.stock-flow.site'
    })

# --- Dashboard & Profile Endpoints ---

@api_mobile_bp.route('/dashboard', methods=['GET'])
@login_required
def get_dashboard():
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
        
    company_id = current_user.id

    # 1. Unread notifications count
    unread_notifications = Notification.query.filter(
        or_(
            Notification.target_type == 'all',
            and_(Notification.target_type == 'specific', Notification.target_id == company_id)
        ),
        Notification.is_active == True,
        ~db.session.query(NotificationRead.id).filter(
            NotificationRead.notification_id == Notification.id,
            NotificationRead.company_id == company_id
        ).exists()
    ).count()

    # 2. Unread community interactions
    unread_community = CommunityNotification.query.filter_by(
        company_id=company_id, is_read=False
    ).count()

    # 3. Unread private messages
    unread_messages = PrivateMessage.query.filter_by(
        receiver_id=company_id, is_read=False, is_deleted_by_receiver=False
    ).count()

    # 4. Pending appointments
    pending_appointments = Appointment.query.filter_by(
        company_id=company_id, status='pending'
    ).count()

    # 5. Ad Carousel & Website Announcement
    is_premium = getattr(current_user, 'is_premium', False)
    allowed_types = ['premium', 'all'] if is_premium else ['free', 'all']
    
    # Get active ad images to show in the app carousel (Directly from AdImage)
    active_ads = AdImage.query.filter(
        AdImage.is_active == True,
        AdImage.image_type.in_(allowed_types)
    ).order_by(AdImage.upload_date.desc()).all()
    
    ads_payload = []
    for ad in active_ads:
        if not hasattr(ad, 'filename') or not ad.filename:
            continue
            
        if ad.filename.startswith('http'):
            image_url = ad.filename
        else:
            image_url = url_for('serve_ad_image', filename=ad.filename, _external=True)
            if image_url.startswith('http://'):
                image_url = image_url.replace('http://', 'https://', 1)
            
        ads_payload.append({
            'id': ad.id,
            'image': image_url,
            'description': ad.description or ''
        })

    # Get website announcement from SystemSetting
    company_ad_setting = SystemSetting.query.filter_by(setting_key='company_page_ad').first()
    announcement = company_ad_setting.setting_value if company_ad_setting else ''

    # --- Promo Feature ---
    promo_active_setting = SystemSetting.query.filter_by(setting_key='app_promo_active').first()
    promo_url_setting = SystemSetting.query.filter_by(setting_key='app_promo_url').first()
    promo_link_setting = SystemSetting.query.filter_by(setting_key='app_promo_link').first()

    promo_payload = {
        'active': promo_active_setting.setting_value.lower() == 'true' if promo_active_setting else False,
        'url': promo_url_setting.setting_value if promo_url_setting else '',
        'link': promo_link_setting.setting_value if promo_link_setting else '',
        'duration': 7,
        'type': 'image',
    }

    if not promo_payload['active'] or not promo_payload['url']:
        promo_gif_setting = SystemSetting.query.filter_by(setting_key='promo_gif').first()
        promo_gif_duration_setting = SystemSetting.query.filter_by(setting_key='promo_gif_duration').first()
        promo_gif_validity_setting = SystemSetting.query.filter_by(setting_key='promo_gif_validity').first()
        promo_gif_upload_date_setting = SystemSetting.query.filter_by(setting_key='promo_gif_upload_date').first()

        promo_gif_filename = promo_gif_setting.setting_value.strip() if promo_gif_setting and promo_gif_setting.setting_value else ''
        promo_gif_validity = promo_gif_validity_setting.setting_value.strip() if promo_gif_validity_setting and promo_gif_validity_setting.setting_value else 'always'
        promo_gif_upload_date = promo_gif_upload_date_setting.setting_value.strip() if promo_gif_upload_date_setting and promo_gif_upload_date_setting.setting_value else ''
        promo_gif_duration = 7

        if promo_gif_duration_setting and str(promo_gif_duration_setting.setting_value).isdigit():
            promo_gif_duration = max(1, min(30, int(promo_gif_duration_setting.setting_value)))

        is_valid = True
        if promo_gif_filename and promo_gif_validity != 'always' and promo_gif_upload_date:
            try:
                upload_dt = datetime.fromisoformat(promo_gif_upload_date)
                if upload_dt.tzinfo is None:
                    upload_dt = pytz.UTC.localize(upload_dt)
                time_diff = datetime.now(pytz.UTC) - upload_dt
                if promo_gif_validity == '24hours' and time_diff.total_seconds() > 86400:
                    is_valid = False
                elif promo_gif_validity == '7days' and time_diff.days > 7:
                    is_valid = False
                elif promo_gif_validity == '30days' and time_diff.days > 30:
                    is_valid = False
            except Exception:
                is_valid = True

        if promo_gif_filename and is_valid:
            promo_url = url_for('static', filename=f'promo_gifs/{promo_gif_filename}', _external=True)
            if promo_url.startswith('http://'):
                promo_url = promo_url.replace('http://', 'https://', 1)
            promo_payload = {
                'active': True,
                'url': promo_url,
                'link': '',
                'duration': promo_gif_duration,
                'type': 'gif',
            }

    # 6. Monthly search statistics
    monthly_search_limit_setting = SystemSetting.query.filter_by(setting_key='monthly_search_limit').first()
    monthly_search_limit = int(monthly_search_limit_setting.setting_value) if monthly_search_limit_setting and monthly_search_limit_setting.setting_value.isdigit() else 30
    
    now = datetime.utcnow()
    monthly_search_count = SearchLog.query.filter(
        SearchLog.company_id == company_id,
        extract('year', SearchLog.search_date) == now.year,
        extract('month', SearchLog.search_date) == now.month
    ).count()

    return jsonify({
        'company_name': current_user.company_name,
        'is_premium': current_user.is_premium,
        'unread_notifications': unread_notifications,
        'unread_community': unread_community,
        'unread_messages': unread_messages,
        'pending_appointments': pending_appointments,
        'ads': ads_payload,
        'announcement': announcement,
        'promo': promo_payload,
        'search_count': monthly_search_count,
        'search_limit': monthly_search_limit,
        'google_linked': bool(current_user.google_id)
    })

@api_mobile_bp.route('/profile', methods=['GET'])
@login_required
def get_profile():
    ensure_following_official_account(current_user)
    return jsonify({
        'id': current_user.id,
        'username': current_user.username,
        'company_name': current_user.company_name,
        'email': current_user.email,
        'phone': current_user.phone,
        'avatar': current_user.avatar,
        'is_premium': current_user.is_premium,
        'premium_end_date': current_user.premium_end_date.isoformat() if current_user.premium_end_date else None,
        'created_at': current_user.created_at.isoformat() if current_user.created_at else None,
        # ط·آ·ط¢آ­ط·آ¸أ¢â‚¬ع‘ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¬ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ©
        'bio': getattr(current_user, 'bio', None),
        'cover_photo_url': getattr(current_user, 'cover_photo_url', None),
        'google_linked': bool(current_user.google_id),
        'google_email': getattr(current_user, 'google_email', None),
    })

@api_mobile_bp.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    try:
        if 'email' in data:
            current_user.email = data['email']
        if 'phone' in data:
            current_user.phone = data['phone']
        if 'avatar' in data:
            current_user.avatar = data['avatar']
        if 'company_name' in data and data['company_name']:
            new_company_name = data['company_name'].strip()
            if (
                normalize_company_name(new_company_name) != normalize_company_name(current_user.company_name)
                and company_name_exists(new_company_name, exclude_company_id=current_user.id)
            ):
                return jsonify({'success': False, 'message': 'اسم الشركة هذا مسجل بالفعل في النظام.'}), 400
            current_user.company_name = new_company_name
        if 'password' in data and data['password']:
            current_user.password = generate_password_hash(data['password'])
        # ط·آ·ط¢آ­ط·آ¸أ¢â‚¬ع‘ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¬ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ©
        if 'bio' in data:
            current_user.bio = data['bio'] or None
        if 'cover_photo_url' in data:
            current_user.cover_photo_url = data['cover_photo_url'] or None
            
        db.session.commit()
        return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¹آ¾ط·آ·ط¢آ­ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ« ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ®ط·آ·ط¢آµط·آ¸ط¸آ¹ ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ­.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@api_mobile_bp.route('/company/settings', methods=['GET'])
@login_required
def get_company_settings():
    return jsonify({
        'receive_messages_enabled': current_user.receive_messages_enabled
    })

@api_mobile_bp.route('/company/settings', methods=['POST'])
@login_required
def update_company_settings():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400
    
    try:
        if 'receive_messages_enabled' in data:
            current_user.receive_messages_enabled = data['receive_messages_enabled']
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¹آ¾ط·آ·ط¢آ­ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ« ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¥ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¹آ¾.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@api_mobile_bp.route('/premium/activate_code', methods=['POST'])
@login_required
def activate_premium_code():
    data = request.get_json()
    import random
    if not data or 'code' not in data:
        return jsonify({'success': False, 'message': 'ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ¨.'}), 400
        
    entered_code = data['code'].strip()
    try:
        current_setting = SystemSetting.query.filter_by(setting_key='invite_code').first()
        current_code = (current_setting.setting_value if current_setting else '') or ''

        if not current_code:
            return jsonify({'success': False, 'message': 'ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¸آ¹ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¥ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ¯ ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ·ط¢آ¯ ط·آ·ط¢آ¯ط·آ·ط¢آ¹ط·آ¸ط«â€ ط·آ·ط¢آ© ط·آ·ط¢آ¨ط·آ·ط¢آ¹ط·آ·ط¢آ¯.'}), 400

        match_kind = resolve_invite_code_match(entered_code)
        if not match_kind:
            return jsonify({'success': False, 'message': 'ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ·ط¢آµط·آ·ط¢آ­ط·آ¸ط¸آ¹ط·آ·ط¢آ­ ط·آ·ط¢آ£ط·آ¸ط«â€  ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬طŒ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹.'}), 400

        # ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¯ط·آ·ط¢آ¹ط·آ¸ط«â€ ط·آ·ط¢آ© ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ­ ط·آ·ط¢آ´ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آ­ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ (30 ط·آ¸ط¸آ¹ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹) ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ´ط·آ·ط¹آ¾ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸ط¦â€™ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ²
        duration_days = 30

        if current_user.is_premium and current_user.premium_end_date and current_user.premium_end_date > datetime.utcnow():
            # Extend subscription
            current_user.premium_end_date = current_user.premium_end_date + timedelta(days=duration_days)
            msg = f'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ·ط¢آ´ط·آ·ط¹آ¾ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸ط¦â€™ط·آ¸ط¦â€™ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ² ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ­! ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬طŒط·آ¸ط¸آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¢ط·آ¸أ¢â‚¬آ  ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ {current_user.premium_end_date.strftime("%Y-%m-%d")}'
        else:
            # New activation
            current_user.is_premium = True
            current_user.premium_activation_date = datetime.utcnow()
            current_user.premium_end_date = datetime.utcnow() + timedelta(days=duration_days)
            msg = f'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¹آ¾ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ·ط¢آ´ط·آ·ط¹آ¾ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸ط¦â€™ط·آ¸ط¦â€™ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ² ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ­ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¯ط·آ·ط¢آ© {duration_days} ط·آ¸ط¸آ¹ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ¦!'
            
        current_user.invite_code_used = entered_code

        apply_invite_code_consumed(match_kind)

        return jsonify({'success': True, 'message': msg})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'ط·آ·ط¢آ­ط·آ·ط¢آ¯ط·آ·ط¢آ« ط·آ·ط¢آ®ط·آ·ط¢آ·ط·آ·ط¢آ£: {str(e)}'}), 500

# --- Product Endpoints ---

@api_mobile_bp.route('/products/search_stats', methods=['GET'])
@login_required
def get_search_stats():
    company_id = current_user.id
    now = datetime.utcnow()
    
    # 1. Get current month search count
    start_of_month = datetime(now.year, now.month, 1)
    monthly_search_count = SearchLog.query.filter(
        SearchLog.company_id == company_id,
        SearchLog.search_date >= start_of_month
    ).count()
    
    # 2. Get system limit
    limit_setting = SystemSetting.query.filter_by(setting_key='monthly_search_limit').first()
    monthly_search_limit = int(limit_setting.setting_value) if limit_setting and limit_setting.setting_value.isdigit() else 30
    
    # 3. Calculate remaining
    remaining = max(0, monthly_search_limit - monthly_search_count)
    if current_user.is_premium:
        remaining = -1 # Unlimited for premium
        
    return jsonify({
        'success': True,
        'search_count': monthly_search_count,
        'search_limit': monthly_search_limit,
        'remaining_searches': remaining,
        'is_premium': current_user.is_premium,
        'message': 'ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ·ط¢آ­ط·آ·ط¢آ«ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ©'
    })

@api_mobile_bp.route('/products/suggestions', methods=['GET'])
@login_required
def get_search_suggestions():
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify([])
    
    # Get blocked product names to exclude
    blocked_names = [bp.product_name.lower() for bp in BlockedProduct.query.all()]
    
    # Filter products by query and not blocked
    suggestions = ProductItem.query.filter(
        ProductItem.name.ilike(f'%{query}%'),
        ~func.lower(ProductItem.name).in_(blocked_names)
    ).limit(10).all()
    
    # Return unique names
    unique_names = list(set([p.name for p in suggestions]))
    result_list = unique_names[:10]
    return jsonify(result_list)

@api_mobile_bp.route('/products/recent', methods=['GET'])
@login_required
def get_recent_searches():
    # Get last 3 unique searches for the current user
    recent = db.session.query(SearchLog.search_term).filter(
        SearchLog.company_id == current_user.id
    ).order_by(SearchLog.search_date.desc()).all()
    
    unique_recent = []
    seen = set()
    for r in recent:
        term = r[0]
        if term and term not in seen:
            unique_recent.append(term)
            seen.add(term)
        if len(unique_recent) >= 3:
            break
            
    return jsonify(unique_recent)

@api_mobile_bp.route('/products/search', methods=['POST'])
@login_required
def search_products():
    data = request.get_json()
    search_term = data.get('search_term', '').strip()
    if not search_term:
        return jsonify({'error': 'ط·آ¸ط¸آ¹ط·آ·ط¢آ±ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ¥ط·آ·ط¢آ¯ط·آ·ط¢آ®ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ·ط¢آ­ط·آ·ط¢آ«'}), 400

    # Check search limit for non-premium
    if not current_user.is_premium:
        limit_setting = SystemSetting.query.filter_by(setting_key='monthly_search_limit').first()
        limit = int(limit_setting.setting_value) if limit_setting else 30
        now = datetime.utcnow()
        start_of_month = datetime(now.year, now.month, 1)
        count = SearchLog.query.filter(
            SearchLog.company_id == current_user.id,
            SearchLog.search_date >= start_of_month
        ).count()
        if count >= limit:
            return jsonify({'error': f'ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¯ ط·آ¸ط«â€ ط·آ·ط¢آµط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آµط·آ¸أ¢â‚¬آ° ({limit}) ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ·ط¢آ­ط·آ·ط¢آ« ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬طŒط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ±.'}), 403

    # Log search
    log = SearchLog(company_id=current_user.id, search_term=search_term, search_date=datetime.utcnow())
    db.session.add(log)

    # Get blocked products
    blocked = {bp.product_name.lower() for bp in BlockedProduct.query.all()}
    
    # Get all products and filter
    all_prods = ProductItem.query.all()
    filtered_prods = [p for p in all_prods if p.name.lower() not in blocked]
    names_list = [p.name for p in filtered_prods]

    # Fuzzy search محسّن — أولوية للمطابقة الدقيقة ثم البادئة ثم الـ fuzzy
    search_lower = search_term.lower()
    scored = {}  # name -> score

    for name in names_list:
        name_lower = name.lower()

        # 1. مطابقة تامة = 100
        if name_lower == search_lower:
            scored[name] = 100
            continue

        # 2. الاسم يبدأ بكلمة البحث = 95
        if name_lower.startswith(search_lower):
            scored[name] = 95
            continue

        # 3. كلمة البحث موجودة كاملةً داخل الاسم = 90
        if search_lower in name_lower:
            scored[name] = 90
            continue

        # 4. Fuzzy — نستخدم WRatio فقط (لا token_set_ratio لأنه يعطي نتائج بعيدة)
        # مع رفع الـ cutoff إلى 80 لتجنب الأسماء البعيدة
        s = fuzz.WRatio(search_term, name)
        if s >= 80:
            scored[name] = s

    # رتب تنازلياً وخذ أفضل 5 نتائج فقط
    top_names = sorted(scored.keys(), key=lambda n: scored[n], reverse=True)[:5]

    results = []
    for name in top_names:
        score = scored[name]
        prods = [p for p in filtered_prods if p.name == name]
        for p in prods:
            results.append({
                'item_code': getattr(p, 'item_code', None),
                'name': p.name,
                'quantity': p.quantity,
                'price': p.price,
                'discount': getattr(p, 'discount', None),
                'score': score
            })

    results.sort(key=lambda x: x['score'], reverse=True)
    log.results_count = len(results)
    db.session.commit()

    return jsonify({
        'search_term': search_term,
        'count': len(results),
        'results': results
    })

@api_mobile_bp.route('/products/favorites', methods=['GET'])
@login_required
def get_favorites():
    if session.get('user_type') != 'company':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    favs = FavoriteProduct.query.filter_by(company_id=current_user.id).order_by(FavoriteProduct.last_modified.desc()).all()
    fav_names = [f.product_name for f in favs]
    
    # Optimize N+1 query problem by fetching all relevant stock histories in one go
    latest_stocks = {}
    if fav_names:
        # Fetching all histories for these products, ordered by date descending
        all_stocks = ProductStockHistory.query.filter(ProductStockHistory.product_name.in_(fav_names)).order_by(ProductStockHistory.record_date.desc(), ProductStockHistory.recorded_at.desc()).all()
        # Keep only the first (latest) record for each product
        for stock in all_stocks:
            if stock.product_name not in latest_stocks:
                latest_stocks[stock.product_name] = stock
                
    result = []
    for f in favs:
        stock = latest_stocks.get(f.product_name)
        result.append({
            'id': f.id,
            'product_name': f.product_name,
            'current_stock': stock.quantity if stock else (f.quantity or '0'),
            'price': stock.price if stock else (f.price or '0'),
            'item_code': getattr(stock, 'item_code', None) if stock else None,
            'discount': getattr(stock, 'discount', None) if stock else None,
            'notes': f.notes or '',
            'added_at': f.added_at.strftime('%d/%m/%Y') if f.added_at else ''
        })
    
    return jsonify({
        'success': True,
        'is_premium': getattr(current_user, 'is_premium', False),
        'favorites': result
    })

@api_mobile_bp.route('/reports/balance', methods=['GET'])
@login_required
def get_balance_report():
    if session.get('user_type') != 'company':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    if not getattr(current_user, 'is_premium', False):
        return jsonify({'success': False, 'error': 'Premium subscription required'}), 403

    end_date_str = request.args.get('end_date')
    start_date_str = request.args.get('start_date')

    try:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else date.today()
    except:
        end_date = date.today()

    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else (end_date - timedelta(days=30))
    except:
        start_date = end_date - timedelta(days=30)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    report_days_count = (end_date - start_date).days + 1
    if report_days_count <= 0: report_days_count = 1

    favorites = FavoriteProduct.query.filter_by(company_id=current_user.id).all()
    fav_names = [f.product_name for f in favorites]
    reports_data = []

    # Optimize N+1 query problem by fetching all records in one query
    records_by_product = {name: [] for name in fav_names}
    if fav_names:
        all_records = ProductStockHistory.query.filter(
            ProductStockHistory.product_name.in_(fav_names),
            ProductStockHistory.record_date >= start_date,
            ProductStockHistory.record_date <= end_date
        ).order_by(ProductStockHistory.record_date).all()
        
        for r in all_records:
            records_by_product[r.product_name].append(r)

    for fav in favorites:
        product_name = fav.product_name
        records = records_by_product.get(product_name, [])

        if not records:
            reports_data.append({
                'product_name': product_name,
                'has_data': False,
                'message': 'لا توجد بيانات متاحة في هذه الفترة'
            })
            continue

        def pack_qty(q):
            """ط·آ·ط¢آ¹ط·آ·ط¢آ¨ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ¸ط¦â€™ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ© ط·آ¸ط¸آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ· ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ ط·آ·ط¢آ¨ط·آ·ط¢آ¯ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ  ط·آ¸ط¦â€™ط·آ·ط¢آ³ط·آ¸ط«â€ ط·آ·ط¢آ± (ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ·ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬ع‘ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¹ط·آ·ط¢آ±ط·آ·ط¢آ¶ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¹)."""
            try:
                return float(math.floor(max(0.0, float(q))))
            except (TypeError, ValueError):
                return 0.0

        numeric_records = []
        for rec in records:
            try:
                qty = pack_qty(rec.quantity)
                numeric_records.append({'date': rec.record_date.isoformat(), 'quantity': qty})
            except Exception:
                numeric_records.append({'date': rec.record_date.isoformat(), 'quantity': 0.0})

        # ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ·ط·آ¸أ¢â‚¬ع‘ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ± (ط·آ·ط¢آ¹ط·آ·ط¢آ¨ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ¸ط¦â€™ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ©) ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬
        # ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ³ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ  ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ : ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ·ط¢آ±ط·آ¸أ¢â‚¬ع‘ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ¬ط·آ·ط¢آ¨ = ط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¯ط·آ¸ط«â€ ط·آ·ط¢آ¨ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ© (ط·آ·ط¢آ²ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ·ط¢آ¯ط·آ·ط¢آ© ط·آ·ط¢آ±ط·آ·ط¢آµط·آ¸ط¸آ¹ط·آ·ط¢آ¯)
        # ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ·ط¢آ±ط·آ¸أ¢â‚¬ع‘ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ = ط·آ·ط¢آµط·آ·ط¢آ±ط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ© (ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ¹/ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬طŒط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ¸ط¦â€™/ط·آ¸أ¢â‚¬آ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آµط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ±ط·آ·ط¢آµط·آ¸ط¸آ¹ط·آ·ط¢آ¯) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ© ط·آ·ط¹آ¾ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ¨ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ·ط¢آ±ط·آ¸ط¸آ¾
        # ط·آ¸ط«â€ ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ£ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ¸أ¢â‚¬طŒ ط·آ·ط¹آ¾ط·آ¸ط¹ث†ط·آ·ط¢آ¹ط·آ·ط¢آ±ط·آ·ط¢آ¶ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¯ط·آ¸ط«â€ ط·آ·ط¢آ¨: ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¹ط·آ·ط¢آ¨ط·آ¸ط«â€ ط·آ·ط¢آ© ط·آ¸ط¸آ¹ط·آ¸ط¹ث†ط·آ¸أ¢â‚¬ع‘ط·آ·ط¹آ¾ط·آ·ط¢آ±ط·آ·ط¢آ­ ط·آ·ط¢آ£ط·آ¸أ¢â‚¬آ  ط·آ¸ط¸آ¹ط·آ·ط¢آ­ط·آ·ط¢آ¶ط·آ·ط¢آ± ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط·â€؛ط·آ·ط¢آ·ط·آ¸ط¸آ¹ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ¯ط·آ¸ط¸آ¾ط·آ·ط¢آ©.
        supply_packs = 0.0   # ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ¹ ط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¯ط·آ¸ط«â€ ط·آ·ط¢آ¨ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ© (ط·آ·ط¢آ²ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ±ط·آ·ط¢آµط·آ¸ط¸آ¹ط·آ·ط¢آ¯ ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ³ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¹آ¾)
        consumption_packs = 0.0  # ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ¹ ط·آ·ط¢آµط·آ·ط¢آ±ط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ© (ط·آ¸أ¢â‚¬آ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آµط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ±ط·آ·ط¢آµط·آ¸ط¸آ¹ط·آ·ط¢آ¯ ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ³ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¹آ¾)
        for i in range(1, len(numeric_records)):
            diff = numeric_records[i]['quantity'] - numeric_records[i - 1]['quantity']
            if diff > 0:
                supply_packs += diff
            elif diff < 0:
                consumption_packs += abs(diff)

        start_p = int(pack_qty(numeric_records[0]['quantity']))
        end_p = int(pack_qty(numeric_records[-1]['quantity']))
        net_change = end_p - start_p  # ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ¬ط·آ·ط¢آ¨ = ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ±ط·آ·ط¢آµط·آ¸ط¸آ¹ط·آ·ط¢آ¯ ط·آ·ط¢آ²ط·آ·ط¢آ§ط·آ·ط¢آ¯ ط·آ·ط¢آµط·آ·ط¢آ§ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ·ط¹آ¾ط·آ·ط¢آ±ط·آ·ط¢آ©

        supply_packs = int(pack_qty(supply_packs))
        consumption_packs = int(pack_qty(consumption_packs))

        # ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ·ط¢آ³ط·آ·ط¢آ· ط·آ·ط¢آµط·آ·ط¢آ±ط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ© ط·آ¸ط¸آ¹ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ = ط·آ·ط¢آ¥ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ ط·آ·ط¢آµط·آ·ط¢آ±ط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ© ط·آ£ط¢آ· ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ¯ ط·آ·ط¢آ£ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ±
        adc = int(pack_qty(consumption_packs / float(report_days_count))) if report_days_count else 0

        # ط·آ·ط¹آ¾ط·آ·ط·â€؛ط·آ·ط¢آ·ط·آ¸ط¸آ¹ط·آ·ط¢آ© ط·آ·ط¢آ±ط·آ·ط¢آµط·آ¸ط¸آ¹ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ© ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¯ ط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¾ط·آ·ط¢آ³ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ·ط¢آ³ط·آ·ط¢آ· ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ·ط¢آ±ط·آ¸ط¸آ¾
        days_of_cover = None
        doc_label_ar = '-'
        if adc > 0:
            days_of_cover = int(end_p // adc)
            doc_label_ar = f'تكفي لمدة {days_of_cover} يوم'
        elif end_p > 0:
            doc_label_ar = 'لا يوجد استهلاك مسجل في هذه الفترة (لا يمكن حساب التغطية)'
        else:
            doc_label_ar = 'رصيد صفر'

        # ط·آ·ط¢آ­ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ© ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آ¶ط·آ·ط¢آ­ط·آ·ط¢آ© ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬آ¦ (ط·آ·ط¢آ¨ط·آ·ط¢آ¯ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ  ط·آ¯ط¦â€™ ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¹ط·آ·ط¢آ©)
        if end_p <= 0:
            health = 'empty'
            health_ar = 'رصيد الشركة صفر - يحتاج توريد من المندوب'
        elif adc <= 0:
            health = 'no_movement'
            health_ar = 'لا يوجد سحب ملحوظ من الرصيد خلال هذه الفترة'
        elif days_of_cover is not None and days_of_cover < 7:
            health = 'critical'
            health_ar = 'تغطية أقل من أسبوع - مخاطر نفاد الرصيد قريباً'
        elif days_of_cover is not None and days_of_cover < 14:
            health = 'low'
            health_ar = 'تغطية أقل من أسبوعين - يرجى مراقبة الرصيد'
        elif days_of_cover is not None and days_of_cover > 120:
            health = 'high'
            health_ar = 'الرصيد مرتفع جداً مقارنة بمعدل الاستهلاك'
        else:
            health = 'ok'
            health_ar = 'تغطية جيدة وتتناسب مع معدل الاستهلاك'

        # ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸ط¹ث†ط·آ·ط¢آ¹ط·آ·ط¢آ±ط·آ·ط¢آ¶ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¯ط·آ¸ط«â€ ط·آ·ط¢آ¨: ط·آ·ط¢آ¹ط·آ·ط¢آ¨ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ¸ط¸آ¹ط·آ¸ط¹ث†ط·آ¸أ¢â‚¬ع‘ط·آ·ط¹آ¾ط·آ·ط¢آ±ط·آ·ط¢آ­ ط·آ·ط¢آ¥ط·آ·ط¢آ­ط·آ·ط¢آ¶ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ§ ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط·إ’ط·آ¸أ¢â‚¬آ¹ ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ° ط·آ·ط¢آµط·آ·ط¢آ±ط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¦â€™ط·آ·ط¢آ© (ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ¯ط·آ¸ط¸آ¾ ط·آ·ط¹آ¾ط·آ·ط·â€؛ط·آ·ط¢آ·ط·آ¸ط¸آ¹ط·آ·ط¢آ© 14 ط·آ¸ط¸آ¹ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹)
        target_days = 14
        need_for_target = int(math.ceil(adc * target_days)) if adc > 0 else 0
        reorder_packs = max(0, need_for_target - end_p)
        reorder_note_ar = (
            f'بناءً على معدل الاستهلاك الحالي: يحتاج لتوريد {reorder_packs} عبوة لتغطية استهلاك {target_days} يوم.'
            if adc > 0
            else 'لا يمكن اقتراح كمية التوريد لعدم وجود نمط سحب واضح في هذه الفترة.'
        )

        # ط·آ·ط¢آ§ط·آ·ط¹آ¾ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ¸أ¢â‚¬طŒ ط·آ·ط¢آ¨ط·آ·ط¢آ³ط·آ¸ط¸آ¹ط·آ·ط¢آ· ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ·ط¢آ§ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ (ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¹ ط·آ·ط¢آ£ط·آ¸ط¦â€™ط·آ·ط¢آ«ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ¹ط·آ·ط¹آ¾ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ¢ط¢آ±5 ط·آ·ط¢آ¹ط·آ·ط¢آ´ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ©)
        if net_change > 0:
            trend_ar = 'الرصيد زاد صافياً خلال الفترة'
        elif net_change < 0:
            trend_ar = 'الرصيد انخفض صافياً خلال الفترة'
        else:
            trend_ar = 'رصيد بداية الفترة يساوي النهاية (تغير صافي صفر)'

        insight_ar = (
            f'صرف الشركة {consumption_packs} عبوة، وتوريد المندوب {supply_packs} عبوة خلال {report_days_count} يوماً. '
            f'متوسط سحب الشركة {adc} عبوة/يوم.'
        )

        reports_data.append({
            'product_name': product_name,
            'has_data': True,
            'unit_label': 'عبوة',
            # ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ¸أ¢â‚¬ع‘ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¬ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ© (ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ·ط·آ¸أ¢â‚¬ع‘ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آ¶ط·آ·ط¢آ­)
            'start_packs': start_p,
            'end_packs': end_p,
            'net_change_packs': net_change,
            'consumption_packs': consumption_packs,
            'supply_packs': supply_packs,
            'avg_daily_consumption_packs': adc,
            'days_of_cover': days_of_cover,
            'days_of_cover_label_ar': doc_label_ar,
            'health': health,
            'health_label_ar': health_ar,
            'reorder_packs': reorder_packs,
            'reorder_note_ar': reorder_note_ar,
            'trend_label_ar': trend_ar,
            'insight_ar': insight_ar,
            # ط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ¸ط¸آ¾ط·آ¸أ¢â‚¬ع‘ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ³ط·آ·ط¢آ® ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ©
            'start_qty': start_p,
            'end_qty': end_p,
            'total_inc': supply_packs,
            'total_dec': consumption_packs,
            'daily_avg': float(adc),
            'trend': trend_ar,
            'forecast': doc_label_ar,
            'safety_stock': 0,
            'recommended_qty': reorder_packs,
            'history': numeric_records
        })

    return jsonify({
        'success': True,
        'summary': {
            'total_products': len(favorites),
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d')
        },
        'reports': reports_data
    })

@api_mobile_bp.route('/products/favorites/toggle', methods=['POST'])
@login_required
def toggle_favorite():
    if session.get('user_type') != 'company':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
    data = request.get_json()
    prod_name = data.get('product_name')
    if not prod_name:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¾ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ¨.'}), 400
        
    fav = FavoriteProduct.query.filter_by(company_id=current_user.id, product_name=prod_name).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
        return jsonify({'success': True, 'is_favorite': False, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ°ط·آ¸ط¸آ¾ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ·ط¢آµط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ¸ط¸آ¾.'})
    else:
        # Get price and quantity from current stock
        stock = ProductStockHistory.query.filter_by(product_name=prod_name).order_by(ProductStockHistory.record_date.desc()).first()
        new_fav = FavoriteProduct(
            company_id=current_user.id,
            product_name=prod_name,
            price=stock.price if stock else 0,
            quantity=stock.quantity if stock else 0,
            added_at=datetime.utcnow(),
            last_modified=datetime.utcnow()
        )
        db.session.add(new_fav)
        db.session.commit()
        return jsonify({'success': True, 'is_favorite': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¥ط·آ·ط¢آ¶ط·آ·ط¢آ§ط·آ¸ط¸آ¾ط·آ·ط¢آ© ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ·ط¢آµط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ¸ط¸آ¾.'})

@api_mobile_bp.route('/products/report_request', methods=['POST'])
@login_required
def request_product_report():
    if session.get('user_type') != 'company':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
    data = request.get_json()
    prod_name = data.get('product_name')
    if not prod_name:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¾ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ¨.'}), 400

    # ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ Monthly limit check ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬
    # Free users: 1 report request/month | Premium users: 5 report requests/month
    monthly_limit = 5 if current_user.is_premium else 1
    now = datetime.utcnow()

    # Count requests this calendar month for this company
    from sqlalchemy import text
    target_month = f"{now.year}-{now.month:02d}"
    count_query = text("""
        SELECT COUNT(*) FROM toby_request_report 
        WHERE company_id = :cid 
        AND substr(timestamp, 1, 7) = :target_month
        AND message LIKE 'PRR_JSON:%'
    """)
    result = db.session.execute(count_query, {'cid': current_user.id, 'target_month': target_month})
    monthly_count = result.scalar() or 0

    if monthly_count >= monthly_limit:
        if current_user.is_premium:
            msg = f'ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¾ط·آ·ط¢آ¯ط·آ·ط¹آ¾ ط·آ·ط¢آ­ط·آ·ط¢آ¯ ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ±ط·آ¸ط¸آ¹ ({monthly_limit} ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ·ط¹آ¾) ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ ط·آ·ط¢آ³ط·آ·ط¢آ®ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ²ط·آ·ط¢آ©. ط·آ¸ط¸آ¹ط·آ·ط¹آ¾ط·آ·ط¢آ¬ط·آ·ط¢آ¯ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ¯ ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ¨ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ¸ط¸آ¹ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ´ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ± ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬آ¦.'
        else:
            msg = 'ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¾ط·آ·ط¢آ¯ط·آ·ط¹آ¾ ط·آ·ط¢آ­ط·آ·ط¢آ¯ ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¹ط·آ·ط¢آ© (ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آ­ط·آ·ط¢آ¯ ط·آ·ط¢آ´ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹). ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ±ط·آ¸أ¢â‚¬ع‘ط·آ¸ط¸آ¹ط·آ·ط¢آ© ط·آ·ط¢آ¥ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ ط·آ·ط¢آ³ط·آ·ط¢آ®ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ²ط·آ·ط¢آ© ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آµط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ° 5 ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ´ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹.'
        return jsonify({
            'success': False,
            'message': msg,
            'limit_reached': True,
            'monthly_limit': monthly_limit,
            'monthly_count': monthly_count
        }), 429
    # ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬

    payload = {
        'type': 'product_report_request',
        'product_name': prod_name,
        'status': 'pending',
        'timestamp': now.isoformat()
    }
    
    try:
        insert_query = text("INSERT INTO toby_request_report (company_id, message, timestamp) VALUES (:cid, :msg, :ts)")
        db.session.execute(insert_query, {
            'cid': current_user.id,
            'msg': 'PRR_JSON:' + json.dumps(payload, ensure_ascii=False),
            'ts': now
        })
        db.session.commit()
        remaining = monthly_limit - (monthly_count + 1)
        return jsonify({
            'success': True,
            'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¥ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¥ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ·ط¢آ© ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ­.',
            'remaining_requests': remaining,
            'monthly_limit': monthly_limit
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'ط·آ·ط¢آ­ط·آ·ط¢آ¯ط·آ·ط¢آ« ط·آ·ط¢آ®ط·آ·ط¢آ·ط·آ·ط¢آ£ ط·آ·ط¢آ£ط·آ·ط¢آ«ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ·ط¢آ¥ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨: {str(e)}'}), 500

@api_mobile_bp.route('/products/remember', methods=['POST'])
@login_required
def remember_product():
    data = request.get_json()
    prod_name = data.get('product_name')
    quantity = data.get('quantity', 0)
    
    if not prod_name:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¾ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ¨.'}), 400
        
    # Check limit: 1 for free, 5 for premium
    limit = 5 if current_user.is_premium else 1
    existing_count = ProductReminder.query.filter_by(company_id=current_user.id).count()
    
    # If already exists, we update it regardless of limit
    existing = ProductReminder.query.filter_by(company_id=current_user.id, product_name=prod_name).first()
    if existing:
        existing.quantity = quantity
        existing.recorded_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¹آ¾ط·آ·ط¢آ­ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ« ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ·ط¢آ°ط·آ¸ط¦â€™ط·آ·ط¢آ±ط·آ·ط¢آ©.'})
    
    if existing_count >= limit:
        msg = 'ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¯ ط·آ¸ط«â€ ط·آ·ط¢آµط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آµط·آ¸أ¢â‚¬آ° (5 ط·آ·ط¢آ£ط·آ·ط¢آµط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ¸ط¸آ¾) ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ ط·آ·ط¢آ³ط·آ·ط¢آ®ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ²ط·آ·ط¢آ©.' if current_user.is_premium else 'ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ ط·آ·ط¢آ³ط·آ·ط¢آ®ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¹ط·آ·ط¢آ© ط·آ·ط¹آ¾ط·آ·ط¢آ³ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ­ ط·آ·ط¢آ¨ط·آ·ط¹آ¾ط·آ·ط¢آ°ط·آ¸ط¦â€™ط·آ·ط¢آ± ط·آ·ط¢آµط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¾ ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آ­ط·آ·ط¢آ¯ ط·آ¸ط¸آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ·.'
        return jsonify({'success': False, 'message': msg}), 403
        
    reminder = ProductReminder(
        company_id=current_user.id,
        product_name=prod_name,
        quantity=quantity,
        recorded_at=datetime.utcnow()
    )
    db.session.add(reminder)
    db.session.commit()
    return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ­ط·آ¸ط¸آ¾ط·آ·ط¢آ¸ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ© ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ°ط·آ¸ط¦â€™ط·آ·ط¢آ±.'})

# --- Appointment Endpoints ---

@api_mobile_bp.route('/appointments', methods=['GET'])
@login_required
def get_appointments():
    # Check if appointments are enabled
    setting = SystemSetting.query.filter_by(setting_key='appointments_enabled').first()
    if setting and setting.setting_value != 'true':
        return jsonify({'status': 'maintenance', 'message': 'MAINTENANCE_MODE'})
    appts = Appointment.query.filter_by(company_id=current_user.id).order_by(Appointment.appointment_date.desc()).all()
    data = []
    for a in appts:
        data.append({
            'id': a.id,
            'date': a.appointment_date.isoformat(),
            'time': a.appointment_time.strftime('%H:%M'),
            'purpose': a.purpose,
            'product': a.product_item_name,
            'status': a.status,
            'response': a.admin_response,
            'created_at': a.created_at.isoformat()
        })
    return jsonify(data)

@api_mobile_bp.route('/appointments/book', methods=['POST'])
@login_required
def book_appointment():
    # Check if appointments are enabled
    setting = SystemSetting.query.filter_by(setting_key='appointments_enabled').first()
    if setting and setting.setting_value != 'true':
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ¹ط·آ·ط¢آ°ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ط·آ·ط¥â€™ ط·آ·ط¢آ­ط·آ·ط¢آ¬ط·آ·ط¢آ² ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آ¹ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ·ط¢آ­ ط·آ·ط¢آ­ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹.'}), 503

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400
        
    try:
        apt_date = datetime.strptime(data.get('date'), '%Y-%m-%d').date()
        apt_time = datetime.strptime(data.get('time'), '%H:%M').time()
        
        # Simple validation
        if apt_date < date.today():
             return jsonify({'success': False, 'message': 'ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ­ط·آ·ط¢آ¬ط·آ·ط¢آ² ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ¹ط·آ·ط¢آ¯ ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ® ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ§ط·آ·ط¢آ¶ط·آ¸ط¹â€ .'}), 400
             
        new_appt = Appointment(
            company_id=current_user.id,
            appointment_date=apt_date,
            appointment_time=apt_time,
            purpose=data.get('purpose'),
            product_item_name=data.get('product'),
            notes=data.get('notes'),
            status='pending'
        )
        db.session.add(new_appt)
        db.session.commit()
        
        # Admin notification
        notif = Notification(
            title=f'طلب موعد جديد من {current_user.company_name}',
            message=f'تم تقديم طلب موعد بتاريخ {data.get("date")} الساعة {data.get("time")}.',
            target_type='all',
            created_by=current_user.id
        )
        db.session.add(notif)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'تم إرسال طلب الموعد بنجاح.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# --- Community Endpoints ---

def _community_post_visible_api(p):
    """ط·آ¸ط¸آ¹ط·آ·ط¢آ¸ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ± ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ¸ط«â€ ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ§ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¸آ¹ط·آ¸ط¹ث†ط·آ·ط¢آ®ط·آ¸ط¸آ¾ط·آ¸أ¢â‚¬ع©ط·آ¸ط¹ع© ط·آ·ط¢آµط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¢آ­ط·آ·ط¢آ©ط·آ¸أ¢â‚¬آ¹ (False/0). NULL = ط·آ·ط¢آ¸ط·آ·ط¢آ§ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ±."""
    v = getattr(p, 'is_active', None)
    if v is None:
        return True
    if v is False:
        return False
    try:
        return int(v) != 0
    except (TypeError, ValueError):
        return bool(v)

@api_mobile_bp.route('/community/suggestions', methods=['GET'])
@login_required
def get_community_suggestions():
    from models import Company, CompanyFollow
    try:
        follows = CompanyFollow.query.filter_by(follower_id=current_user.id).all()
        excluded_ids = {f.followed_id for f in follows}
        excluded_ids.add(current_user.id)
        
        # We can order randomly or by newest. Let's do random using func.random() and limit 10
        suggestions = Company.query.filter(
            ~Company.id.in_(excluded_ids),
            Company.is_active == True
        ).order_by(db.func.random()).limit(15).all()
        
        data = []
        for c in suggestions:
            data.append({
                'id': c.id,
                'company_name': c.company_name,
                'avatar': getattr(c, 'avatar', 'default-male'),
                'is_verified': getattr(c, 'is_verified', False),
                'is_premium': getattr(c, 'is_premium', False),
            })
            
        return jsonify({'success': True, 'suggestions': data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500



@api_mobile_bp.route('/community/posts', methods=['GET'])
@login_required
def get_posts():
    cand = CommunityPost.query.order_by(CommunityPost.created_at.desc()).limit(500).all()
    posts = [p for p in cand if _community_post_visible_api(p)]
    # Bulk loading stats for get_posts
    post_ids = [p.id for p in posts]
    likes_dict = {}
    comments_dict = {}
    views_dict = {}
    liked_by_me_set = set()

    if post_ids:
        try:
            likes_counts = db.session.query(PostLike.post_id, func.count(PostLike.id)).filter(PostLike.post_id.in_(post_ids)).group_by(PostLike.post_id).all()
            likes_dict = {pid: count for pid, count in likes_counts}
        except Exception:
            pass

        try:
            comments_counts = db.session.query(PostComment.post_id, func.count(PostComment.id)).filter(PostComment.post_id.in_(post_ids), PostComment.is_active == True).group_by(PostComment.post_id).all()
            comments_dict = {pid: count for pid, count in comments_counts}
        except Exception:
            pass

        try:
            views_counts = db.session.query(PostView.post_id, func.count(PostView.id)).filter(PostView.post_id.in_(post_ids)).group_by(PostView.post_id).all()
            views_dict = {pid: count for pid, count in views_counts}
        except Exception:
            pass

        my_likes_dict = {}
        try:
            my_likes = PostLike.query.filter(PostLike.post_id.in_(post_ids), PostLike.company_id == current_user.id).all()
            liked_by_me_set = {like.post_id for like in my_likes}
            my_likes_dict = {like.post_id: getattr(like, 'reaction_type', 'heart') or 'heart' for like in my_likes}
        except Exception:
            pass

        top_reactions_dict = {}
        try:
            all_likes = PostLike.query.filter(PostLike.post_id.in_(post_ids)).all()
            from collections import Counter
            reaction_counters = {}
            for l in all_likes:
                pid = l.post_id
                if pid not in reaction_counters:
                    reaction_counters[pid] = Counter()
                rt = getattr(l, 'reaction_type', 'heart') or 'heart'
                reaction_counters[pid][rt] += 1
            
            for pid, counter in reaction_counters.items():
                top_reactions = [k for k, v in counter.most_common(3)]
                top_reactions_dict[pid] = top_reactions
        except Exception:
            pass

    followed_company_ids = set()
    if current_user.is_authenticated:
        try:
            from models import CompanyFollow
            follows = CompanyFollow.query.filter_by(follower_id=current_user.id).all()
            followed_company_ids = {f.followed_id for f in follows}
        except Exception:
            pass

    data = []
    for p in posts:
        liked = p.id in liked_by_me_set

        # Get last comment individually since it's tricky to bulk fetch latest child natively easily,
        # but the removed 4 count/fetch queries already reduce 80% DB load.
        last_comment_obj = PostComment.query.filter_by(post_id=p.id, is_active=True)\
            .order_by(PostComment.created_at.desc()).first()

        last_comment = None
        if last_comment_obj:
            c_anon = getattr(last_comment_obj, 'is_anonymous', False)
            c_company = last_comment_obj.company
            last_comment = {
                'id': last_comment_obj.id,
                'content': last_comment_obj.content,
                'company_name': (getattr(c_company, 'company_name', 'شركة محذوفة') if not c_anon else ANONYMOUS_DISPLAY_NAME),
                'created_at': last_comment_obj.created_at.isoformat()
            }

        likes_n = likes_dict.get(p.id, 0)
        comments_n = comments_dict.get(p.id, 0)
        views_n = views_dict.get(p.id, 0)

        # ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¢آ¬ ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ§ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ­ط·آ¸ط¸آ¾ط·آ¸ط«â€ ط·آ·ط¢آ¸ط·آ·ط¢آ© (JSON strings ط£آ¢أ¢â‚¬آ أ¢â‚¬â„¢ lists) ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬
        import json as _json_get
        _file_ids = []
        _m_types = []
        _m_previews = []
        try:
            raw_fids = getattr(p, 'media_file_ids', None)
            if raw_fids:
                _file_ids = _json_get.loads(raw_fids) if isinstance(raw_fids, str) else raw_fids
        except Exception:
            pass
        try:
            raw_mt = getattr(p, 'media_types', None)
            if raw_mt:
                _m_types = _json_get.loads(raw_mt) if isinstance(raw_mt, str) else raw_mt
        except Exception:
            pass
        try:
            raw_mp = getattr(p, 'media_preview_urls', None)
            if raw_mp:
                _m_previews = _json_get.loads(raw_mp) if isinstance(raw_mp, str) else raw_mp
        except Exception:
            pass

        # Safe access للشركة في حالة انها اتحذفت
        _co = p.company
        _co_name = getattr(_co, 'company_name', 'شركة محذوفة') if _co else 'شركة محذوفة'
        _co_avatar = getattr(_co, 'avatar', 'default-male') if _co else 'default-male'
        _co_premium = getattr(_co, 'is_premium', False) if _co else False
        _co_verified = getattr(_co, 'is_verified', False) if _co else False

        data.append({
            'id': p.id,
            'company_id': p.company_id,
            'company_name': _co_name if not p.is_anonymous else ANONYMOUS_DISPLAY_NAME,
            'avatar': _co_avatar if not p.is_anonymous else 'default-male',
            'content': p.content or '',
            'created_at': p.created_at.isoformat(),
            'likes_count': likes_n,
            'comments_count': comments_n,
            'views': views_n,
            'views_count': views_n,
            'liked_by_me': liked,
            'is_mine': p.company_id == current_user.id,
            'is_anonymous': p.is_anonymous,
            'is_pinned': p.is_pinned,
            'is_followed': getattr(p, 'company_id', None) in followed_company_ids or getattr(p, 'company_id', None) == current_user.id,
            'is_premium': _co_premium if not p.is_anonymous else False,
            'is_verified': _co_verified if not p.is_anonymous else False,
            'last_comment': last_comment,
            'media_file_ids': _file_ids,
            'media_types': _m_types,
            'media_preview_urls': _m_previews,
            'audio_file_id': getattr(p, 'audio_file_id', None),
            'audio_url': getattr(p, 'audio_url', None),
            'top_reactions': top_reactions_dict.get(p.id, []),
            'my_reaction_type': my_likes_dict.get(p.id, 'heart')
        })
    data = [_normalize_anonymous_entity(item) for item in data]
    return jsonify(data)


@api_mobile_bp.route('/community/posts/create', methods=['POST'])
@login_required
def create_post():
    data = request.get_json()
    content = (data.get('content') or '').strip()

    # ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ§ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ (ط·آ·ط¢آ§ط·آ·ط¢آ®ط·آ·ط¹آ¾ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ¸ط¸آ¹)
    media_file_ids = data.get('media_file_ids', [])
    media_types = data.get('media_types', [])
    media_preview_urls = data.get('media_preview_urls', [])
    audio_file_id = (data.get('audio_file_id') or '').strip()
    audio_url = (data.get('audio_url') or '').strip()
    if isinstance(media_file_ids, str):
        media_file_ids = [media_file_ids] if media_file_ids else []
    if isinstance(media_types, str):
        media_types = [media_types] if media_types else []
    if isinstance(media_preview_urls, str):
        media_preview_urls = [media_preview_urls] if media_preview_urls else []
    has_audio_attachment = bool(audio_file_id or audio_url)
    has_audio_only_post = bool(has_audio_attachment and not content and not media_file_ids)
    if has_audio_only_post:
        media_file_ids = ['__audio__']

    # ط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ¨ ط·آ·ط¢آ£ط·آ¸أ¢â‚¬آ  ط·آ¸ط¸آ¹ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ  ط·آ¸أ¢â‚¬طŒط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ¸ط¦â€™ ط·آ¸أ¢â‚¬آ ط·آ·ط¢آµ ط·آ·ط¢آ£ط·آ¸ط«â€  ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ§ ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬â€چ
    if not content and not media_file_ids:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ­ط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ£ط·آ¸ط«â€  ط·آ·ط¢آµط·آ¸ط«â€ ط·آ·ط¢آ±ط·آ·ط¢آ© ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ¨ط·آ·ط¢آ©.'}), 400
        
    # Check if user is blocked from messaging/posting
    if getattr(current_user, 'messaging_blocked', False):
        return jsonify({'success': False, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¥ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ¸ط¸آ¾ ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ¸ط¦â€™ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ·ط¢آ± ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¬ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ®ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ·ط¢آ©. ط·آ¸ط¸آ¹ط·آ·ط¢آ±ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آµط·آ¸أ¢â‚¬â€چ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¥ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ·ط¢آ©.'}), 403
        
    if has_audio_only_post:
        media_file_ids = []

    import json as _json
    post = CommunityPost(
        company_id=current_user.id,
        content=content,
        is_anonymous=data.get('is_anonymous', False),
        created_at=datetime.utcnow()
    )
    # ط·آ·ط¢آ­ط·آ¸ط¸آ¾ط·آ·ط¢آ¸ ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ§ ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¯ط·آ·ط¢آ© ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ¬ط·آ¸ط«â€ ط·آ·ط¢آ¯ط·آ·ط¢آ© ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â€ڑآ¬ model
    for attr, val in [
        ('media_file_ids', _json.dumps(media_file_ids) if media_file_ids else None),
        ('media_types', _json.dumps(media_types) if media_types else None),
        ('media_preview_urls', _json.dumps(media_preview_urls) if media_preview_urls else None),
        ('audio_file_id', audio_file_id or None),
        ('audio_url', audio_url or None),
    ]:
        try:
            if val is not None:
                setattr(post, attr, val)
        except Exception:
            pass
    db.session.add(post)
    db.session.commit()
    # ط·آ·ط¢آ¥ط·آ·ط¢آ±ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ¹ ط·آ¸ط¦â€™ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ¸ط«â€ ط·آ·ط¢آ± ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ§ ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ GET /community/posts ط·آ·ط¢آ­ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ° ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ²ط·آ¸أ¢â‚¬ع©ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬طŒ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ Firestore
    p = post
    liked = PostLike.query.filter_by(post_id=p.id, company_id=current_user.id).first() is not None
    response_data = {
        'id': p.id,
        'company_id': p.company_id,
        'company_name': p.company.company_name if not p.is_anonymous else ANONYMOUS_DISPLAY_NAME,
        'avatar': p.company.avatar if not p.is_anonymous else 'default-male',
        'content': p.content,
        'created_at': p.created_at.isoformat(),
        'likes_count': 0,
        'comments_count': 0,
        'liked_by_me': liked,
        'is_mine': True,
        'is_anonymous': p.is_anonymous,
        'is_pinned': p.is_pinned,
        'is_premium': getattr(p.company, 'is_premium', False) if not p.is_anonymous else False,
        'is_verified': getattr(p.company, 'is_verified', False) if not p.is_anonymous else False,
        'last_comment': None,
        'media_file_ids': media_file_ids,
        'media_types': media_types,
        'media_preview_urls': media_preview_urls,
        'audio_file_id': audio_file_id or None,
        'audio_url': audio_url or None,
    }
    response_data = _normalize_anonymous_entity(response_data)

    # --- Notify followers (fire-and-forget) ---
    if not post.is_anonymous:
        try:
            followers = CompanyFollow.query.filter_by(followed_id=current_user.id).all()
            for f in followers:
                body_text = _notification_preview(content, 80, 'نشر منشورًا جديدًا في المجتمع.')
                send_push_notification(
                    target_company_id=f.follower_id,
                    title=f'منشور جديد من {current_user.company_name}',
                    body=body_text,
                    data={'type': 'followed_post', 'post_id': post.id}
                )
        except Exception:
            pass

    return jsonify({'success': True, 'message': 'تم نشر المنشور بنجاح.', 'post': response_data})

@api_mobile_bp.route('/community/posts/<int:post_id>/like', methods=['POST'])
@login_required
def toggle_like(post_id):
    post = CommunityPost.query.get_or_404(post_id)
    
    req_data = request.get_json(silent=True) or {}
    reaction_type = req_data.get('type', 'heart')
    
    like = PostLike.query.filter_by(post_id=post_id, company_id=current_user.id).first()
    
    liked = False
    if like:
        if getattr(like, 'reaction_type', 'heart') == reaction_type:
            db.session.delete(like)
            db.session.commit()
            liked = False
        else:
            like.reaction_type = reaction_type
            db.session.commit()
            liked = True
    else:
        new_like = PostLike(post_id=post_id, company_id=current_user.id, reaction_type=reaction_type)
        db.session.add(new_like)
        liked = True
        
        # Create notification if not own post
        if post.company_id != current_user.id:
            notif = CommunityNotification(
                company_id=post.company_id,
                post_id=post.id,
                from_company_id=current_user.id,
                message=f'أعجب {current_user.company_name} بمنشورك.',
                notification_type='like'
            )
            db.session.add(notif)
            
        db.session.commit()
        current_likes_count = PostLike.query.filter_by(post_id=post_id).count()
        
        # Send push notification
        if post.company_id != current_user.id:
            send_push_notification(
                post.company_id, 
                "إعجاب جديد",
                f"أعجب {current_user.company_name} بمنشورك.",
                {"type": "like", "post_id": post_id}
            )
            
        return jsonify({'success': True, 'liked': liked, 'likes_count': current_likes_count})

@api_mobile_bp.route('/community/posts/<int:post_id>/comments', methods=['GET'])
@login_required
def get_comments(post_id):
    comments = PostComment.query.filter_by(post_id=post_id, is_active=True).order_by(PostComment.created_at.asc()).all()
    data = []
    for c in comments:
        parent_comment = c.parent if getattr(c, 'parent_id', None) else None
        parent_company_name = None
        if parent_comment:
            if getattr(parent_comment, 'is_anonymous', False):
                parent_company_name = 'مستخدم مجهول'
            elif getattr(parent_comment, 'company', None):
                parent_company_name = parent_comment.company.company_name

        data.append({
            'id': c.id,
            'company_id': c.company_id,
            'company_name': c.company.company_name if not c.is_anonymous else 'ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬آ¦ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬طŒط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چ',
            'avatar': c.company.avatar if not c.is_anonymous else 'default-male',
            'content': c.content,
            'created_at': c.created_at.isoformat(),
            'is_mine': c.company_id == current_user.id,
            'is_anonymous': c.is_anonymous,
            'parent_id': c.parent_id,
            'parent_company_name': parent_company_name,
            'parent_preview': (parent_comment.content[:120] if parent_comment and parent_comment.content else None),
        })
    data = [_normalize_anonymous_entity(item) for item in data]
    return jsonify(data)

@api_mobile_bp.route('/community/posts/<int:post_id>/edit', methods=['POST'])
@login_required
def edit_post(post_id):
    post = CommunityPost.query.get_or_404(post_id)
    if post.company_id != current_user.id:
        return jsonify({'success': False, 'message': 'ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ­ ط·آ¸أ¢â‚¬â€چط·آ¸ط¦â€™ ط·آ·ط¢آ¨ط·آ·ط¹آ¾ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ¸ط«â€ ط·آ·ط¢آ±.'}), 403
    
    data = request.get_json()
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ­ط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ° ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ£ط·آ¸أ¢â‚¬آ  ط·آ¸ط¸آ¹ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ  ط·آ¸ط¸آ¾ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ·ط·â€؛ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹.'}), 400
        
    post.content = content
    post.is_anonymous = data.get('is_anonymous', post.is_anonymous)
    db.session.commit()
    return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¹آ¾ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ¸ط«â€ ط·آ·ط¢آ±.'})

@api_mobile_bp.route('/community/posts/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = CommunityPost.query.get_or_404(post_id)
    if post.company_id != current_user.id:
        # Allow admins? For now only owner
        return jsonify({'success': False, 'message': 'ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ­ ط·آ¸أ¢â‚¬â€چط·آ¸ط¦â€™ ط·آ·ط¢آ¨ط·آ·ط¢آ­ط·آ·ط¢آ°ط·آ¸ط¸آ¾ ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ¸ط«â€ ط·آ·ط¢آ±.'}), 403
    
    post.is_active = False # Soft delete
    db.session.commit()
    return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ­ط·آ·ط¢آ°ط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ¸ط«â€ ط·آ·ط¢آ±.'})

@api_mobile_bp.route('/community/posts/<int:post_id>/report', methods=['POST'])
@login_required
def report_post(post_id):
    post = CommunityPost.query.get_or_404(post_id)
    if post.company_id == current_user.id:
        return jsonify({'success': False, 'message': 'ظ„ط§ ظٹظ…ظƒظ†ظƒ ط§ظ„ط¥ط¨ظ„ط§ط؛ ط¹ظ† ظ…ظ†ط´ظˆط±ظƒ.'}), 400

    data = request.get_json() or {}
    reason = (data.get('reason') or '').strip()

    existing_report = PostReport.query.filter_by(post_id=post_id, reporter_id=current_user.id).first()
    if existing_report:
        return jsonify({'success': False, 'message': 'طھظ… ط¥ط±ط³ط§ظ„ ط¨ظ„ط§ط؛ظƒ ط¹ظ„ظ‰ ظ‡ط°ط§ ط§ظ„ظ…ظ†ط´ظˆط± ط¨ط§ظ„ظپط¹ظ„.'}), 409

    report = PostReport(
        post_id=post_id,
        reporter_id=current_user.id,
        reason=reason[:200] if reason else None,
        created_at=datetime.utcnow()
    )
    db.session.add(report)
    db.session.commit()

    owner = Company.query.get(post.company_id)
    preview = ((post.content or '').strip() or 'ظ…ظ†ط´ظˆط± ط¨ط¯ظˆظ† ظ†طµ').replace('\r', ' ').replace('\n', ' ')
    if len(preview) > 180:
        preview = preview[:177] + '...'

    media_flags = []
    if getattr(post, 'image_file_id', None):
        media_flags.append('طµظˆط±ط©')
    if getattr(post, 'video_file_id', None):
        media_flags.append('ظپظٹط¯ظٹظˆ')
    if getattr(post, 'audio_file_id', None):
        media_flags.append('طµظˆطھ')
    media_label = ' + '.join(media_flags) if media_flags else 'ط¨ط¯ظˆظ† ظ…ط±ظپظ‚ط§طھ'

    telegram_message = (
        "ًںڑ¨ <b>ط¨ظ„ط§ط؛ ط¬ط¯ظٹط¯ ط¹ظ„ظ‰ ظ…ظ†ط´ظˆط± ط§ظ„ظ…ط¬طھظ…ط¹</b>\n"
        f"â€¢ <b>ط±ظ‚ظ… ط§ظ„ط¨ظ„ط§ط؛:</b> {report.id}\n"
        f"â€¢ <b>ط±ظ‚ظ… ط§ظ„ظ…ظ†ط´ظˆط±:</b> {post.id}\n"
        f"â€¢ <b>ط§ظ„ظ…ط¨ظ„ظ‘ط؛:</b> {escape(current_user.company_name)} (@{escape(current_user.username)})\n"
        f"â€¢ <b>طµط§ط­ط¨ ط§ظ„ظ…ظ†ط´ظˆط±:</b> {escape(owner.company_name if owner else 'ط؛ظٹط± ظ…ط¹ط±ظˆظپ')}\n"
        f"â€¢ <b>ظ†ظˆط¹ ط§ظ„ظ…ظ†ط´ظˆط±:</b> {'ظ…ط¬ظ‡ظˆظ„' if getattr(post, 'is_anonymous', False) else 'ط¹ط§ط¯ظٹ'}\n"
        f"â€¢ <b>ط§ظ„ظ…ط­طھظˆظ‰:</b> {escape(preview)}\n"
        f"â€¢ <b>ط§ظ„ظ…ط±ظپظ‚ط§طھ:</b> {escape(media_label)}\n"
        f"â€¢ <b>ط§ظ„ط³ط¨ط¨:</b> {escape(reason or 'ظ„ظ… ظٹظƒطھط¨ ط§ظ„ظ…ط³طھط®ط¯ظ… ط³ط¨ط¨ط§ظ‹') }"
    )
    _send_telegram_text_message(telegram_message)

    return jsonify({'success': True, 'message': 'طھظ… ط¥ط±ط³ط§ظ„ ط§ظ„ط¨ظ„ط§ط؛ ظˆط³ظٹطھظ… ظ…ط±ط§ط¬ط¹طھظ‡.'})
@api_mobile_bp.route('/community/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = PostComment.query.get_or_404(comment_id)
    if comment.company_id != current_user.id:
        return jsonify({'success': False, 'message': 'ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ­ ط·آ¸أ¢â‚¬â€چط·آ¸ط¦â€™ ط·آ·ط¢آ¨ط·آ·ط¢آ­ط·آ·ط¢آ°ط·آ¸ط¸آ¾ ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘.'}), 403
    
    comment.is_active = False # Soft delete
    db.session.commit()
    return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ­ط·آ·ط¢آ°ط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘.'})

def _parse_bool_param(val, default=False):
    """ط·آ·ط¹آ¾ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¨ ط·آ·ط¢آ§ط·آ·ط¢آ¹ط·آ·ط¹آ¾ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ·ط¢آ± ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ³ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ³ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ© 'false' ط·آ¸أ¢â‚¬ع‘ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ© ط·آ·ط¢آ­ط·آ¸أ¢â‚¬ع‘ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ط·آ¸ط¸آ¹ط·آ·ط¢آ© ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ¸ط¸آ¹ط·آ·ط¢آ«ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ ."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ('false', '0', 'no', '', 'off'):
            return False
        if s in ('true', '1', 'yes', 'on'):
            return True
    return bool(val)


@api_mobile_bp.route('/community/posts/<int:post_id>/comments/create', methods=['POST'])
@login_required
def create_comment(post_id):
    data = request.get_json() or {}
    content = data.get('content', '').strip()
    if not content:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ£ط·آ¸أ¢â‚¬آ  ط·آ¸ط¸آ¹ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ  ط·آ¸ط¸آ¾ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ·ط·â€؛ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹.'}), 400
        
    # Check if user is blocked from messaging/posting
    if getattr(current_user, 'messaging_blocked', False):
        return jsonify({'success': False, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¥ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ¸ط¸آ¾ ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ¸ط¦â€™ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ·ط¢آ± ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¬ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ®ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ·ط¢آ©. ط·آ¸ط¸آ¹ط·آ·ط¢آ±ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آµط·آ¸أ¢â‚¬â€چ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¥ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ·ط¢آ©.'}), 403
        
    post = CommunityPost.query.get_or_404(post_id)
    is_anon = _parse_bool_param(data.get('is_anonymous'), False)
    parent_id = data.get('parent_id')
    try:
        parent_id = int(parent_id) if parent_id not in (None, '', False) else None
    except (TypeError, ValueError):
        parent_id = None

    parent_comment = None
    if parent_id is not None:
        parent_comment = PostComment.query.filter_by(id=parent_id, post_id=post_id, is_active=True).first()
        if not parent_comment:
            return jsonify({'success': False, 'message': 'التعليق الذي تحاول الرد عليه غير متاح الآن.'}), 404

    comment = PostComment(
        post_id=post_id,
        company_id=current_user.id,
        content=content,
        parent_id=parent_comment.id if parent_comment else None,
        is_anonymous=is_anon,
        created_at=datetime.utcnow()
    )
    db.session.add(comment)
    
    commenter_name = ANONYMOUS_DISPLAY_NAME if is_anon else current_user.company_name

    if parent_comment and parent_comment.company_id != current_user.id:
        target_company_id = parent_comment.company_id
        notif_type = 'reply'
    elif post.company_id != current_user.id:
        target_company_id = post.company_id
        notif_type = 'comment'
    else:
        target_company_id = None
        notif_type = 'comment'

    if target_company_id:
        if parent_comment:
            notif_msg = (
                'تم الرد على تعليقك بواسطة مستخدم مجهول.'
                if is_anon
                else f'رد {commenter_name} على تعليقك.'
            )
        else:
            notif_msg = (
                'قام مستخدم مجهول بالتعليق على منشورك.'
                if is_anon
                else f'علّق {commenter_name} على منشورك.'
            )
        notif = CommunityNotification(
            company_id=target_company_id,
            post_id=post.id,
            comment_id=comment.id,
            from_company_id=current_user.id,
            message=notif_msg,
            notification_type=notif_type
        )
        db.session.add(notif)
        
    db.session.commit()
    
    if target_company_id:
        preview = _notification_preview(content, 80)
        if parent_comment:
            push_title = 'رد جديد على تعليقك'
            push_body = (
                f'رد {current_user.company_name}: {preview}'
                if not is_anon
                else f'قام مستخدم مجهول بالرد: {preview}'
            )
        else:
            push_title = 'تعليق جديد على منشورك'
            push_body = (
                f'علّق {current_user.company_name}: {preview}'
                if not is_anon
                else f'قام مستخدم مجهول بالتعليق: {preview}'
            )
        send_push_notification(
            target_company_id,
            push_title,
            push_body,
            {"type": "reply" if parent_comment else "comment", "post_id": post_id, "comment_id": comment.id}
        )

    return jsonify({
        'success': True,
        'message': 'تمت إضافة التعليق بنجاح.',
        'comment': _normalize_anonymous_entity({
            'id': comment.id,
            'company_id': comment.company_id,
            'company_name': current_user.company_name if not is_anon else 'مستخدم مجهول',
            'avatar': current_user.avatar if not is_anon else 'default-male',
            'content': comment.content,
            'created_at': comment.created_at.isoformat(),
            'is_mine': True,
            'is_anonymous': is_anon,
            'parent_id': comment.parent_id,
            'parent_company_name': (
                'مستخدم مجهول'
                if parent_comment and getattr(parent_comment, 'is_anonymous', False)
                else (parent_comment.company.company_name if parent_comment and getattr(parent_comment, 'company', None) else None)
            ),
            'parent_preview': parent_comment.content[:120] if parent_comment and parent_comment.content else None,
        })
    })

# --- Private Messaging Endpoints ---

@api_mobile_bp.route('/messages/conversations', methods=['GET'])
@login_required
def get_conversations():
    # Similar to app.py get_conversations but for API
    messages = db.session.query(PrivateMessage).filter(
        or_(
            and_(PrivateMessage.sender_id == current_user.id, PrivateMessage.is_deleted_by_sender == False),
            and_(PrivateMessage.receiver_id == current_user.id, PrivateMessage.is_deleted_by_receiver == False)
        )
    ).order_by(PrivateMessage.sent_at.desc()).all()
    
    convos = {}
    for m in messages:
        other_id = m.receiver_id if m.sender_id == current_user.id else m.sender_id
        is_anon = (m.subject or '').startswith('[ANON]')
        
        # Use a composite key to separate normal and anonymous threads
        convo_key = f"{other_id}_{'anon' if is_anon else 'normal'}"
        
        if convo_key not in convos:
            other = Company.query.get(other_id)
            if other:
                unread = PrivateMessage.query.filter_by(
                    sender_id=other_id, 
                    receiver_id=current_user.id, 
                    is_read=False
                ).filter(PrivateMessage.subject.like('[ANON]%' if is_anon else 'رسالة مجهولة%')).count()
                
                is_official = other.company_name.upper() == 'STOCK FLOW' or other.username.upper() == 'STOCK FLOW'
                
                # Mask identity for anonymous threads
                display_name = other.company_name if not is_anon else "مستخدم مجهول"
                display_avatar = other.avatar if not is_anon else "default-male"
                
                convos[convo_key] = {
                    'other_company_id': other_id,
                    'my_company_id': current_user.id,
                    'company_name': display_name,
                    'avatar': display_avatar,
                    'last_message': m.message[:50],
                    'last_message_time': m.sent_at.isoformat() if m.sent_at else None,
                    'unread_count': unread,
                    'is_premium': other.is_premium if not is_anon else False,
                    'is_official': is_official if not is_anon else False,
                    'is_anonymous': is_anon
                }
    
    conversations_payload = [_normalize_anonymous_entity(item) for item in convos.values()]
    return jsonify({
        'success': True,
        'conversations': conversations_payload
    })

@api_mobile_bp.route('/messages/conversation/<int:other_id>', methods=['GET'])
@login_required
def get_conversation(other_id):
    is_anon_param = request.args.get('is_anonymous', 'false').lower() == 'true'
    other = Company.query.get_or_404(other_id) # Fetch other company details
    block_state = _get_message_block_state(current_user.id, other_id)
    
    query = db.session.query(PrivateMessage).filter(
        or_(
            and_(PrivateMessage.sender_id == current_user.id, PrivateMessage.receiver_id == other_id),
            and_(
                PrivateMessage.sender_id == other_id,
                PrivateMessage.receiver_id == current_user.id,
                not_(PrivateMessage.subject.like(f'{PHONE_BLOCKED_SUBJECT_PREFIX}%'))
            )
        )
    )
    
    # Filter by anonymous status
    if is_anon_param:
        query = query.filter(PrivateMessage.subject.contains('[ANON]'))
    else:
        query = query.filter(not_(PrivateMessage.subject.contains('[ANON]')))
        
    messages = query.order_by(PrivateMessage.sent_at.asc()).all()
    
    # Mark as read for this specific thread
    read_filter = PrivateMessage.query.filter_by(sender_id=other_id, receiver_id=current_user.id, is_read=False)
    read_filter = read_filter.filter(not_(PrivateMessage.subject.like(f'{PHONE_BLOCKED_SUBJECT_PREFIX}%')))
    if is_anon_param:
        read_filter = read_filter.filter(PrivateMessage.subject.contains('[ANON]'))
    else:
        read_filter = read_filter.filter(not_(PrivateMessage.subject.contains('[ANON]')))
        
    read_filter.update({'is_read': True, 'read_at': datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    
    data = []
    for m in messages:
        is_anon = (m.subject or '').startswith('[ANON]')
        data.append({
            'id': m.id,
            'sender_id': m.sender_id,
            'receiver_id': m.receiver_id,
            'is_me': m.sender_id == current_user.id,
            'message': m.message,
            'sent_at': m.sent_at.isoformat() if m.sent_at else None,
            'is_read': m.is_read,
            'is_anonymous': is_anon
        })
        
    # Mask company identity if conversation is anonymous
    display_name = other.company_name if not is_anon_param else "مستخدم مجهول"
    display_avatar = other.avatar if not is_anon_param else "default-male"
    
    other_company_payload = _normalize_anonymous_entity({
        'id': other.id,
        'company_name': display_name,
        'avatar': display_avatar,
        'is_premium': other.is_premium if not is_anon_param else False,
        'is_official': (other.company_name.upper() == 'STOCK FLOW' or other.username.upper() == 'STOCK FLOW') if not is_anon_param else False,
        'is_anonymous': is_anon_param,
    })
    return jsonify({
        'messages': data,
        'other_company': other_company_payload,
        **block_state
    })

@api_mobile_bp.route('/messages/send', methods=['POST'])
@login_required
def send_private_message():
    data = request.get_json()
    receiver_id = data.get('receiver_id')
    content = data.get('message', '').strip()
    is_anonymous = data.get('is_anonymous', False)
    
    if not receiver_id or not content:
        return jsonify({'success': False, 'message': 'بيانات غير مكتملة.'}), 400
        
    is_silently_filtered_phone_message = _contains_blocked_phone_number(content)

    receiver = Company.query.get(receiver_id)
    if not receiver:
        return jsonify({'success': False, 'message': 'المستخدم غير موجود.'}), 404
        
    # Rule: Check if sender is blocked from messaging
    if getattr(current_user, 'messaging_blocked', False):
        reason = getattr(current_user, 'messaging_block_reason', '') or 'تم حظرك من استخدام المراسلات من قبل الإدارة.'
        return jsonify({'success': False, 'message': f'محظور: {reason}'}), 403
        
    # Rule: Check if receiver has messaging enabled
    if not getattr(receiver, 'receive_messages_enabled', True):
        return jsonify({'success': False, 'message': 'عذراً ، الشركة قامت بتعطيل الرسائل حالياً.'}), 403
        
    block_error = _get_message_block_error(current_user.id, receiver_id)
    if block_error:
        return jsonify({'success': False, 'message': block_error}), 403

    # Rule: Check if receiver is official account (Stock Flow)
    if receiver.company_name.upper() == 'STOCK FLOW' or receiver.username.upper() == 'STOCK FLOW':
        return jsonify({'success': False, 'message': 'عذراً لا يمكن الرد على حساب STOCK FLOW الرسمي.'}), 403
        
    subject_value = "[ANON] رسالة مجهولة" if is_anonymous else "رسالة من الموبايل"
    if is_silently_filtered_phone_message:
        subject_value = f"{PHONE_BLOCKED_SUBJECT_PREFIX}{subject_value}"

    msg = PrivateMessage(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        subject=subject_value,
        message=content,
        sent_at=datetime.utcnow()
    )
    db.session.add(msg)
    db.session.commit()
    
    # NEW: إرسال إشعار للمستلم
    if not is_silently_filtered_phone_message:
        sender_display = ANONYMOUS_DISPLAY_NAME if is_anonymous else current_user.company_name
        send_push_notification(
            receiver_id, 
            f"رسالة جديدة من {sender_display}",
            _notification_preview(content, 50),
            {"type": "message", "sender_id": current_user.id}
        )
    
    return jsonify({'success': True, 'message': 'تم إرسال الرسالة.'})

@api_mobile_bp.route('/messages/block/<int:other_id>', methods=['POST'])
@login_required
def toggle_message_block(other_id):
    if other_id == current_user.id:
        return jsonify({'success': False, 'message': 'ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ ط·آ¸ط¦â€™ ط·آ·ط¢آ­ط·آ·ط¢آ¸ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¾ط·آ·ط¢آ³ط·آ¸ط¦â€™.'}), 400

    other = Company.query.get_or_404(other_id)
    existing_block = MessageBlock.query.filter_by(blocker_id=current_user.id, blocked_id=other_id).first()

    if existing_block:
        db.session.delete(existing_block)
        db.session.commit()
        return jsonify({
            'success': True,
            'action': 'unblocked',
            'message': f'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¥ط·آ¸أ¢â‚¬â€چط·آ·ط·â€؛ط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ·ط¢آ­ط·آ·ط¢آ¸ط·آ·ط¢آ± ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬â€چ {other.company_name}.',
            **_get_message_block_state(current_user.id, other_id)
        })

    new_block = MessageBlock(blocker_id=current_user.id, blocked_id=other_id)
    db.session.add(new_block)
    db.session.commit()
    return jsonify({
        'success': True,
        'action': 'blocked',
        'message': f'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ­ط·آ·ط¢آ¸ط·آ·ط¢آ± ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬â€چ {other.company_name}. ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ  ط·آ¸ط¸آ¹ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ  ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸ط¦â€™ ط·آ·ط¢آ¨ط·آ·ط¢آ¹ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¢ط·آ¸أ¢â‚¬آ .',
        **_get_message_block_state(current_user.id, other_id)
    })

@api_mobile_bp.route('/messages/<int:message_id>/delete', methods=['POST'])
@login_required
def delete_message(message_id):
    msg = PrivateMessage.query.get_or_404(message_id)
    
    # Check if user is sender or receiver
    if msg.sender_id != current_user.id and msg.receiver_id != current_user.id:
        return jsonify({'success': False, 'message': 'غير مصرح لك بحذف هذه الرسالة.'}), 403
        
    data = request.get_json() or {}
    delete_for_everyone = data.get('delete_for_everyone', False)
    
    if delete_for_everyone:
        # Only sender can delete for everyone
        if msg.sender_id == current_user.id:
            from models import PrivateMessageEditLog
            PrivateMessageEditLog.query.filter_by(message_id=msg.id).delete()
            db.session.delete(msg)
        else:
            return jsonify({'success': False, 'message': 'المرسل فقط يمكنه حذف الرسالة من الجانبين.'}), 403
    else:
        # Delete for current user only (logical delete)
        if msg.sender_id == current_user.id:
            msg.is_deleted_by_sender = True
        else:
            msg.is_deleted_by_receiver = True
            
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم حذف الرسالة.'})

@api_mobile_bp.route('/messages/conversations/<int:other_id>', methods=['DELETE'])
@login_required
def delete_conversation(other_id):
    delete_for_everyone = request.args.get('delete_for_everyone', 'false').lower() == 'true'
    
    messages = PrivateMessage.query.filter(
        or_(
            and_(PrivateMessage.sender_id == current_user.id, PrivateMessage.receiver_id == other_id),
            and_(PrivateMessage.sender_id == other_id, PrivateMessage.receiver_id == current_user.id)
        )
    ).all()
    
    deleted_count = 0
    for m in messages:
        try:
            if delete_for_everyone:
                # ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¸ط·آ¸ط¸آ¹ط·آ¸ط¸آ¾ ط·آ·ط¢آ³ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ£ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¨ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ´ط·آ·ط¢آ§ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬â€چ Foreign Key
                try:
                    from models import PrivateMessageEditLog
                    PrivateMessageEditLog.query.filter_by(message_id=m.id).delete()
                except Exception:
                    pass  # ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¬ط·آ·ط¢آ¯ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¯ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸ط¦â€™ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ  ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ¬ط·آ¸ط«â€ ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹
                
                db.session.delete(m)
                deleted_count += 1
            else:
                if m.sender_id == current_user.id:
                    m.is_deleted_by_sender = True
                else:
                    m.is_deleted_by_receiver = True
                deleted_count += 1
        except Exception as e:
            print(f"[delete_conversation] Error processing message {m.id}: {e}")
            db.session.rollback()
            continue
            
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[delete_conversation] Commit error: {e}")
        return jsonify({'success': False, 'message': f'ط·آ·ط¢آ®ط·آ·ط¢آ·ط·آ·ط¢آ£ ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾: {str(e)}'}), 500
        
    return jsonify({'success': True, 'message': f'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ­ط·آ·ط¢آ°ط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ­ط·آ·ط¢آ§ط·آ·ط¢آ¯ط·آ·ط¢آ«ط·آ·ط¢آ©. ({deleted_count} ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬â€چ)'})

@api_mobile_bp.route('/messages/available-companies', methods=['GET'])
@login_required
def get_available_companies():
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Get all active companies except the current user that have messaging enabled
    companies = Company.query.filter(
        Company.id != current_user.id, 
        Company.is_active == True,
        Company.receive_messages_enabled == True
    ).all()
    
    companies_data = []
    for company in companies:
        companies_data.append({
            'id': company.id,
            'company_name': company.company_name,
            'avatar': company.avatar or '',
        })
        
    return jsonify(companies_data)

# --- Notification Endpoints ---

@api_mobile_bp.route('/notifications', methods=['GET'])
@api_mobile_bp.route('/company/notifications', methods=['GET'])
@login_required
def get_notifications():
    # 1. System notifications (from admin)
    notifs = Notification.query.filter(
        or_(Notification.target_type == 'all', and_(Notification.target_type == 'specific', Notification.target_id == current_user.id)),
        Notification.is_active == True
    ).order_by(Notification.created_at.desc()).limit(50).all()
    
    data = []
    for n in notifs:
        try:
            is_read = NotificationRead.query.filter_by(notification_id=n.id, company_id=current_user.id).first() is not None
            created_at_val = n.created_at.isoformat() if n.created_at else datetime.utcnow().isoformat()
            
            data.append({
                'id': n.id,
                'title': _repair_mojibake_text(n.title or 'تنبيه عام'),
                'message': _repair_mojibake_text(n.message or ''),
                'created_at': created_at_val,
                'is_read': is_read,
                'type': 'system'
            })
        except Exception as e:
            print(f"Error processing notification {getattr(n, 'id', 'unknown')}: {e}")
            continue
    
    # 2. Community notifications (likes, comments, follows, poll votes)
    try:
        community_notifs = CommunityNotification.query.filter_by(
            company_id=current_user.id
        ).order_by(CommunityNotification.created_at.desc()).limit(50).all()
        
        for cn in community_notifs:
            notif_type = cn.notification_type or 'comment'
            title = _community_notification_title(notif_type)
            
            data.append({
                'id': f'community_{cn.id}',
                'title': title,
                'message': _repair_mojibake_text(cn.message or ''),
                'created_at': cn.created_at.isoformat() if cn.created_at else datetime.utcnow().isoformat(),
                'is_read': cn.is_read,
                'type': 'community',
                'post_id': cn.post_id,
                'notification_type': notif_type,
            })
    except Exception as e:
        print(f"Error fetching community notifications: {e}")
    
    # Sort all notifications by date (newest first)
    data.sort(key=lambda x: x['created_at'], reverse=True)
    
    return jsonify(data)

@api_mobile_bp.route('/notifications/read/<int:notification_id>', methods=['POST'])
@api_mobile_bp.route('/company/mark_notification_read/<int:notification_id>', methods=['POST'])
@login_required
def mark_read(notification_id):
    # Check if it's a community notification (passed as string like 'community_123')
    # The mobile app sends the ID as-is, so for community notifications we handle separately
    existing = NotificationRead.query.filter_by(notification_id=notification_id, company_id=current_user.id).first()
    if not existing:
        read = NotificationRead(notification_id=notification_id, company_id=current_user.id)
        db.session.add(read)
        db.session.commit()
    return jsonify({'success': True})

@api_mobile_bp.route('/community/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_community_notification_read(notification_id):
    cn = CommunityNotification.query.get(notification_id)
    if cn and cn.company_id == current_user.id:
        cn.is_read = True
        db.session.commit()
    return jsonify({'success': True})

# --- Statuses ---

@api_mobile_bp.route('/statuses', methods=['GET'])
@login_required
def get_statuses():
    now = datetime.utcnow()
    statuses = CompanyStatus.query.filter(
        CompanyStatus.is_active == True,
        CompanyStatus.start_at <= now,
        CompanyStatus.end_at > now
    ).order_by(CompanyStatus.start_at.desc()).all()
    
    data = []
    for s in statuses:
        viewed = CompanyStatusView.query.filter_by(status_id=s.id, viewer_company_id=current_user.id).first() is not None
        data.append({
            'id': s.id,
            'company_name': s.company.company_name,
            'text': s.text,
            'viewed_by_me': viewed,
            'is_mine': s.company_id == current_user.id
        })
    return jsonify(data)

@api_mobile_bp.route('/statuses/create', methods=['POST'])
@login_required
def create_status():
    data = request.get_json()
    text = data.get('text', '').strip()
    if not text or len(text) > 200:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ ط·آ·ط¢آµ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ¨ (ط·آ·ط¢آ¨ط·آ·ط¢آ­ط·آ·ط¢آ¯ ط·آ·ط¢آ£ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آµط·آ¸أ¢â‚¬آ° 200 ط·آ·ط¢آ­ط·آ·ط¢آ±ط·آ¸ط¸آ¾).'}), 400
        
    now = datetime.utcnow()
    # Deactivate old status
    CompanyStatus.query.filter_by(company_id=current_user.id, is_active=True).update({'is_active': False})
    
    new_status = CompanyStatus(
        company_id=current_user.id,
        text=text,
        start_at=now,
        end_at=now + timedelta(hours=24),
        is_active=True,
        created_at=now
    )
    db.session.add(new_status)
    db.session.commit()
    return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ·ط¢آ± ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ© ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ­.'})

# --- Surveys ---

@api_mobile_bp.route('/surveys', methods=['GET'])
@login_required
def get_surveys():
    surveys = Survey.query.filter_by(is_active=True).all()
    data = []
    for s in surveys:
        status = CompanySurveyStatus.query.filter_by(company_id=current_user.id, survey_id=s.id).first()
        is_completed = status.is_completed if status else False
        data.append({
            'id': s.id,
            'title': s.title,
            'description': s.description,
            'is_mandatory': s.is_mandatory,
            'is_completed': is_completed
        })
    return jsonify(data)

@api_mobile_bp.route('/surveys/<int:survey_id>/questions', methods=['GET'])
@login_required
def get_survey_questions(survey_id):
    survey = Survey.query.get_or_404(survey_id)
    questions = Question.query.filter_by(survey_id=survey_id).order_by(Question.order.asc()).all()
    data = []
    for q in questions:
        data.append({
            'id': q.id,
            'text': q.question_text,
            'type': q.question_type,
            'is_required': q.is_required,
            'options': json.loads(q.options) if q.options else None
        })
    return jsonify({'survey_title': survey.title, 'questions': data})

@api_mobile_bp.route('/surveys/<int:survey_id>/submit', methods=['POST'])
@login_required
def submit_survey(survey_id):
    data = request.get_json()
    answers = data.get('answers', []) # List of {question_id, answer_text, rating_value}
    
    response = SurveyResponse(survey_id=survey_id, company_id=current_user.id)
    db.session.add(response)
    
    for a in answers:
        ans = Answer(
            response=response,
            question_id=a.get('question_id'),
            answer_text=a.get('answer_text'),
            rating_value=a.get('rating_value')
        )
        db.session.add(ans)
    
    # Mark as completed
    status = CompanySurveyStatus.query.filter_by(company_id=current_user.id, survey_id=survey_id).first()
    if not status:
        status = CompanySurveyStatus(company_id=current_user.id, survey_id=survey_id)
        db.session.add(status)
    status.is_completed = True
    status.completed_at = datetime.utcnow()
    
    db.session.commit()
    return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¥ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¥ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ­.'})


# ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬
# Community Profile & Follow Endpoints
# ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬

@api_mobile_bp.route('/community/companies/<int:company_id>/profile', methods=['GET'])
@login_required
def get_company_community_profile(company_id):
    """Get public community profile for a company (posts + follow info)"""
    official = ensure_following_official_account(current_user)
    company = Company.query.get_or_404(company_id)

    # Follow counts
    followers_count = CompanyFollow.query.filter_by(followed_id=company_id).count()
    following_count = CompanyFollow.query.filter_by(follower_id=company_id).count()
    is_following = CompanyFollow.query.filter_by(
        follower_id=current_user.id,
        followed_id=company_id
    ).first() is not None
    if official and company.id == official.id:
        is_following = True

    # Posts (non-anonymous only, active)
    posts = CommunityPost.query.filter_by(
        company_id=company_id,
        is_active=True,
        is_anonymous=False
    ).order_by(CommunityPost.created_at.desc()).limit(50).all()

    # Bulk loading stats
    post_ids = [p.id for p in posts]
    likes_dict = {}
    comments_dict = {}
    views_dict = {}
    liked_by_me_set = set()

    if post_ids:
        try:
            likes_counts = db.session.query(PostLike.post_id, func.count(PostLike.id)).filter(PostLike.post_id.in_(post_ids)).group_by(PostLike.post_id).all()
            likes_dict = {pid: count for pid, count in likes_counts}
        except Exception:
            pass

        try:
            comments_counts = db.session.query(PostComment.post_id, func.count(PostComment.id)).filter(PostComment.post_id.in_(post_ids), PostComment.is_active == True).group_by(PostComment.post_id).all()
            comments_dict = {pid: count for pid, count in comments_counts}
        except Exception:
            pass

        try:
            views_counts = db.session.query(PostView.post_id, func.count(PostView.id)).filter(PostView.post_id.in_(post_ids)).group_by(PostView.post_id).all()
            views_dict = {pid: count for pid, count in views_counts}
        except Exception:
            pass

        try:
            my_likes = PostLike.query.filter(PostLike.post_id.in_(post_ids), PostLike.company_id == current_user.id).all()
            liked_by_me_set = {like.post_id for like in my_likes}
        except Exception:
            pass

    posts_data = []
    for p in posts:
        likes_count = likes_dict.get(p.id, 0)
        comments_count = comments_dict.get(p.id, 0)
        views_count = views_dict.get(p.id, 0)
        liked_by_me = p.id in liked_by_me_set

        # ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¢آ¬ ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ§ ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬
        import json as _json_cp
        _cp_fids = []
        _cp_types = []
        _cp_previews = []
        try:
            raw = getattr(p, 'media_file_ids', None)
            if raw:
                _cp_fids = _json_cp.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            pass
        try:
            raw = getattr(p, 'media_types', None)
            if raw:
                _cp_types = _json_cp.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            pass
        try:
            raw = getattr(p, 'media_preview_urls', None)
            if raw:
                _cp_previews = _json_cp.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            pass

        posts_data.append({
            'id': p.id,
            'content': p.content or '',
            'created_at': p.created_at.isoformat(),
            'likes_count': likes_count,
            'comments_count': comments_count,
            'views': views_count,
            'views_count': views_count,
            'liked_by_me': liked_by_me,
            'is_mine': p.company_id == current_user.id,
            'company_name': company.company_name,
            'avatar': company.avatar,
            'is_anonymous': False,
            'is_verified': getattr(company, 'is_premium', False),
            'is_premium': getattr(company, 'is_premium', False),
            'media_file_ids': _cp_fids,
            'media_types': _cp_types,
            'media_preview_urls': _cp_previews,
            'audio_file_id': getattr(p, 'audio_file_id', None),
            'audio_url': getattr(p, 'audio_url', None),
        })

    return jsonify({
        'success': True,
        'profile': {
            'id': company.id,
            'company_name': company.company_name,
            'avatar': company.avatar or 'ط¸â€¹ط¹ط›ط¹ث†ط¢آ¢',
            'is_premium': getattr(company, 'is_premium', False),
            'created_at': company.created_at.isoformat() if company.created_at else None,
            'followers_count': followers_count,
            'following_count': following_count,
            'is_following': is_following,
            'posts_count': len(posts_data),
            'is_me': company.id == current_user.id,
            'bio': getattr(company, 'bio', None),
            'cover_photo_url': getattr(company, 'cover_photo_url', None),
        },
        'posts': posts_data,
    })


@api_mobile_bp.route('/community/companies/<int:company_id>/follow', methods=['POST'])
@login_required
def toggle_follow_company(company_id):
    """Follow or unfollow a company"""
    if company_id == current_user.id:
        return jsonify({'success': False, 'message': 'ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ ط·آ¸ط¦â€™ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¢آ¹ط·آ·ط¢آ© ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ¸ط¦â€™ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ®ط·آ·ط¢آ§ط·آ·ط¢آµ!'}), 400

    company = Company.query.get_or_404(company_id)
    official = get_official_stockflow_account()
    if official and company.id == official.id:
        ensure_following_official_account(current_user)
        followers_count = CompanyFollow.query.filter_by(followed_id=company_id).count()
        return jsonify({
            'success': True,
            'is_following': True,
            'followers_count': followers_count,
            'message': 'ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ STOCK FLOW ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ ط·آ·ط¹آ¾ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¢آ¹ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬طŒ ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ¥ط·آ¸أ¢â‚¬â€چط·آ·ط·â€؛ط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¢آ¹ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬طŒ.'
        })

    existing = CompanyFollow.query.filter_by(
        follower_id=current_user.id,
        followed_id=company_id
    ).first()

    if existing:
        # Unfollow
        db.session.delete(existing)
        db.session.commit()
        followers_count = CompanyFollow.query.filter_by(followed_id=company_id).count()
        return jsonify({
            'success': True,
            'is_following': False,
            'followers_count': followers_count,
            'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¥ط·آ¸أ¢â‚¬â€چط·آ·ط·â€؛ط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¢آ¹ط·آ·ط¢آ©.'
        })
    else:
        # Follow
        follow = CompanyFollow(follower_id=current_user.id, followed_id=company_id)
        db.session.add(follow)
        
        # ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ ط·آ·ط¢آ¥ط·آ·ط¢آ´ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ± ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ®ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ (Notifications Screen) ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬
        notif = CommunityNotification(
            company_id=company_id,
            from_company_id=current_user.id,
            message=f"قام {current_user.company_name} بمتابعتك.",
            notification_type='new_follower'
        )
        db.session.add(notif)
        db.session.commit()

        # ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ ط·آ·ط¢آ¥ط·آ·ط¢آ´ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ± ط·آ¸ط¸آ¾ط·آ¸ط«â€ ط·آ·ط¢آ±ط·آ¸ط¸آ¹ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ·ط¢آ§ط·آ·ط¢آ­ط·آ·ط¢آ¨ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬
        try:
            send_push_notification(
                target_company_id=company_id,
                title='متابع جديد',
                body=f'قام {current_user.company_name} بمتابعتك الآن.',
                data={'type': 'new_follower', 'follower_id': current_user.id, 'follower_name': current_user.company_name}
            )
        except Exception:
            pass

        followers_count = CompanyFollow.query.filter_by(followed_id=company_id).count()
        return jsonify({
            'success': True,
            'is_following': True,
            'followers_count': followers_count,
            'message': 'تمت المتابعة بنجاح.'
        })


@api_mobile_bp.route('/community/polls/notify_vote', methods=['POST'])
@login_required
def notify_poll_vote():
    """
    ط·آ¸ط¸آ¹ط·آ¸ط¹ث†ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ¯ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬آ° ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ ط·آ·ط¢آ¨ط·آ·ط¢آ¹ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آµط·آ¸ط«â€ ط·آ¸ط¸آ¹ط·آ·ط¹آ¾ ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¥ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¥ط·آ·ط¢آ´ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ± ط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ·ط¢آ§ط·آ·ط¢آ­ط·آ·ط¢آ¨ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹.
    ط·آ¸ط¸آ¹ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¹آ¾ط·آ·ط¢آ³ط·آ·ط¢آ¬ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¥ط·آ·ط¢آ´ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ± ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¸ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ± ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ³ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¥ط·آ·ط¢آ´ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ط·آ·ط¥â€™ ط·آ¸ط«â€ ط·آ¸ط¸آ¹ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ¸أ¢â‚¬â€چ push notification.
    """
    data = request.get_json()
    if not data:
        return jsonify({'success': False}), 400

    creator_id = data.get('creator_id')      # ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ط·آ·ط¢آ±ط·آ¸ط¸آ¾ ط·آ·ط¢آµط·آ·ط¢آ§ط·آ·ط¢آ­ط·آ·ط¢آ¨ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹
    poll_question = data.get('question', 'استطلاع')  # ط·آ¸أ¢â‚¬آ ط·آ·ط¢آµ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ³ط·آ·ط¢آ¤ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ
    option_text = data.get('option_text', '')   # ط·آ¸أ¢â‚¬آ ط·آ·ط¢آµ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ®ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ·ط¢آ± ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ®ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ·ط¢آ±
    is_anonymous = data.get('is_anonymous', False)  # ط·آ¸أ¢â‚¬طŒط·آ¸أ¢â‚¬â€چ ط·آ¸ط¦â€™ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ·ط¢آ¦ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬طŒط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹

    # ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ¥ط·آ·ط¢آ´ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ± ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¾ط·آ·ط¢آ³ط·آ¸ط¦â€™ ط·آ·ط¢آ£ط·آ¸ط«â€  ط·آ·ط¢آ¥ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ° ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬طŒط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چ
    if not creator_id or creator_id == current_user.id or is_anonymous:
        return jsonify({'success': True, 'skipped': True})

    try:
        voter_name = current_user.company_name
        question_short = poll_question[:40] + ('...' if len(poll_question) > 40 else '')
        option_short = option_text[:25] + ('...' if len(option_text) > 25 else '') if option_text else ''

        body = f'صوّت {voter_name} على الخيار "{option_short}" في استطلاعك: {question_short}'

        # ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ ط·آ·ط¢آ¥ط·آ·ط¢آ´ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ± ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ®ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬
        notif = CommunityNotification(
            company_id=int(creator_id),
            from_company_id=current_user.id,
            message=body,
            notification_type='poll_vote'
        )
        db.session.add(notif)
        db.session.commit()

        send_push_notification(
            target_company_id=int(creator_id),
            title='تصويت جديد على استطلاعك',
            body=body,
            data={'type': 'poll_vote', 'voter_name': voter_name}
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬
# Poll CRUD Endpoints ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ­ط·آ¸ط¸آ¾ط·آ¸ط«â€ ط·آ·ط¢آ¸ط·آ·ط¢آ© ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾ (persistent)
# ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬ط£آ¢أ¢â‚¬â€Œأ¢â€ڑآ¬

from models import CommunityPoll, CommunityPollVote

@api_mobile_bp.route('/community/polls', methods=['GET'])
@login_required
def get_polls():
    """ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ·ط¢آ·ط·آ·ط¢آ© ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ±ط·آ·ط¹آ¾ط·آ·ط¢آ¨ط·آ·ط¢آ© ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ·ط¢آ­ط·آ·ط¢آ¯ط·آ·ط¢آ« ط·آ·ط¢آ¥ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬آ¦"""
    try:
        followed_company_ids = set()
        if current_user.is_authenticated:
            try:
                from models import CompanyFollow
                follows = CompanyFollow.query.filter_by(follower_id=current_user.id).all()
                followed_company_ids = {f.followed_id for f in follows}
            except Exception:
                pass

        polls = CommunityPoll.query.filter_by(is_active=True).order_by(
            CommunityPoll.created_at.desc()
        ).limit(50).all()

        result = []
        for poll in polls:
            options = json.loads(poll.options_json or '[]')
            votes = json.loads(poll.votes_json or '{}')

            # ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ³ votes ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘: company_id(str) -> option_index(int)
            votes_parsed = {}
            for k, v in votes.items():
                try:
                    votes_parsed[str(k)] = int(v)
                except (ValueError, TypeError):
                    pass

            # ط·آ·ط¹آ¾ط·آ·ط¢آ­ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬ع‘ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ­ط·آ¸ط¸آ¹ط·آ·ط¢آ©
            is_expired = False
            if poll.expires_at and poll.expires_at < datetime.utcnow():
                is_expired = True

            creator = poll.creator
            result.append({
                'id': poll.firestore_id or str(poll.id),
                'db_id': poll.id,
                'question': poll.question,
                'options': options,
                'votes': votes_parsed,
                'total_votes': len(votes_parsed),
                'created_at': poll.created_at.isoformat() + 'Z',
                'expires_at': poll.expires_at.isoformat() + 'Z' if poll.expires_at else None,
                'creator_id': poll.creator_id,
                'creator_name': creator.company_name if not poll.is_anonymous else 'ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬آ¦ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬طŒط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چ',
                'creator_avatar': creator.avatar if not poll.is_anonymous else 'default-male',
                'is_anonymous': poll.is_anonymous,
                'is_followed': poll.creator_id in followed_company_ids or poll.creator_id == current_user.id,
                'hide_results': poll.hide_results,
                'allow_change_vote': poll.allow_change_vote,
                'is_active': poll.is_active and not is_expired,
                '_type': 'poll',
            })

        polls_payload = [
            _normalize_anonymous_entity(item, name_keys=('creator_name',), avatar_keys=('creator_avatar',))
            for item in result
        ]
        return jsonify({'success': True, 'polls': polls_payload})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_mobile_bp.route('/community/polls/create', methods=['POST'])
@login_required
def create_poll():
    """ط·آ·ط¢آ¥ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹ ط·آ·ط¢آ¬ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ ط·آ¸ط«â€ ط·آ·ط¢آ­ط·آ¸ط¸آ¾ط·آ·ط¢آ¸ط·آ¸أ¢â‚¬طŒ ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾"""
    if getattr(current_user, 'messaging_blocked', False):
        return jsonify({'success': False, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¥ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ¸ط¸آ¾ ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ¸ط¦â€™ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ·ط¢آ± ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¬ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹.'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ¨ط·آ·ط¢آ©.'}), 400

    question = (data.get('question') or '').strip()
    options = data.get('options', [])
    duration_hours = int(data.get('duration_hours') or 0)
    is_anonymous = bool(data.get('is_anonymous', False))
    hide_results = bool(data.get('hide_results', False))
    allow_change_vote = bool(data.get('allow_change_vote', True))
    firestore_id = data.get('firestore_id')  # ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ط·آ·ط¢آ±ط·آ¸ط¸آ¾ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  Firestore ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ­ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ¸ط«â€ ط·آ·ط¢آ±ط·آ·ط¢آ¯

    if not question:
        return jsonify({'success': False, 'message': 'ط·آ¸أ¢â‚¬آ ط·آ·ط¢آµ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ³ط·آ·ط¢آ¤ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ¨.'}), 400
    if not options or len(options) < 2:
        return jsonify({'success': False, 'message': 'ط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ¨ ط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ·ط¢آ®ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬â€چ.'}), 400

    expires_at = None
    if duration_hours > 0:
        expires_at = datetime.utcnow() + timedelta(hours=duration_hours)

    try:
        poll = CommunityPoll(
            creator_id=current_user.id,
            question=question,
            options_json=json.dumps(options, ensure_ascii=False),
            votes_json='{}',
            is_anonymous=is_anonymous,
            hide_results=hide_results,
            allow_change_vote=allow_change_vote,
            is_active=True,
            expires_at=expires_at,
            created_at=datetime.utcnow(),
            firestore_id=firestore_id,
        )
        db.session.add(poll)
        db.session.commit()

        # ط·آ·ط¢آ¥ط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¸آ¹ط·آ¸ط¹ث†ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ¸أ¢â‚¬â€چ firestore_idط·آ·ط¥â€™ ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬آ¦ DB id ط·آ¸ط¦â€™ط·آ¸أ¢â€ڑآ¬ fallback
        if not poll.firestore_id:
            poll.firestore_id = f'poll_db_{poll.id}'
            db.session.commit()

        return jsonify({
            'success': True,
            'poll': {
                'id': poll.firestore_id,
                'db_id': poll.id,
                'question': poll.question,
                'options': options,
                'votes': {},
                'total_votes': 0,
                'created_at': poll.created_at.isoformat() + 'Z',
                'expires_at': poll.expires_at.isoformat() + 'Z' if poll.expires_at else None,
                'creator_id': poll.creator_id,
                'creator_name': current_user.company_name,
                'creator_avatar': current_user.avatar,
                'is_anonymous': poll.is_anonymous,
                'hide_results': poll.hide_results,
                'allow_change_vote': poll.allow_change_vote,
                'is_active': True,
                '_type': 'poll',
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@api_mobile_bp.route('/community/polls/sync_firestore_id', methods=['POST'])
@login_required
def sync_poll_firestore_id():
    """ط·آ·ط¢آ±ط·آ·ط¢آ¨ط·آ·ط¢آ· DB poll ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ط·آ·ط¢آ±ط·آ¸ط¸آ¾ Firestore ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ ط·آ¸ط¸آ¹ط·آ¸ط¹ث†ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ¯ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬آ° ط·آ·ط¢آ¨ط·آ·ط¢آ¹ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¦â€™ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¢آ© ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â€ڑآ¬ Firestore"""
    data = request.get_json() or {}
    db_id = data.get('db_id')
    firestore_id = data.get('firestore_id')

    if not db_id or not firestore_id:
        return jsonify({'success': False, 'message': 'db_id ط·آ¸ط«â€ firestore_id ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ .'}), 400

    poll = CommunityPoll.query.get(db_id)
    if not poll:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹ ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ¬ط·آ¸ط«â€ ط·آ·ط¢آ¯.'}), 404
    if poll.creator_id != current_user.id:
        return jsonify({'success': False, 'message': 'ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آµط·آ·ط¢آ±ط·آ·ط¢آ­.'}), 403

    try:
        poll.firestore_id = firestore_id
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@api_mobile_bp.route('/community/polls/<int:poll_db_id>/vote', methods=['POST'])
@login_required
def vote_poll(poll_db_id):
    """ط·آ·ط¹آ¾ط·آ·ط¢آ³ط·آ·ط¢آ¬ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¹آ¾ط·آ·ط¢آµط·آ¸ط«â€ ط·آ¸ط¸آ¹ط·آ·ط¹آ¾ ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾"""
    data = request.get_json() or {}
    option_index = data.get('option_index')

    if option_index is None:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ±ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ®ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ¨.'}), 400

    poll = CommunityPoll.query.get_or_404(poll_db_id)

    # ط·آ·ط¹آ¾ط·آ·ط¢آ­ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬ع‘ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹
    if poll.expires_at and poll.expires_at < datetime.utcnow():
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬طŒط·آ·ط¹آ¾ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¯ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹.'}), 400

    options = json.loads(poll.options_json or '[]')
    if option_index < 0 or option_index >= len(options):
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ®ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ·ط¢آ± ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ·ط¢آµط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­.'}), 400

    try:
        existing_vote = CommunityPollVote.query.filter_by(
            poll_id=poll.id, voter_id=current_user.id
        ).first()

        if existing_vote:
            if not poll.allow_change_vote:
                return jsonify({'success': False, 'message': 'ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¯ ط·آ·ط¢آµط·آ¸ط«â€ ط·آ¸أ¢â‚¬ع©ط·آ·ط¹آ¾ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹ ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ¸ط¸آ¹ط·آ·ط¢آ±.'}), 400
            existing_vote.option_index = option_index
            existing_vote.voted_at = datetime.utcnow()
            is_new_vote = False
        else:
            new_vote = CommunityPollVote(
                poll_id=poll.id,
                voter_id=current_user.id,
                option_index=option_index,
            )
            db.session.add(new_vote)
            is_new_vote = True

        # ط·آ·ط¹آ¾ط·آ·ط¢آ­ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ« votes_json ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ© ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾
        votes = json.loads(poll.votes_json or '{}')
        votes[str(current_user.id)] = option_index
        poll.votes_json = json.dumps(votes, ensure_ascii=False)
        db.session.commit()

        # ط·آ·ط¢آ¥ط·آ·ط¢آ´ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ± ط·آ·ط¢آµط·آ·ط¢آ§ط·آ·ط¢آ­ط·آ·ط¢آ¨ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹ ط·آ¸ط¸آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ· ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آµط·آ¸ط«â€ ط·آ¸ط¸آ¹ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¬ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ·ط¢آ¯
        if is_new_vote and poll.creator_id != current_user.id and not poll.is_anonymous:
            option_text = options[option_index] if option_index < len(options) else ''
            question_short = poll.question[:40] + ('...' if len(poll.question) > 40 else '')
            option_short = option_text[:25] + ('...' if len(option_text) > 25 else '')
            body = f'صوّت {current_user.company_name} على الخيار "{option_short}" في استطلاعك: {question_short}'

            notif = CommunityNotification(
                company_id=poll.creator_id,
                from_company_id=current_user.id,
                message=body,
                notification_type='poll_vote'
            )
            db.session.add(notif)
            db.session.commit()

            try:
                send_push_notification(
                    target_company_id=poll.creator_id,
                    title='تصويت جديد على استطلاعك',
                    body=body,
                    data={'type': 'poll_vote', 'voter_name': current_user.company_name}
                )
            except Exception:
                pass

        return jsonify({
            'success': True,
            'votes': {k: int(v) for k, v in votes.items()},
            'total_votes': len(votes),
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@api_mobile_bp.route('/community/polls/<int:poll_db_id>/delete', methods=['POST'])
@login_required
def delete_poll(poll_db_id):
    """ط·آ·ط¢آ­ط·آ·ط¢آ°ط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹ (soft delete) ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ´ط·آ·ط¢آ¦ ط·آ¸ط¸آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ·"""
    poll = CommunityPoll.query.get_or_404(poll_db_id)
    if poll.creator_id != current_user.id:
        return jsonify({'success': False, 'message': 'ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آµط·آ·ط¢آ±ط·آ·ط¢آ­ ط·آ¸أ¢â‚¬â€چط·آ¸ط¦â€™ ط·آ·ط¢آ¨ط·آ·ط¢آ­ط·آ·ط¢آ°ط·آ¸ط¸آ¾ ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹.'}), 403

    try:
        poll.is_active = False
        db.session.commit()
        return jsonify({'success': True, 'message': 'ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ­ط·آ·ط¢آ°ط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ¹.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯
# ط¸â€¹ط¹ط›أ¢â‚¬إ“ط¢آ¦ Telegram Media Storage ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ ط·آ·ط¢آ±ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ¸ط«â€ ط·آ·ط¢آ± ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ¸ط«â€ ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ¹ط·آ·ط¢آ¨ط·آ·ط¢آ± ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦
# ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯ط£آ¢أ¢â‚¬آ¢ط¹آ¯

# ط·آ·ط¢آ¥ط·آ·ط¢آ¹ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨ط·آ¸ط«â€ ط·آ·ط¹آ¾ ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¦â€™ط·آ¸أ¢â‚¬آ  ط·آ¸أ¢â‚¬آ ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬طŒط·آ·ط¢آ§ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ config.py ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ­ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¹
# SECURITY: Do NOT hardcode API tokens or chat IDs in source code.
# Load Telegram configuration from environment variables. If missing,
# set to empty and require operator to configure them securely.
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
TELEGRAM_STORAGE_CHAT_ID = os.environ.get('TELEGRAM_STORAGE_CHAT_ID', '').strip()
if TELEGRAM_BOT_TOKEN:
    TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
else:
    TELEGRAM_API_BASE = ''

# ط·آ·ط¢آ£ط·آ¸أ¢â‚¬آ ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ·ط¢آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ·ط¢آ· ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¨ط·آ¸ط«â€ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ© ط·آ¸ط«â€ ط·آ·ط¢آ­ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ§ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آµط·آ¸أ¢â‚¬آ°
ALLOWED_PHOTO_TYPES = {'image/jpeg', 'image/jpg', 'image/png', 'image/webp'}
ALLOWED_VIDEO_TYPES = {'video/mp4', 'video/mov', 'video/avi', 'video/quicktime'}
ALLOWED_AUDIO_TYPES = {'audio/ogg', 'audio/mpeg', 'audio/mp4', 'audio/aac', 'audio/wav', 'audio/m4a', 'audio/x-m4a'}
MAX_PHOTO_SIZE_MB = 10   # ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ­ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ° 10MB ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ¸ط«â€ ط·آ·ط¢آ±
MAX_VIDEO_SIZE_MB = 50   # ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ­ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ° 50MB ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ¸ط«â€ 
MAX_VOICE_SIZE_MB = 20   # ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آµط·آ¸ط«â€ ط·آ·ط¹آ¾ط·آ¸ط¸آ¹ط·آ·ط¢آ© ط·آ·ط¢آ­ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ° 20MB


def _upload_to_telegram(file_bytes: bytes, media_type: str, filename: str) -> dict:
    """
    ط·آ·ط¹آ¾ط·آ·ط¢آ±ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ ط·آ¸ط«â€ ط·آ·ط¹آ¾ط·آ·ط¢آ±ط·آ·ط¢آ¬ط·آ·ط¢آ¹ dict ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬طŒ:
      - file_id: ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¾ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ·ط¢آ­ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬آ¦ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾
      - file_unique_id: ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ط·آ·ط¢آ±ط·آ¸ط¸آ¾ ط·آ¸ط¸آ¾ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ¯
      - width / height (ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ¸ط«â€ ط·آ·ط¢آ± ط·آ¸ط¸آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ·)
      - duration (ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ¸ط«â€  ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آµط·آ¸ط«â€ ط·آ·ط¹آ¾)
    """
    if media_type == 'photo':
        url = f"{TELEGRAM_API_BASE}/sendPhoto"
        files = {'photo': (filename, file_bytes, 'image/jpeg')}
    elif media_type == 'video':
        url = f"{TELEGRAM_API_BASE}/sendVideo"
        files = {'video': (filename, file_bytes, 'video/mp4')}
    elif media_type == 'voice':
        # sendVoice ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¸آ¹ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬طŒ ط·آ¸ط¦â€™ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ© ط·آ·ط¢آµط·آ¸ط«â€ ط·آ·ط¹آ¾ط·آ¸ط¸آ¹ط·آ·ط¢آ© ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ ط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ¸ط¸آ¹ط·آ·ط¢آ· ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ´ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ
        url = f"{TELEGRAM_API_BASE}/sendVoice"
        files = {'voice': (filename, file_bytes, 'audio/ogg')}
    elif media_type == 'audio':
        # sendAudio ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ ط·آ·ط¢آµط·آ¸ط«â€ ط·آ·ط¹آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ (mp3, m4a...)
        url = f"{TELEGRAM_API_BASE}/sendAudio"
        files = {'audio': (filename, file_bytes, 'audio/mpeg')}
    else:
        raise ValueError(f"Unsupported media_type: {media_type}")

    data = {
        'chat_id': TELEGRAM_STORAGE_CHAT_ID,
        'disable_notification': True
    }

    response = requests.post(url, files=files, data=data, timeout=60)
    res = response.json()

    if not res.get('ok'):
        raise RuntimeError(f"Telegram API error: {res.get('description', 'Unknown error')}")

    result = res['result']

    if media_type == 'photo':
        photos = result.get('photo', [])
        if not photos:
            raise RuntimeError("No photo data in Telegram response")
        best = photos[-1]
        return {
            'file_id': best['file_id'],
            'file_unique_id': best['file_unique_id'],
            'width': best.get('width'),
            'height': best.get('height'),
        }
    elif media_type in ('voice', 'audio'):
        key = 'voice' if media_type == 'voice' else 'audio'
        audio_obj = result.get(key, {})
        return {
            'file_id': audio_obj['file_id'],
            'file_unique_id': audio_obj.get('file_unique_id'),
            'duration': audio_obj.get('duration'),
            'mime_type': audio_obj.get('mime_type'),
        }
    else:  # video
        video = result.get('video', {})
        return {
            'file_id': video['file_id'],
            'file_unique_id': video['file_unique_id'],
            'duration': video.get('duration'),
            'width': video.get('width'),
            'height': video.get('height'),
            'thumb_file_id': (video.get('thumbnail') or video.get('thumb') or {}).get('file_id'),
        }


def _get_telegram_file_url(file_id: str) -> str | None:
    """
    ط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ¸ط¸آ¹ط·آ·ط¢آ¨ ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¢آ· ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ­ط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ·ط¢آ´ط·آ·ط¢آ± ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¤ط·آ¸أ¢â‚¬ع‘ط·آ·ط¹آ¾ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦.
    ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ®ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ ط·آ¸ط¸آ¾ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ· ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¹ط·آ·ط¢آ±ط·آ·ط¢آ¶ ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬آ¦ proxy_url.
    """
    try:
        resp = requests.get(
            f"{TELEGRAM_API_BASE}/getFile",
            params={'file_id': file_id},
            timeout=10
        )
        data = resp.json()
        if data.get('ok'):
            file_path = data['result']['file_path']
            # Only build file URL if bot token is configured
            if TELEGRAM_BOT_TOKEN:
                return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
            else:
                current_app.logger.warning('TELEGRAM_BOT_TOKEN not configured; cannot build file URL')
                return None
    except Exception as e:
        print(f"[Telegram] getFile error: {e}")
    return None


def _build_proxy_url(file_id: str) -> str:
    """
    ط·آ¸ط¸آ¹ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â€ڑآ¬ URL ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬آ¦ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸أ¢â€ڑآ¬ proxy endpoint ط·آ·ط¢آ¨ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§.
    ط·آ¸أ¢â‚¬طŒط·آ·ط¢آ°ط·آ·ط¢آ§ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¢آ· ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬طŒط·آ¸ط¸آ¹ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¯ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬طŒ ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ£ط·آ¸أ¢â‚¬آ ط·آ¸أ¢â‚¬طŒ ط·آ¸ط¸آ¹ط·آ·ط¢آ¹ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¯ ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ° file_id ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ«ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¹آ¾.
    """
    base = 'https://www.stock-flow.site'
    return f"{base}/api/mobile/media/proxy/{file_id}"


@api_mobile_bp.route('/media/upload', methods=['POST'])
@login_required
def upload_media_to_telegram():
    """
    ط·آ·ط¢آ±ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ ط·آ·ط¢آµط·آ¸ط«â€ ط·آ·ط¢آ±ط·آ·ط¢آ© ط·آ·ط¢آ£ط·آ¸ط«â€  ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ط·آ·ط¢آ¯ط·آ¸ط¸آ¹ط·آ¸ط«â€  ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¦â€™ط·آ¸أ¢â€ڑآ¬ storage.
    
    ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ·ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¨: multipart/form-data
      - file: ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¢آ¯ ط·آ·ط¢آ±ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ط·آ¸أ¢â‚¬طŒ
      - media_type: 'photo' ط·آ·ط¢آ£ط·آ¸ط«â€  'video'
    
    ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¢آ©:
      - success: True
      - file_id: ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸ط¸آ¾ط·آ·ط¹آ¾ط·آ·ط¢آ§ط·آ·ط¢آ­ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬آ¦ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦
      - preview_url: ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¢آ· ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¤ط·آ¸أ¢â‚¬ع‘ط·آ·ط¹آ¾ ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ©
      - meta: ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ¥ط·آ·ط¢آ¶ط·آ·ط¢آ§ط·آ¸ط¸آ¾ط·آ¸ط¸آ¹ط·آ·ط¢آ© (ط·آ·ط¢آ£ط·آ·ط¢آ¨ط·آ·ط¢آ¹ط·آ·ط¢آ§ط·آ·ط¢آ¯ط·آ·ط¥â€™ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¯ط·آ·ط¢آ©...)
    """
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ ط·آ¸ط¸آ¹ط·آ·ط¹آ¾ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¥ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾.'}), 400

    file = request.files['file']
    media_type = request.form.get('media_type', 'photo').lower()
    media_type = {
        'image': 'photo',
        'photo': 'photo',
        'video': 'video',
        'voice': 'voice',
        'audio': 'audio',
    }.get(media_type, media_type)

    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ±ط·آ·ط¢آ³ط·آ¸أ¢â‚¬â€چ ط·آ¸ط¸آ¾ط·آ·ط¢آ§ط·آ·ط¢آ±ط·آ·ط·â€؛.'}), 400

    # ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ­ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬ع‘ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ¸أ¢â‚¬آ ط·آ¸ط«â€ ط·آ·ط¢آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ³ط·آ¸ط¸آ¹ط·آ·ط¢آ·
    if media_type not in ('photo', 'video', 'voice', 'audio'):
        return jsonify({'success': False, 'message': 'ط·آ¸أ¢â‚¬آ ط·آ¸ط«â€ ط·آ·ط¢آ¹ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸ط«â€ ط·آ·ط¢آ³ط·آ¸ط¸آ¹ط·آ·ط¢آ· ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¯ط·آ·ط¢آ¹ط·آ¸ط«â€ ط·آ¸أ¢â‚¬آ¦. ط·آ·ط¢آ§ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬آ¦ photo ط·آ·ط¢آ£ط·آ¸ط«â€  video ط·آ·ط¢آ£ط·آ¸ط«â€  voice.'}), 400

    # ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط·إ’ط·آ·ط¢آ© ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط¹آ¾ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾
    file_bytes = file.read()
    file_size_mb = len(file_bytes) / (1024 * 1024)

    # ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ­ط·آ¸أ¢â‚¬ع‘ط·آ¸أ¢â‚¬ع‘ ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬آ  ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ­ط·آ·ط¢آ³ط·آ·ط¢آ¨ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ ط·آ¸ط«â€ ط·آ·ط¢آ¹
    if media_type == 'photo':
        max_mb = MAX_PHOTO_SIZE_MB
    elif media_type == 'video':
        max_mb = MAX_VIDEO_SIZE_MB
    else:  # voice / audio
        max_mb = MAX_VOICE_SIZE_MB

    if file_size_mb > max_mb:
        return jsonify({
            'success': False,
            'message': f'ط·آ·ط¢آ­ط·آ·ط¢آ¬ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¾ ({file_size_mb:.1f} MB) ط·آ¸ط¸آ¹ط·آ·ط¹آ¾ط·آ·ط¢آ¬ط·آ·ط¢آ§ط·آ¸ط«â€ ط·آ·ط¢آ² ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ­ط·آ·ط¢آ¯ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ³ط·آ¸أ¢â‚¬آ¦ط·آ¸ط«â€ ط·آ·ط¢آ­ ({max_mb} MB).'
        }), 413

    try:
        # ط·آ·ط¢آ±ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦
        tg_result = _upload_to_telegram(file_bytes, media_type, file.filename)
        file_id = tg_result['file_id']

        # ط·آ·ط¢آ¨ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â€ڑآ¬ proxy_url ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬آ¦ ط·آ·ط¢آ¨ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â€ڑآ¬ URL ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¤ط·آ¸أ¢â‚¬ع‘ط·آ·ط¹آ¾
        proxy_url = _build_proxy_url(file_id)

        return jsonify({
            'success': True,
            'file_id': file_id,
            'file_unique_id': tg_result.get('file_unique_id'),
            'preview_url': proxy_url,   # ط·آ·ط¢آ¯ط·آ·ط¢آ§ط·آ·ط¢آ¦ط·آ¸أ¢â‚¬آ¦ ط£آ¢أ¢â€ڑآ¬أ¢â‚¬â€Œ ط·آ¸ط¸آ¹ط·آ·ط¢آ³ط·آ·ط¹آ¾ط·آ·ط¢آ®ط·آ·ط¢آ¯ط·آ¸أ¢â‚¬آ¦ط·آ¸أ¢â‚¬طŒ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ·ط¢آ·ط·آ·ط¢آ¨ط·آ¸ط¸آ¹ط·آ¸أ¢â‚¬ع‘ ط·آ¸أ¢â‚¬آ¦ط·آ·ط¢آ¨ط·آ·ط¢آ§ط·آ·ط¢آ´ط·آ·ط¢آ±ط·آ·ط¢آ©
            'proxy_url': proxy_url,     # ط·آ¸أ¢â‚¬آ ط·آ¸ط¸آ¾ط·آ·ط¢آ³ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ·ط¢آ¨ط·آ·ط¢آ· ط·آ¸أ¢â‚¬â€چط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ·ط¢آ§ط·آ¸ط¸آ¾ط·آ¸أ¢â‚¬ع‘
            'media_type': media_type,
            'meta': {
                'width': tg_result.get('width'),
                'height': tg_result.get('height'),
                'duration': tg_result.get('duration'),
                'thumb_file_id': tg_result.get('thumb_file_id'),
                'size_mb': round(file_size_mb, 2),
            }
        })

    except RuntimeError as e:
        print(f"[Telegram Upload] RuntimeError: {e}")
        return jsonify({'success': False, 'message': f'ط·آ¸ط¸آ¾ط·آ·ط¢آ´ط·آ¸أ¢â‚¬â€چ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ±ط·آ¸ط¸آ¾ط·آ·ط¢آ¹ ط·آ¸أ¢â‚¬â€چط·آ·ط¹آ¾ط·آ¸أ¢â‚¬â€چط·آ¸ط¸آ¹ط·آ·ط¢آ¬ط·آ·ط¢آ±ط·آ·ط¢آ§ط·آ¸أ¢â‚¬آ¦: {str(e)}'}), 502
    except Exception as e:
        print(f"[Telegram Upload] Unexpected error: {e}")
        return jsonify({'success': False, 'message': 'ط·آ·ط¢آ­ط·آ·ط¢آ¯ط·آ·ط¢آ« ط·آ·ط¢آ®ط·آ·ط¢آ·ط·آ·ط¢آ£ ط·آ·ط·â€؛ط·آ¸ط¸آ¹ط·آ·ط¢آ± ط·آ¸أ¢â‚¬آ¦ط·آ·ط¹آ¾ط·آ¸ط«â€ ط·آ¸أ¢â‚¬ع‘ط·آ·ط¢آ¹ ط·آ·ط¢آ£ط·آ·ط¢آ«ط·آ¸أ¢â‚¬آ ط·آ·ط¢آ§ط·آ·ط·إ’ ط·آ·ط¢آ§ط·آ¸أ¢â‚¬â€چط·آ·ط¢آ±ط·آ¸ط¸آ¾ط·آ·ط¢آ¹.'}), 500


@api_mobile_bp.route('/media/proxy/<path:file_id>', methods=['GET'])
@login_required
def proxy_telegram_media(file_id):
    """Stream Telegram-hosted media through the API for authenticated clients."""
    if not file_id:
        return jsonify({'success': False, 'message': 'file_id is required.'}), 400

    tg_url = _get_telegram_file_url(file_id)
    if not tg_url:
        return jsonify({'success': False, 'message': 'Unable to resolve media URL.'}), 404

    is_video = any(ext in tg_url.lower() for ext in ['.mp4', '.mov', '.avi', '.mkv'])
    is_audio = any(ext in tg_url.lower() for ext in ['.ogg', '.mp3', '.m4a', '.aac', '.wav', '.oga'])
    if is_video:
        content_type = 'video/mp4'
    elif is_audio:
        content_type = 'audio/ogg'
        if '.mp3' in tg_url.lower():
            content_type = 'audio/mpeg'
        elif '.m4a' in tg_url.lower():
            content_type = 'audio/mp4'
    else:
        content_type = 'image/jpeg'

    if '.png' in tg_url.lower():
        content_type = 'image/png'
    elif '.webp' in tg_url.lower():
        content_type = 'image/webp'

    try:
        tg_response = requests.get(tg_url, timeout=30, stream=True)
        if tg_response.status_code != 200:
            return jsonify({'success': False, 'message': 'Failed to fetch media from Telegram.'}), 502

        def generate():
            for chunk in tg_response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

        response = Response(
            generate(),
            status=200,
            content_type=content_type,
        )
        response.headers['Cache-Control'] = 'public, max-age=86400'
        response.headers['X-File-Id'] = file_id
        return response
    except requests.Timeout:
        return jsonify({'success': False, 'message': 'Telegram media request timed out.'}), 504
    except Exception as e:
        print(f'[Telegram Proxy] Error streaming file {file_id}: {e}')
        return jsonify({'success': False, 'message': 'Unexpected error while streaming media.'}), 500


@api_mobile_bp.route('/media/url/<path:file_id>', methods=['GET'])
@login_required
def get_media_url(file_id):
    """Redirect authenticated media requests to the proxy endpoint."""
    from flask import redirect
    return redirect(f'/api/mobile/media/proxy/{file_id}', code=302)


@api_mobile_bp.route('/media/batch-urls', methods=['POST'])
@login_required
def get_batch_media_urls():
    """Resolve a batch of Telegram file ids to direct URLs."""
    data = request.get_json()
    file_ids = data.get('file_ids', []) if data else []

    if not file_ids or not isinstance(file_ids, list):
        return jsonify({'success': False, 'message': 'file_ids list is required.'}), 400

    if len(file_ids) > 20:
        return jsonify({'success': False, 'message': 'Maximum batch size is 20 file ids.'}), 400

    results = {}
    for fid in file_ids:
        results[fid] = _get_telegram_file_url(str(fid))

    return jsonify({'success': True, 'urls': results})
