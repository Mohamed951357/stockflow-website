from functools import wraps
from flask import flash, redirect, url_for, session, current_app, request
from flask_login import current_user, logout_user # تم استيراد current_user هنا
import json
import os
import re
from datetime import datetime, date, timedelta
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError
from werkzeug.utils import secure_filename

# استيراد db فقط هنا. لا تستورد النماذج (مثل Company) في هذا المكان
from models import db 

# ALL_PERMISSIONS, ADMIN_ROLES, WEEK_DAYS لا تعتمد على db، يمكن أن تكون هنا
ALL_PERMISSIONS = {
    'manage_users': 'إدارة المستخدمين (الشركات)',
    'manage_admins': 'إدارة المديرين (صلاحيات، إضافة، تعديل، حذف)',
    'manage_appointments': 'إدارة المواعيد (قبول، رفض، تعديل)',
    'manage_files': 'إدارة ملفات الأصناف (رفع، تعطيل)',
    'send_notifications': 'إرسال إشعارات للشركات',
    'view_reports': 'عرض التقارير والإحصائيات',
    'manage_settings': 'إدارة إعدادات النظام (لوجو، نسخ احتياطي، مسح سجلات، صيانة، قيود الطلبات، إعلانات)',
    'manage_ad_images': 'إدارة الصور الإعلانات',
    'manage_community_chat': 'إدارة شات المجتمع (حذف/تثبيت رسائل، إلخ)',
    'manage_warehouses': 'إدارة المخازن (إضافة، تعديل، صلاحيات)',
    'view_appointments': 'عرض المواعيد',
    'upload_files': 'رفع ملفات الأصناف',
    'manage_products': 'إدارة الأصناف',
    'manage_invite_code': 'رؤية والتحكم في كود الدعوة'
}

ADMIN_ROLES = {
    'super': {
        'name': 'مدير عام',
        'permissions': ['all']
    },
    'manager': {
        'name': 'مدير',
        'permissions': ['manage_users', 'manage_appointments', 'manage_files', 'view_reports', 'send_notifications', 'manage_settings', 'manage_ad_images', 'manage_community_chat']
    },
    'warehouse_admin': {
        'name': 'أدمن مخزن',
        'permissions': ['manage_appointments', 'manage_files', 'view_reports', 'view_appointments', 'upload_files', 'manage_products']
    },
    'editor': {
        'name': 'محرر',
        'permissions': ['manage_appointments', 'manage_files', 'send_notifications']
    },
    'viewer': {
        'name': 'مشاهد',
        'permissions': ['view_reports']
    }
}

WEEK_DAYS = {
    0: 'الأحد',
    1: 'الاثنين',
    2: 'الثلاثاء',
    3: 'الأربعاء',
    4: 'الخميس',
    5: 'الجمعة',
    6: 'السبت'
}

