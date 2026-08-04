# -*- coding: utf-8 -*-
"""بوت التعارف بين الشركات — رسائل ترحيب تظهر للمستقبل فقط."""

from __future__ import annotations

import random
from datetime import datetime

from models import Company, MessageBlock, PrivateMessage, PrivateMessageEditLog, SystemSetting, db

WARMUP_TEMPLATES = [
    'أهلا',
    'سلام عليكم',
    'مساء الخير',
    'صباح الخير',
]

SETTING_ENABLED = 'messaging_warmup_enabled'
SETTING_BATCH_SIZE = 'messaging_warmup_batch_size'


def _setting_bool(key: str, default: bool = False) -> bool:
    row = SystemSetting.query.filter_by(setting_key=key).first()
    if not row or row.setting_value is None:
        return default
    return str(row.setting_value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _setting_int(key: str, default: int) -> int:
    row = SystemSetting.query.filter_by(setting_key=key).first()
    if not row or not str(row.setting_value or '').strip().isdigit():
        return default
    return int(row.setting_value)


def is_warmup_enabled() -> bool:
    return _setting_bool(SETTING_ENABLED, False)


def get_warmup_batch_size() -> int:
    return max(1, min(_setting_int(SETTING_BATCH_SIZE, 3), 25))


def message_hidden_from_sender(message: PrivateMessage) -> bool:
    return bool(getattr(message, 'hidden_from_sender', False))


def message_visible_to_user(message: PrivateMessage, user_id: int) -> bool:
    if message.sender_id == user_id and message_hidden_from_sender(message):
        return False
    if message.sender_id == user_id and message.is_deleted_by_sender:
        return False
    if message.receiver_id == user_id and message.is_deleted_by_receiver:
        return False
    return True


def _is_official_company(company: Company) -> bool:
    name = (company.company_name or '').upper()
    username = (company.username or '').upper()
    return name == 'STOCK FLOW' or username == 'STOCK FLOW'


def _is_eligible_company(company: Company) -> bool:
    if not company or not getattr(company, 'is_active', True):
        return False
    if _is_official_company(company):
        return False
    if getattr(company, 'messaging_blocked', False):
        return False
    if not getattr(company, 'receive_messages_enabled', True):
        return False
    return True


def pair_has_existing_thread(company_a_id: int, company_b_id: int) -> bool:
    return db.session.query(PrivateMessage.id).filter(
        db.or_(
            db.and_(PrivateMessage.sender_id == company_a_id, PrivateMessage.receiver_id == company_b_id),
            db.and_(PrivateMessage.sender_id == company_b_id, PrivateMessage.receiver_id == company_a_id),
        )
    ).first() is not None


def _is_blocked(sender_id: int, receiver_id: int) -> bool:
    return db.session.query(MessageBlock.id).filter(
        db.or_(
            db.and_(MessageBlock.blocker_id == receiver_id, MessageBlock.blocked_id == sender_id),
            db.and_(MessageBlock.blocker_id == sender_id, MessageBlock.blocked_id == receiver_id),
        )
    ).first() is not None


def pick_random_greeting() -> str:
    return random.choice(WARMUP_TEMPLATES)


def send_ghost_intro(sender_id: int, receiver_id: int, message: str | None = None, *, push_notifier=None):
    """يرسل رسالة ترحيب تظهر للمستقبل فقط وكأن المرسل هو من بدأ المحادثة."""
    if sender_id == receiver_id:
        return False, 'لا يمكن إرسال رسالة لنفس الشركة.'

    sender = Company.query.get(sender_id)
    receiver = Company.query.get(receiver_id)
    if not sender or not receiver:
        return False, 'إحدى الشركتين غير موجودة.'

    if not _is_eligible_company(sender):
        return False, f'الشركة المرسلة ({sender.company_name}) غير مؤهلة.'
    if not _is_eligible_company(receiver):
        return False, f'الشركة المستقبلة ({receiver.company_name}) غير مؤهلة.'

    if _is_blocked(sender_id, receiver_id):
        return False, 'يوجد حظر بين الشركتين.'

    if pair_has_existing_thread(sender_id, receiver_id):
        return False, 'يوجد تواصل سابق بين الشركتين.'

    content = (message or '').strip() or pick_random_greeting()
    msg = PrivateMessage(
        sender_id=sender_id,
        receiver_id=receiver_id,
        subject='رسالة من الموبايل',
        message=content[:1000],
        sent_at=datetime.utcnow(),
        hidden_from_sender=True,
        is_read=False,
    )
    db.session.add(msg)
    db.session.commit()

    if push_notifier:
        preview = content[:50] + ('...' if len(content) > 50 else '')
        push_notifier(
            receiver_id,
            f'رسالة جديدة من {sender.company_name}',
            preview,
            {'type': 'message', 'sender_id': sender_id},
        )

    return True, f'تم إرسال رسالة تعارف من {sender.company_name} إلى {receiver.company_name}.'


def _pair_is_valid(sender: Company, receiver: Company) -> bool:
    if sender.id == receiver.id:
        return False
    if _is_blocked(sender.id, receiver.id):
        return False
    if pair_has_existing_thread(sender.id, receiver.id):
        return False
    return True


def _pick_random_direction(company_a: Company, company_b: Company) -> tuple[Company, Company] | None:
    """يختار اتجاه عشوائي للرسالة إن كان ممكناً في أي من الاتجاهين."""
    options = []
    if _pair_is_valid(company_a, company_b):
        options.append((company_a, company_b))
    if _pair_is_valid(company_b, company_a):
        options.append((company_b, company_a))
    return random.choice(options) if options else None


def build_disjoint_warmup_pairs(batch_size: int) -> list[tuple[Company, Company]]:
    """يبني أزواجاً عشوائية منفصلة: كل شركة تظهر مرة واحدة فقط (مرسلة أو مستقبلة، ليس الاثنين)."""
    companies = Company.query.filter_by(is_active=True).order_by(Company.id.asc()).all()
    eligible = [c for c in companies if _is_eligible_company(c)]
    random.shuffle(eligible)

    used_ids: set[int] = set()
    pairs: list[tuple[Company, Company]] = []

    for anchor in eligible:
        if len(pairs) >= batch_size:
            break
        if anchor.id in used_ids:
            continue

        partners = [c for c in eligible if c.id != anchor.id and c.id not in used_ids]
        random.shuffle(partners)

        matched = None
        for partner in partners:
            direction = _pick_random_direction(anchor, partner)
            if direction:
                matched = direction
                break

        if matched:
            sender, receiver = matched
            pairs.append((sender, receiver))
            used_ids.add(sender.id)
            used_ids.add(receiver.id)

    return pairs


def run_warmup_batch(batch_size: int | None = None, *, push_notifier=None):
    size = batch_size or get_warmup_batch_size()
    pairs = build_disjoint_warmup_pairs(size)

    sent = []
    skipped = []

    for sender, receiver in pairs:
        ok, detail = send_ghost_intro(sender.id, receiver.id, push_notifier=push_notifier)
        if ok:
            sent.append({
                'sender': sender.company_name,
                'receiver': receiver.company_name,
                'detail': detail,
            })
        else:
            skipped.append((sender.company_name, receiver.company_name, detail))

    return {
        'success': True,
        'sent_count': len(sent),
        'sent': sent,
        'skipped_count': len(skipped),
        'skipped': skipped[:20],
        'requested_pairs': size,
    }


def get_warmup_messages_count() -> int:
    return PrivateMessage.query.filter_by(hidden_from_sender=True).count()


def delete_all_warmup_messages():
    """يحذف كل رسائل الراندم السابقة نهائياً من قاعدة البيانات."""
    message_ids = [
        row[0] for row in db.session.query(PrivateMessage.id).filter_by(hidden_from_sender=True).all()
    ]

    if not message_ids:
        return {'success': True, 'deleted_count': 0}

    PrivateMessageEditLog.query.filter(PrivateMessageEditLog.message_id.in_(message_ids)).delete(
        synchronize_session=False,
    )
    deleted_count = PrivateMessage.query.filter(PrivateMessage.id.in_(message_ids)).delete(
        synchronize_session=False,
    )
    db.session.commit()

    return {'success': True, 'deleted_count': deleted_count}
