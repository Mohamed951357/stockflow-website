# -*- coding: utf-8 -*-
"""
toby_whatsapp.py — موديول إرسال إشعارات انخفاض المخزون عبر الواتساب من توبي (Toby WhatsApp Bridge Integration)
مكفول ومعد خصيصاً للعملاء المميزين الساريين فقط، وبدون أي تأثير على سرعة أداء الموقع أو توبي.
"""
import os
import requests
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# الإعدادات الافتراضية لجسر توبي للواتساب (Toby WhatsApp Bridge)
DEFAULT_BRIDGE_URL = "http://127.0.0.1:8788/api/send-admin"
DEFAULT_ADMIN_TOKEN = "u2haqx3yH6OHFJZrc7I_eHGXsMsLXwmoI1Kal6FEyII"

def format_egyptian_phone(phone_raw):
    """
    تحويل وتنسيق الأرقام المصرية تلقائياً للصيغة الدولية القياسية.
    أمثلة:
    - 01012345678    -> 201012345678
    - 1012345678     -> 201012345678
    - +201012345678  -> 201012345678
    - 00201012345678 -> 201012345678
    """
    if not phone_raw:
        return None
    
    digits = ''.join(c for c in str(phone_raw) if c.isdigit())
    if not digits:
        return None

    if digits.startswith('0020'):
        digits = digits[2:]
    
    if digits.startswith('01') and len(digits) == 11:
        digits = '20' + digits[1:]
    elif digits.startswith('1') and len(digits) == 10:
        digits = '20' + digits
    elif digits.startswith('20') and len(digits) == 12:
        pass
    elif len(digits) in (10, 11) and not digits.startswith('20'):
        digits = '20' + digits.lstrip('0')

    return digits


def send_toby_whatsapp_stock_notification(company_phone, company_name, product_name, sold_qty, remaining_qty):
    """
    إرسال إشعار انخفاض مخزون عبر الواتساب من توبي مباشرة للمستخدمين المميزين الساريين.
    تتم المعالجة بأمان تام مع تسجيل اللوج ودون تأخير السيرفر.
    """
    formatted_phone = format_egyptian_phone(company_phone)
    if not formatted_phone:
        logger.debug(f"[Toby WhatsApp] Skipped: Invalid or missing phone number '{company_phone}' for {company_name}")
        return False

    bridge_url = os.environ.get('TOBY_BRIDGE_SEND_URL') or DEFAULT_BRIDGE_URL
    admin_token = os.environ.get('TOBY_ADMIN_TOKEN') or DEFAULT_ADMIN_TOKEN

    # قالب رسالة توبي الأنيق والمحترف بالاسم والتوجيه للتطبيق
    comp_name_str = (company_name or 'المشترك المميز').strip()
    message_body = (
        f"أهلاً بك / *{comp_name_str}* 🌸\n"
        f"لديك تحديث بخصوص رصيد صنف (*{product_name}*) الآن.\n\n"
        f"📱 افتح تطبيق ستوك فلو لمتابعة الرصيد الحالي."
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {admin_token}",
        "x-admin-token": admin_token
    }

    payload = {
        "to": formatted_phone,
        "message": message_body
    }

    try:
        response = requests.post(bridge_url, json=payload, headers=headers, timeout=12)
        if response.status_code == 200:
            logger.info(f"[Toby WhatsApp Delivered] Successfully sent to {formatted_phone} ({company_name})")
            return True
        else:
            logger.warning(f"[Toby WhatsApp Bridge Error] HTTP {response.status_code}: {response.text[:200]}")
            return False
    except Exception as exc:
        logger.warning(f"[Toby WhatsApp Exception] Failed to send to {formatted_phone}: {exc}")
        return False


def send_toby_whatsapp_stock_notification_async(company_phone, company_name, product_name, sold_qty, remaining_qty):
    """
    تشغيل الإرسال في خلفية الخيط (Daemon Thread) لمنع أي تأثير على سرعة استجابة السيرفر.
    """
    thread = threading.Thread(
        target=send_toby_whatsapp_stock_notification,
        args=(company_phone, company_name, product_name, sold_qty, remaining_qty),
        daemon=True,
        name=f"toby-wa-{datetime.utcnow().timestamp()}"
    )
    thread.start()