def check_permission(permission):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('غير مصرح لك بالوصول، يرجى تسجيل الدخول.', 'error')
                return redirect(url_for('login'))

            if session.get('user_type') != 'admin' or not current_user.is_active:
                flash('غير مصرح لك بالوصول', 'error')
                logout_user() 
                session.pop('user_type', None)
                return redirect(url_for('login'))

            user_role_permissions = ADMIN_ROLES.get(current_user.role, {}).get('permissions', [])

            if permission in {'manage_warehouses', 'manage_admins'} and current_user.role != 'super':
                flash('هذه الصلاحية متاحة للمدير العام فقط', 'error')
                return redirect(url_for('admin_dashboard'))

            user_specific_permissions = []
            if current_user.permissions:
                try:
                    user_specific_permissions = json.loads(current_user.permissions)
                except json.JSONDecodeError:
                    user_specific_permissions = []

            final_permissions = list(set(user_role_permissions + user_specific_permissions))

            if 'all' in final_permissions:
                return f(*args, **kwargs)

            # التحقق من صلاحيات المخزن إذا كان أدمن مخزن
            if current_user.role == 'warehouse_admin' and current_user.warehouse_id:
                if not check_warehouse_permission(current_user.warehouse_id, permission):
                    flash('ليس لديك صلاحية للوصول لهذه الميزة في هذا المخزن', 'error')
                    return redirect(url_for('warehouse_admin_dashboard'))
                return f(*args, **kwargs)

            if current_user.role == 'warehouse_admin' and not current_user.warehouse_id:
                flash('حسابك غير مربوط بأي مخزن. تواصل مع المدير العام.', 'error')
                return redirect(url_for('admin_dashboard'))

            if permission not in final_permissions:
                flash('ليس لديك صلاحية للوصول لهذه الصفحة', 'error')
                return redirect(url_for('admin_dashboard'))

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def classify_client_context(user_agent='', is_standalone=False, source_hint=None, display_mode=None):
    ua = (user_agent or '').strip()
    ua_lower = ua.lower()
    source_hint = (source_hint or '').strip().lower()
    display_mode = (display_mode or '').strip().lower()
    standalone = bool(is_standalone) or display_mode == 'standalone'

    if source_hint == 'android_app' or '/api/mobile' in source_hint:
        return {
            'type': 'android_app',
            'os': 'Android',
            'browser': 'StockFlow Android App',
            'device': 'Android App',
            'display_mode': 'app',
            'is_standalone': True,
        }

    if 'iphone' in ua_lower or 'ipod' in ua_lower:
        browser = _detect_browser_name(ua_lower)
        return {
            'type': 'iphone_shortcut' if standalone else 'iphone_browser',
            'os': 'iOS',
            'browser': browser,
            'device': 'iPhone',
            'display_mode': 'standalone' if standalone else 'browser',
            'is_standalone': standalone,
        }

    if 'ipad' in ua_lower or ('macintosh' in ua_lower and 'mobile' in ua_lower):
        browser = _detect_browser_name(ua_lower)
        return {
            'type': 'ipad_shortcut' if standalone else 'ipad_browser',
            'os': 'iPadOS',
            'browser': browser,
            'device': 'iPad',
            'display_mode': 'standalone' if standalone else 'browser',
            'is_standalone': standalone,
        }

    if 'android' in ua_lower:
        browser = _detect_browser_name(ua_lower)
        return {
            'type': 'android_browser',
            'os': 'Android',
            'browser': browser,
            'device': 'Android',
            'display_mode': 'browser',
            'is_standalone': False,
        }

    if 'windows' in ua_lower:
        os_name = 'Windows'
    elif 'macintosh' in ua_lower or 'mac os x' in ua_lower:
        os_name = 'macOS'
    elif 'linux' in ua_lower:
        os_name = 'Linux'
    else:
        os_name = 'Unknown'

    browser = _detect_browser_name(ua_lower)
    client_type = 'desktop_web' if os_name != 'Unknown' else 'unknown'
    return {
        'type': client_type,
        'os': os_name,
        'browser': browser,
        'device': 'Desktop' if client_type == 'desktop_web' else 'Unknown',
        'display_mode': 'browser',
        'is_standalone': False,
    }


def update_company_client_context(company, user_agent=None, is_standalone=False, source_hint=None,
                                  display_mode=None, commit=True, force=False, throttle_seconds=600):
    if not company:
        return False

    ua = user_agent if user_agent is not None else request.headers.get('User-Agent', '')
    context = classify_client_context(
        user_agent=ua,
        is_standalone=is_standalone,
        source_hint=source_hint,
        display_mode=display_mode,
    )

    now = datetime.utcnow()
    last_seen = getattr(company, 'last_client_seen_at', None)
    same_context = (
        getattr(company, 'last_client_type', None) == context['type']
        and getattr(company, 'last_client_browser', None) == context['browser']
        and bool(getattr(company, 'last_client_is_standalone', False)) == bool(context['is_standalone'])
    )

    if not force and same_context and last_seen and (now - last_seen) < timedelta(seconds=throttle_seconds):
        return False

    company.last_client_type = context['type']
    company.last_client_os = context['os']
    company.last_client_browser = context['browser']
    company.last_client_device = context['device']
    company.last_client_display_mode = context['display_mode']
    company.last_client_is_standalone = context['is_standalone']
    company.last_client_user_agent = (ua or '')[:1000]
    company.last_client_seen_at = now

    if commit:
        db.session.commit()
    return True


def _detect_browser_name(ua_lower):
    if not ua_lower:
        return 'Unknown'
    if 'samsungbrowser' in ua_lower:
        return 'Samsung Internet'
    if 'edgios' in ua_lower or 'edga' in ua_lower or 'edg/' in ua_lower:
        return 'Microsoft Edge'
    if 'crios' in ua_lower or ('chrome/' in ua_lower and 'chromium' not in ua_lower and 'edg/' not in ua_lower):
        if '; wv' in ua_lower or ' wv)' in ua_lower:
            return 'Android WebView'
        return 'Chrome'
    if 'fxios' in ua_lower or 'firefox/' in ua_lower:
        return 'Firefox'
    if 'opr/' in ua_lower or 'opera' in ua_lower:
        return 'Opera'
    if 'safari/' in ua_lower:
        return 'Safari'
    if 'okhttp' in ua_lower:
        return 'Android App'
    return 'Unknown'

def check_warehouse_permission(warehouse_id, permission_key):
    """التحقق مما إذا كانت ميزة معينة مفعلة لمخزن معين"""
    from models import WarehousePermissions
    perm = WarehousePermissions.query.filter_by(
        warehouse_id=warehouse_id, 
        permission_key=permission_key
    ).first()
    return perm.is_enabled if perm else False

INVITE_CODE_KEY = 'invite_code'
INVITE_CODE_PREV_KEY = 'invite_code_prev'
INVITE_CODE_PREV_USES_KEY = 'invite_code_prev_uses_left'


def _upsert_system_setting(setting_key, value):
    from models import SystemSetting
    row = SystemSetting.query.filter_by(setting_key=setting_key).first()
    if row:
        row.setting_value = value
    else:
        db.session.add(SystemSetting(setting_key=setting_key, setting_value=value))


def resolve_invite_code_match(submitted_code):
    """
    يحدد ما إذا كان الكود المُدخل يطابق الكود الحالي أو الكود السابق (المرخص له استخدام واحد بعد التدوير).
    يعيد 'current' أو 'prev' أو None إن كان غير صالح.
    """
    from models import SystemSetting

    code = (submitted_code or '').strip()
    if not code:
        return None

    cur_row = SystemSetting.query.filter_by(setting_key=INVITE_CODE_KEY).first()
    current = (cur_row.setting_value if cur_row else '') or ''
    if not current:
        return None

    if code == current:
        return 'current'

    prev_row = SystemSetting.query.filter_by(setting_key=INVITE_CODE_PREV_KEY).first()
    uses_row = SystemSetting.query.filter_by(setting_key=INVITE_CODE_PREV_USES_KEY).first()
    prev = (prev_row.setting_value if prev_row else '') or ''
    uses_left = 0
    if uses_row and uses_row.setting_value and str(uses_row.setting_value).isdigit():
        uses_left = int(uses_row.setting_value)

    if code == prev and uses_left > 0:
        return 'prev'

    return None


def burn_and_regenerate_invite_code():
    """
    بعد استخدام الكود الحالي بنجاح: يستبدله بكود عشوائي جديد.
    لا يمس كود «الاستخدام الواحد» المحفوظ بعد تغيير الإدارة للكود (invite_code_prev).
    """
    from models import SystemSetting
    import random

    try:
        current_setting = SystemSetting.query.filter_by(setting_key=INVITE_CODE_KEY).first()
        new_code = str(random.randint(100000, 999999))

        if current_setting:
            current_setting.setting_value = new_code
        else:
            db.session.add(SystemSetting(setting_key=INVITE_CODE_KEY, setting_value=new_code))

        db.session.commit()
        return new_code
    except Exception as e:
        db.session.rollback()
        print(f"Error burning invite code: {e}")
        return None


def consume_one_time_prev_invite_code():
    """بعد استخدام الكود السابق (مرة واحدة) يُزال من الصلاحية."""
    try:
        _upsert_system_setting(INVITE_CODE_PREV_KEY, '')
        _upsert_system_setting(INVITE_CODE_PREV_USES_KEY, '0')
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error consuming prev invite code: {e}")


def apply_invite_code_consumed(match_kind):
    """يُستدعى بعد تفعيل ناجح: إما حرق الكود الحالي أو إنهاء صلاحية الكود السابق لمرة واحدة."""
    if match_kind == 'current':
        burn_and_regenerate_invite_code()
    elif match_kind == 'prev':
        consume_one_time_prev_invite_code()


def normalize_company_name(company_name):
    """توحيد اسم الشركة للمقارنة: إزالة المسافات الزائدة وتجاهل اختلاف حالة الحروف."""
    return ' '.join(str(company_name or '').split()).casefold()


def company_name_exists(company_name, exclude_company_id=None):
    """يرجع True إذا كان اسم الشركة مستخدماً بالفعل، مع تجاهل اختلاف المسافات وحالة الحروف."""
    from models import Company

    normalized_name = normalize_company_name(company_name)
    if not normalized_name:
        return False

    query = Company.query.with_entities(Company.id, Company.company_name)
    if exclude_company_id is not None:
        query = query.filter(Company.id != exclude_company_id)

    for _company_id, existing_name in query.all():
        if normalize_company_name(existing_name) == normalized_name:
            return True
    return False


def find_company_for_login(identifier, password, allow_phone=True):
    """البحث عن شركة بالاسم/الهاتف مع مطابقة كلمة المرور، لأن اسم المستخدم قد يتكرر."""
    from werkzeug.security import check_password_hash
    from models import Company

    identifier = (identifier or '').strip()
    if not identifier or not password:
        return None

    candidates = []
    seen_ids = set()

    def add_candidates(rows):
        for company in rows:
            if company.id not in seen_ids:
                candidates.append(company)
                seen_ids.add(company.id)

    if allow_phone:
        add_candidates(Company.query.filter_by(phone=identifier).all())
    add_candidates(Company.query.filter_by(username=identifier).all())

    password_matches = []
    for company in candidates:
        if check_password_hash(company.password, password):
            password_matches.append(company)
    for company in password_matches:
        if company.is_active:
            return company
    if password_matches:
        return password_matches[0]
    return None


def rotate_invite_code_admin():
    """
    تغيير الكود من الإدارة: الكود الحالي يصبح صالحاً لاستخدام واحد فقط تحت invite_code_prev،
    ويُعرض للمستخدمين الجدد كود جديد.
    """
    from models import SystemSetting
    import random

    try:
        current_setting = SystemSetting.query.filter_by(setting_key=INVITE_CODE_KEY).first()
        old_current = (current_setting.setting_value if current_setting else '') or ''
        new_code = str(random.randint(100000, 999999))

        if current_setting:
            current_setting.setting_value = new_code
        else:
            current_setting = SystemSetting(setting_key=INVITE_CODE_KEY, setting_value=new_code)
            db.session.add(current_setting)

        if old_current:
            _upsert_system_setting(INVITE_CODE_PREV_KEY, old_current)
            _upsert_system_setting(INVITE_CODE_PREV_USES_KEY, '1')
        else:
            _upsert_system_setting(INVITE_CODE_PREV_KEY, '')
            _upsert_system_setting(INVITE_CODE_PREV_USES_KEY, '0')

        db.session.commit()
        return new_code
    except Exception as e:
        db.session.rollback()
        print(f"Error rotating invite code (admin): {e}")
        return None

# دالة لـ user_loader - تستورد النماذج هنا
def _get_request_user_type_hint():
    """Helps restore old remember cookies that stored only a numeric id."""
    try:
        path = (request.path or '').lower()
        endpoint = (request.endpoint or '').lower()
    except RuntimeError:
        return None

    company_markers = (
        '/api/mobile', '/api/company', '/company', '/search', '/book_appointment',
        '/appointments', '/community', '/notifications', '/premium', '/subscribe',
        '/profile/company', '/messages', '/my_products', '/products',
    )
    admin_markers = (
        '/admin', '/manage', '/reports', '/upload', '/send_notification',
        '/system_settings', '/app_download_logs',
    )

    if path.startswith(company_markers) or endpoint.startswith(('company', 'api_mobile')):
        return 'company'
    if path.startswith(admin_markers) or endpoint.startswith(('admin', 'manage')):
        return 'admin'
    return None


def _load_active_user(model, raw_id):
    try:
        user = model.query.get(int(raw_id))
    except (TypeError, ValueError):
        return None
    return user if user and user.is_active else None


def _restore_loaded_user(user_type, user):
    session['user_type'] = user_type
    session.permanent = True
    return user


def load_user(user_id):
    # استيراد النماذج داخل الدالة لضمان أنها معرفة
    from models import Admin, Company 
    try:
        user_id_value = str(user_id or '')

        if ':' in user_id_value:
            user_type, raw_id = user_id_value.split(':', 1)
            if user_type == 'admin':
                admin = _load_active_user(Admin, raw_id)
                if admin:
                    return _restore_loaded_user('admin', admin)
            elif user_type == 'company':
                company = _load_active_user(Company, raw_id)
                if company:
                    return _restore_loaded_user('company', company)
            return None

        # دعم الكوكيز القديمة التي كانت تحفظ الرقم فقط. لو الطلب واضح أنه
        # لشاشة/ API شركات، نفضل جدول الشركات حتى لا يلتبس id الشركة مع id أدمن.
        request_hint = _get_request_user_type_hint()
        if request_hint == 'company':
            company = _load_active_user(Company, user_id_value)
            if company:
                return _restore_loaded_user('company', company)
        elif request_hint == 'admin':
            admin = _load_active_user(Admin, user_id_value)
            if admin:
                return _restore_loaded_user('admin', admin)

        user_type = session.get('user_type')

        # إذا كان نوع المستخدم موجود في الجلسة، استخدمه مباشرة
        if user_type == 'admin':
            admin = _load_active_user(Admin, user_id_value)
            if admin:
                return _restore_loaded_user('admin', admin)
        elif user_type == 'company':
            company = _load_active_user(Company, user_id_value)
            if company:
                return _restore_loaded_user('company', company)

        # إذا لم يكن نوع المستخدم موجود في الجلسة (حالة Remember Me قديمة)
        # نحافظ على ترتيب الأدمن القديم للروابط غير الواضحة، والكوكيز الجديدة
        # أصبحت تحمل prefix يمنع الالتباس من الأساس.
        admin = _load_active_user(Admin, user_id_value)
        if admin:
            return _restore_loaded_user('admin', admin)

        company = _load_active_user(Company, user_id_value)
        if company:
            return _restore_loaded_user('company', company)
        
        return None
    except Exception as e:
        print(f"Error loading user {user_id}: {e}")
        import traceback
        traceback.print_exc()
        return None

# دالة لـ context_processor - تستورد النماذج هنا
# تم تعديلها لتستقبل 'app' و 'db' وتوحيد مسار اللوجو
def inject_global_data(app, db): 
    # استيراد النموذج داخل الدالة لضمان أنها معرفة
    from models import SystemSetting, WarehousePermissions
    
    global_data = {}
    current_logo_path = None

    # يجب أن نكون ضمن App Context للوصول إلى قاعدة البيانات
    with app.app_context():
        logo_setting = SystemSetting.query.filter_by(setting_key='current_logo').first()
        if logo_setting and logo_setting.setting_value:
            # مسار موحد: دائماً 'static/logos/'
            current_logo_path = url_for('static', filename=f'logos/{logo_setting.setting_value}')
        else:
            # Fallback للوجو الافتراضي
            current_logo_path = url_for('static', filename='images/default_logo.png')

        # إضافة صلاحيات المستخدم الحالي للقوالب
        if current_user.is_authenticated and session.get('user_type') == 'admin':
            user_role_permissions = ADMIN_ROLES.get(current_user.role, {}).get('permissions', [])
            user_specific_permissions = []
            if current_user.permissions:
                try:
                    user_specific_permissions = json.loads(current_user.permissions)
                except:
                    user_specific_permissions = []
            
            final_permissions = list(set(user_role_permissions + user_specific_permissions))
            
            # إذا كان أدمن مخزن، ندمج صلاحيات المخزن أيضاً
            if current_user.role == 'warehouse_admin' and current_user.warehouse_id:
                warehouse_perms = WarehousePermissions.query.filter_by(warehouse_id=current_user.warehouse_id, is_enabled=True).all()
                warehouse_perm_keys = [p.permission_key for p in warehouse_perms]
                # أدمن المخزن لديه فقط ما هو مسموح به في مخزنه من ضمن صلاحيات دوره
                final_permissions = [p for p in final_permissions if p in warehouse_perm_keys or p == 'all']
                
                global_data['is_warehouse_admin'] = True
                global_data['current_warehouse'] = current_user.warehouse
            else:
                global_data['is_warehouse_admin'] = False
                global_data['current_warehouse'] = None
                
            global_data['current_user_permissions'] = final_permissions
        else:
            global_data['current_user_permissions'] = []
            global_data['is_warehouse_admin'] = False
            global_data['current_warehouse'] = None

    global_data['current_logo_path'] = current_logo_path
    return global_data

# دالة مساعدة لتحديد امتدادات اللوجو المسموح بها
def allowed_logo_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_LOGO_EXTENSIONS']

# دالة مساعدة لتحديد امتدادات الصور الإعلانية المسموح بها
def allowed_image_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'html', 'htm'}
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_IMAGE_EXTENSIONS']


def _quote_identifier(identifier):
    return '"' + str(identifier).replace('"', '""') + '"'


def _is_valid_identifier(name: str) -> bool:
    return bool(re.match(r'^[A-Za-z0-9_]+$', str(name)))


def _sanitize_identifier(name: str) -> str:
    if not _is_valid_identifier(name):
        raise ValueError(f"Invalid SQL identifier: {name}")
    return name


def _drop_company_username_uniques(db, inspector):
    """يفك أي unique قديم على company.username حتى يسمح بتشابه أسماء المستخدمين."""
    dialect = db.engine.dialect.name

    changed = False
    if dialect == 'postgresql':
        for constraint in inspector.get_unique_constraints('company'):
            if constraint.get('column_names') == ['username'] and constraint.get('name'):
                constraint_name = constraint['name']
                try:
                    print(f"Dropping old unique constraint on company.username: {constraint_name}")
                    db.session.execute(text(
                        f"ALTER TABLE {_quote_identifier('company')} "
                        f"DROP CONSTRAINT IF EXISTS {_quote_identifier(constraint_name)}"
                    ))
                    changed = True
                except Exception as e:
                    db.session.rollback()
                    print(f"Could not drop username unique constraint '{constraint_name}': {e}")

        fresh_inspector = inspect(db.engine)
        for index in fresh_inspector.get_indexes('company'):
            if index.get('unique') and index.get('column_names') == ['username'] and index.get('name'):
                index_name = index['name']
                try:
                    print(f"Dropping old unique index on company.username: {index_name}")
                    db.session.execute(text(f"DROP INDEX IF EXISTS {_quote_identifier(index_name)}"))
                    changed = True
                except Exception as e:
                    db.session.rollback()
                    print(f"Could not drop username unique index '{index_name}': {e}")
        if changed:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return

    if dialect == 'sqlite':
        for index in inspector.get_indexes('company'):
            if index.get('unique') and index.get('column_names') == ['username'] and index.get('name'):
                index_name = index['name']
                if index_name.startswith('sqlite_autoindex'):
                    print(f"Keeping SQLite autoindex '{index_name}' on company.username; table rebuild would be required.")
                    continue
                try:
                    print(f"Dropping old unique index on company.username: {index_name}")
                    db.session.execute(text(f"DROP INDEX IF EXISTS {_quote_identifier(index_name)}"))
                    changed = True
                except Exception as e:
                    db.session.rollback()
                    print(f"Could not drop username unique index '{index_name}': {e}")
        if changed:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return

    for index in inspector.get_indexes('company'):
        if index.get('unique') and index.get('column_names') == ['username'] and index.get('name'):
            index_name = index['name']
            try:
                print(f"Dropping old unique index on company.username: {index_name}")
                db.session.execute(text(f"ALTER TABLE {_quote_identifier('company')} DROP INDEX {_quote_identifier(index_name)}"))
                changed = True
            except Exception as e:
                db.session.rollback()
                print(f"Could not drop username unique index '{index_name}': {e}")
    if changed:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


# دالة تحديث قاعدة البيانات
def update_database_schema(app, db):
    # استيراد جميع النماذج هنا لضمان أنها معرفة عند بدء التحديث
    from models import (Admin, Company, ProductFile, Appointment, Notification, SearchLog, 
                        FavoriteProduct, SystemSetting, ProductItem, ProductStockHistory, AdImage,
                        AppDownloadLog, CommunityMessage, DbMaintenanceLog, Warehouse, WarehousePermissions)
    try: 
        inspector = inspect(db.engine)

        # Check and add avatar column to company table
        if inspector.has_table('company'):
            _drop_company_username_uniques(db, inspector)

            columns = [col['name'] for col in inspector.get_columns('company')]
            if 'avatar' not in columns:
                print("Adding avatar column to company table...")
                db.session.execute(text('ALTER TABLE "company" ADD COLUMN "avatar" VARCHAR(100) DEFAULT \'male-1\''))
                db.session.commit()
                print("Avatar column added successfully!")

            if 'receive_messages_enabled' not in columns:
                print("Adding receive_messages_enabled column to company table...")
                db.session.execute(text('ALTER TABLE "company" ADD COLUMN "receive_messages_enabled" BOOLEAN DEFAULT 1'))
                db.session.commit()
                print("receive_messages_enabled column added successfully!")

            if 'google_id' not in columns:
                print("Adding google_id column to company table...")
                # SQLite لا يدعم إضافة عمود UNIQUE مباشرة عبر ALTER TABLE
                # سنقوم بإضافة العمود أولاً ثم إنشاء INDEX فريد إذا لزم الأمر
                try:
                    safe_col = _sanitize_identifier('google_id')
                except Exception as e:
                    print(f"Skipping adding unsafe column name 'google_id': {e}")
                else:
                    db.session.execute(text(f'ALTER TABLE "company" ADD COLUMN {_quote_identifier(safe_col)} VARCHAR(100)'))
                    db.session.commit()
                    try:
                        db.session.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS idx_company_google_id ON company (google_id)'))
                        db.session.commit()
                    except Exception as index_e:
                        print(f"Note: Could not create unique index for google_id: {index_e}")
                    print("google_id column added successfully!")

            if 'expo_push_token' not in columns:
                print("Adding expo_push_token column to company table...")
                db.session.execute(text('ALTER TABLE "company" ADD COLUMN "expo_push_token" VARCHAR(255)'))
                db.session.commit()
                print("expo_push_token column added successfully!")

            if 'last_active' not in columns:
                print("Adding last_active column to company table...")
                db.session.execute(text('ALTER TABLE "company" ADD COLUMN "last_active" DATETIME'))
                db.session.commit()
                print("last_active column added successfully!")

            if 'is_typing' not in columns:
                print("Adding is_typing column to company table...")
                db.session.execute(text('ALTER TABLE "company" ADD COLUMN "is_typing" BOOLEAN DEFAULT 0'))
                db.session.commit()
                print("is_typing column added successfully!")

            if 'monthly_search_count' not in columns:
                print("Adding monthly_search_count column to company table...")
                db.session.execute(text('ALTER TABLE "company" ADD COLUMN "monthly_search_count" INTEGER DEFAULT 0'))
                db.session.commit()
                print("monthly_search_count column added successfully!")

            is_postgres = db.engine.dialect.name == 'postgresql'
            timestamp_type = 'TIMESTAMP' if is_postgres else 'DATETIME'
            boolean_false_type = 'BOOLEAN DEFAULT false' if is_postgres else 'BOOLEAN DEFAULT 0'
            client_columns = {
                'last_client_type': 'VARCHAR(50)',
                'last_client_os': 'VARCHAR(50)',
                'last_client_browser': 'VARCHAR(80)',
                'last_client_device': 'VARCHAR(80)',
                'last_client_display_mode': 'VARCHAR(50)',
                'last_client_is_standalone': boolean_false_type,
                'last_client_user_agent': 'TEXT',
                'last_client_seen_at': timestamp_type,
            }
            for col_name, col_type in client_columns.items():
                if col_name not in columns:
                    print(f"Adding {col_name} column to company table...")
                    try:
                        safe_col = _sanitize_identifier(col_name)
                    except Exception as e:
                        print(f"Skipping invalid column name {col_name}: {e}")
                        continue
                    if is_postgres:
                        db.session.execute(text(f"ALTER TABLE {_quote_identifier('company')} ADD COLUMN IF NOT EXISTS {_quote_identifier(safe_col)} {col_type}"))
                    else:
                        db.session.execute(text(f"ALTER TABLE {_quote_identifier('company')} ADD COLUMN {_quote_identifier(safe_col)} {col_type}"))
                    company_changed = True
                    print(f"{col_name} column added successfully!")

            if 'subscription_plan' not in columns:
                print("Adding subscription_plan column to company table...")
                try:
                    if db.engine.dialect.name == 'postgresql':
                        db.session.execute(text(f"ALTER TABLE {_quote_identifier('company')} ADD COLUMN IF NOT EXISTS {_quote_identifier('subscription_plan')} VARCHAR(50) DEFAULT 'standard'"))
                    else:
                        db.session.execute(text(f"ALTER TABLE {_quote_identifier('company')} ADD COLUMN {_quote_identifier('subscription_plan')} VARCHAR(50) DEFAULT 'standard'"))
                    db.session.commit()
                    print("subscription_plan column added successfully!")
                except Exception as sub_plan_e:
                    db.session.rollback()
                    fresh_columns = [col['name'] for col in inspect(db.engine).get_columns('company')]
                    if 'subscription_plan' not in fresh_columns:
                        print(f"Error adding subscription_plan column: {sub_plan_e}")
                        raise
                    print("subscription_plan column already exists.")

            # إضافة أعمدة الاشتراك التجريبي (Premium Trial)
            trial_columns = {
                'premium_trial_prompted': 'BOOLEAN DEFAULT 0',
                'premium_trial_active': 'BOOLEAN DEFAULT 0',
                'premium_trial_start': 'DATETIME',
                'premium_trial_end': 'DATETIME'
            }
            for col_name, col_type in trial_columns.items():
                if col_name not in columns:
                    print(f"Adding {col_name} column to company table...")
                    try:
                        safe_col = _sanitize_identifier(col_name)
                    except Exception as e:
                        print(f"Skipping invalid trial column {col_name}: {e}")
                        continue
                    db.session.execute(text(f"ALTER TABLE {_quote_identifier('company')} ADD COLUMN {_quote_identifier(safe_col)} {col_type}"))
                    company_changed = True
                    print(f"{col_name} column added successfully!")

            # Commit once for company-related DDL changes
            if company_changed:
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        if inspector.has_table('community_post'):
            cp_columns = [col['name'] for col in inspector.get_columns('community_post')]
            community_post_changed = False
            if 'is_anonymous' not in cp_columns:
                print("Adding is_anonymous column to community_post table...")
                db.session.execute(text('ALTER TABLE "community_post" ADD COLUMN "is_anonymous" BOOLEAN DEFAULT 0'))
                community_post_changed = True
                print("is_anonymous column added successfully!")
            community_post_expected_cols = {
                'audio_file_id': 'VARCHAR(255)',
                'audio_url': 'TEXT'
            }
            for col_name, col_type in community_post_expected_cols.items():
                if col_name not in cp_columns:
                    print(f"Adding {col_name} column to community_post table...")
                    try:
                        safe_col = _sanitize_identifier(col_name)
                    except Exception as e:
                        print(f"Skipping invalid community_post column {col_name}: {e}")
                        continue
                    db.session.execute(text(f"ALTER TABLE {_quote_identifier('community_post')} ADD COLUMN {_quote_identifier(safe_col)} {col_type}"))
                    community_post_changed = True
                    print(f"{col_name} column added successfully!")
            if community_post_changed:
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        if inspector.has_table('community_message'):
            cm_columns = [col['name'] for col in inspector.get_columns('community_message')]
            cm_changed = False
            # قائمة بكافة الأعمدة المتوقع وجودها في جدول community_message
            cm_expected_cols = {
                'company_id': 'INTEGER',
                'message': 'TEXT',
                'sent_at': 'DATETIME',
                'is_active': 'BOOLEAN DEFAULT 1',
                'is_pinned': 'BOOLEAN DEFAULT 0'
            }
            
            for col_name, col_type in cm_expected_cols.items():
                if col_name not in cm_columns:
                    print(f"Adding {col_name} column to community_message table...")
                    try:
                        safe_col = _sanitize_identifier(col_name)
                        db.session.execute(text(f"ALTER TABLE {_quote_identifier('community_message')} ADD COLUMN {_quote_identifier(safe_col)} {col_type}"))
                        cm_changed = True
                        print(f"{col_name} column added successfully!")
                    except Exception as e:
                        print(f"Error adding {col_name}: {e}")
                        db.session.rollback()
            if cm_changed:
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        if inspector.has_table('warehouse'):
            # إعادة قراءة أسماء الأعمدة قبل كل إضافة حتى لا نعتمد على قائمة قديمة
            # (يضمن ظهور last_process_filename و last_process_data_rows بعد النشر حتى لو أُضيفت لاحقاً للنموذج)
            warehouse_columns_to_ensure = [
                ('is_processing', 'BOOLEAN DEFAULT 0'),
                ('last_process_added', 'INTEGER DEFAULT 0'),
                ('last_process_updated', 'INTEGER DEFAULT 0'),
                ('last_process_reset', 'INTEGER DEFAULT 0'),
                ('last_process_status', 'VARCHAR(50)'),
                ('last_process_error', 'TEXT'),
                ('last_process_time', 'DATETIME'),
                ('last_process_filename', 'VARCHAR(255)'),
                ('last_process_data_rows', 'INTEGER DEFAULT 0'),
            ]
            warehouse_changed = False
            for col_name, col_type in warehouse_columns_to_ensure:
                fresh_insp = inspect(db.engine)
                existing = {c['name'] for c in fresh_insp.get_columns('warehouse')}
                if col_name in existing:
                    continue
                try:
                    print(f"Adding {col_name} column to warehouse table...")
                    try:
                        safe_col = _sanitize_identifier(col_name)
                    except Exception as e:
                        print(f"Skipping invalid warehouse column {col_name}: {e}")
                        continue
                    db.session.execute(text(f"ALTER TABLE {_quote_identifier('warehouse')} ADD COLUMN {_quote_identifier(safe_col)} {col_type}"))
                    warehouse_changed = True
                    print(f"{col_name} column added successfully!")
                except Exception as w_e:
                    print(f"Error adding warehouse column {col_name}: {w_e}")
                    db.session.rollback()
            if warehouse_changed:
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        if inspector.has_table('product_item'):
            product_item_columns = {col['name'] for col in inspector.get_columns('product_item')}
            product_item_changed = False
            for col_name, col_type in {'item_code': 'VARCHAR(100)', 'discount': 'VARCHAR(100)'}.items():
                if col_name not in product_item_columns:
                    try:
                        print(f"Adding {col_name} column to product_item table...")
                        safe_col = _sanitize_identifier(col_name)
                        db.session.execute(text(f"ALTER TABLE {_quote_identifier('product_item')} ADD COLUMN {_quote_identifier(safe_col)} {col_type}"))
                        product_item_changed = True
                    except Exception as p_e:
                        print(f"Error adding product_item column {col_name}: {p_e}")
                        db.session.rollback()
            if product_item_changed:
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        if inspector.has_table('product_stock_history'):
            product_stock_history_columns = {col['name'] for col in inspector.get_columns('product_stock_history')}
            psh_changed = False
            for col_name, col_type in {'item_code': 'VARCHAR(100)', 'discount': 'VARCHAR(100)'}.items():
                if col_name not in product_stock_history_columns:
                    try:
                        print(f"Adding {col_name} column to product_stock_history table...")
                        safe_col = _sanitize_identifier(col_name)
                        db.session.execute(text(f"ALTER TABLE {_quote_identifier('product_stock_history')} ADD COLUMN {_quote_identifier(safe_col)} {col_type}"))
                        psh_changed = True
                    except Exception as h_e:
                        print(f"Error adding product_stock_history column {col_name}: {h_e}")
                        db.session.rollback()
            if psh_changed:
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

        tables_to_check = ['admin', 'company', 'product_file', 'appointment', 'notification', 
                           'search_log', 'favorite_product', 'system_setting', 'product_item', 
                           'product_stock_history', 'ad_image', 'app_download_log', 'community_message',
                           'warehouse', 'warehouse_permissions']

        with db.engine.connect() as connection:
            for table_name in tables_to_check:
                if not inspector.has_table(table_name):
                    print(f"Table '{table_name}' does not exist. Attempting to create.")
                    try:
                        # Create all tables
                        db.create_all()
                        break
                    except Exception as e:
                        print(f"Error creating table '{table_name}': {e}")
                        db.session.rollback() 
            
        return True, "Database updated successfully!"
    except Exception as e:
        # تأكد من أننا داخل App Context قبل محاولة rollback
        from flask import has_app_context
        if has_app_context():
            db.session.rollback()
        import traceback
        traceback.print_exc()
        return False, f"An error occurred during database update: {str(e)}"
