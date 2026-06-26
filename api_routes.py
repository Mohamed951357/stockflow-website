from flask import Blueprint, request, jsonify, session, current_app, url_for
from flask_login import login_user, login_required, current_user, logout_user
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
import hmac
import json
import os
import pytz
import random
import threading
import time

from models import db, Company, ProductStockHistory, Appointment, Notification, NotificationRead, FavoriteProduct, SystemSetting, CommunityMessage, PrivateMessage, Admin, ProductItem, Warehouse
from sqlalchemy import or_, and_, desc, func
from sqlalchemy.exc import OperationalError
from upload_control import UploadCancelledError, clear_upload_cancel, is_upload_cancel_requested
from utils import find_company_for_login

api_bp = Blueprint('api', __name__, url_prefix='/api')

CAIRO_TIMEZONE = pytz.timezone('Africa/Cairo')
# القيمة الافتراضية للـ stale timeout — يمكن تجاوزها من DB أو env var
_ERP_PROCESSING_STALE_MINUTES_DEFAULT = max(1, int(os.environ.get('ERP_PROCESSING_STALE_MINUTES', '60')))


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on', 'y'}


def _get_erp_processing_stale_minutes():
    """اقرأ مهلة المعالجة من DB ثم env ثم الافتراضي 60 دقيقة."""
    try:
        setting = SystemSetting.query.filter_by(
            setting_key='erp_processing_stale_minutes'
        ).first()
        if setting and setting.setting_value:
            val = int(setting.setting_value)
            return max(1, val)
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    return _ERP_PROCESSING_STALE_MINUTES_DEFAULT

# حد أقصى لعدد صفوف سجل المخزون اليومي (لتوفير المساحة)
_STOCK_HISTORY_MAX_ROWS = int(os.environ.get('STOCK_HISTORY_MAX_ROWS', '300000'))
_STOCK_HISTORY_KEEP_DAYS = int(os.environ.get('STOCK_HISTORY_KEEP_DAYS', '90'))


def _is_sqlite_lock_error(exc):
    return 'database is locked' in str(exc).lower() or 'database table is locked' in str(exc).lower()


def _run_with_sqlite_lock_retry(operation, max_retries=4, retry_delay_seconds=2):
    last_exc = None

    for attempt in range(max_retries):
        try:
            return operation()
        except OperationalError as exc:
            db.session.rollback()
            last_exc = exc
            if (not _is_sqlite_lock_error(exc)) or attempt == max_retries - 1:
                raise
            time.sleep(retry_delay_seconds)

    if last_exc:
        raise last_exc


def _use_file_backed_bridge_runtime_status():
    backend = (os.environ.get('ERP_BRIDGE_RUNTIME_BACKEND') or '').strip().lower()
    if backend in {'file', 'json'}:
        return True
    if backend in {'db', 'database'}:
        return False

    database_uri = (current_app.config.get('SQLALCHEMY_DATABASE_URI') or '').strip().lower()
    return database_uri.startswith('sqlite')


def _get_bridge_runtime_status_file_path():
    configured_path = (os.environ.get('ERP_BRIDGE_RUNTIME_STATUS_FILE') or '').strip()
    if configured_path:
        return configured_path

    os.makedirs(current_app.instance_path, exist_ok=True)
    return os.path.join(current_app.instance_path, 'erp_bridge_runtime_status.json')


def _read_bridge_runtime_status_from_file():
    path = _get_bridge_runtime_status_file_path()
    if not os.path.exists(path):
        return {}

    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle) or {}
    except Exception:
        current_app.logger.exception("Failed to read ERP bridge runtime status file")
        return {}


def _write_bridge_runtime_status_to_file(payload):
    path = _get_bridge_runtime_status_file_path()
    temp_path = f"{path}.tmp"

    with open(temp_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)

    os.replace(temp_path, path)


def _get_erp_bridge_token():
    env_token = (os.environ.get('ERP_BRIDGE_TOKEN') or '').strip()
    if env_token:
        return env_token

    try:
        token_setting = SystemSetting.query.filter_by(setting_key='erp_bridge_token').first()
        return ((token_setting.setting_value if token_setting else '') or '').strip()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to read ERP bridge token from database")
        return ''


def _get_bridge_runtime_status():
    if _use_file_backed_bridge_runtime_status():
        return _read_bridge_runtime_status_from_file()

    try:
        setting = SystemSetting.query.filter_by(setting_key='erp_bridge_runtime_status').first()
        if not setting or not setting.setting_value:
            return {}
        return json.loads(setting.setting_value)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to read ERP bridge runtime status from database")
        return {}


def _save_bridge_runtime_status(payload):
    if _use_file_backed_bridge_runtime_status():
        _write_bridge_runtime_status_to_file(payload)
        return

    def persist_runtime_status():
        setting = SystemSetting.query.filter_by(setting_key='erp_bridge_runtime_status').first()
        serialized = json.dumps(payload, ensure_ascii=False)

        if setting:
            setting.setting_value = serialized
            setting.last_updated = datetime.utcnow()
        else:
            setting = SystemSetting(
                setting_key='erp_bridge_runtime_status',
                setting_value=serialized,
                last_updated=datetime.utcnow()
            )
            db.session.add(setting)

        db.session.commit()

    return _run_with_sqlite_lock_retry(persist_runtime_status, max_retries=2, retry_delay_seconds=1)


def _parse_bridge_runtime_time(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = pytz.utc.localize(parsed)
        return parsed.astimezone(pytz.utc)
    except Exception:
        return None


def _get_fresh_bridge_runtime_for_warehouse(warehouse):
    if not warehouse:
        return None

    runtime_payload = _get_bridge_runtime_status()
    if not runtime_payload:
        return None

    warehouse_statuses = runtime_payload.get('warehouses')
    if isinstance(warehouse_statuses, dict):
        scoped_payload = warehouse_statuses.get(str(warehouse.id))
        if isinstance(scoped_payload, dict):
            runtime_payload = scoped_payload

    runtime_warehouse_id = runtime_payload.get('warehouse_id')
    if runtime_warehouse_id not in (None, ''):
        try:
            if int(runtime_warehouse_id) != int(warehouse.id):
                return None
        except Exception:
            return None

    updated_at = _parse_bridge_runtime_time(runtime_payload.get('updated_at_utc'))
    if not updated_at:
        return None

    try:
        age = datetime.utcnow().replace(tzinfo=pytz.utc) - updated_at
    except Exception:
        return None

    if age > timedelta(seconds=150):
        return None

    return runtime_payload


def _read_bridge_token_from_request(expected_token):
    auth_header = request.headers.get('Authorization', '')
    provided_token = ''

    if auth_header.lower().startswith('bearer '):
        provided_token = auth_header[7:].strip()

    if not provided_token:
        provided_token = (request.headers.get('X-ERP-Token') or '').strip()

    if not provided_token or not hmac.compare_digest(provided_token, expected_token):
        return None

    return provided_token


def _parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


# ─── ERP Bridge Throttle (فلتر الفترة الزمنية بين التحديثات) ───────────────
# يُسمح لبرنامج الربط بالاستمرار في الإرسال دون أي تغيير في سلوكه.
# الموقع يرد دائماً بـ 200 OK ولكنه يتجاهل المعالجة الثقيلة إذا لم ينقضِ الوقت.
_ERP_THROTTLE_LOCK = threading.Lock()
_ERP_THROTTLE_LAST_ACCEPTED: dict = {}  # warehouse_id -> datetime (utc)


def _get_erp_bridge_min_interval_minutes():
    """اقرأ الحد الأدنى للفترة بالدقائق من إعدادات النظام.
    القيمة 0 تعني مطفي (اقبل كل تحديث).
    """
    try:
        setting = SystemSetting.query.filter_by(
            setting_key='erp_bridge_min_interval_minutes'
        ).first()
        if setting and setting.setting_value:
            val = int(setting.setting_value)
            return max(0, val)
    except Exception:
        db.session.rollback()
    return 0


def _check_erp_bridge_throttle(warehouse_id):
    """تحقق من انقضاء الفترة الزمنية المحددة منذ آخر تحديث مقبول.

    يعيد: (should_process: bool, wait_minutes: float)
      - should_process=True  → اقبل التحديث الآن
      - should_process=False → تجاهل التحديث (الوقت لم ينقضِ بعد)

    ملاحظة: الرد لبرنامج الربط يكون 200 OK في كلتا الحالتين حتى لا يتأثر.
    """
    min_interval = _get_erp_bridge_min_interval_minutes()
    if min_interval <= 0:
        return True, 0.0

    key = int(warehouse_id) if warehouse_id is not None else 0
    now_utc = datetime.utcnow()

    # 1: اقرأ آخر وقت قبول من الـ in-memory cache
    with _ERP_THROTTLE_LOCK:
        last_accepted = _ERP_THROTTLE_LAST_ACCEPTED.get(key)

    # 2: لو الـ cache فارغ (مثلاً بعد restart)، اقرأ من DB
    if last_accepted is None:
        try:
            db_s = SystemSetting.query.filter_by(
                setting_key=f'erp_bridge_last_accepted_{key}'
            ).first()
            if db_s and db_s.setting_value:
                last_accepted = datetime.fromisoformat(db_s.setting_value)
                with _ERP_THROTTLE_LOCK:
                    _ERP_THROTTLE_LAST_ACCEPTED[key] = last_accepted
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

    # 3: تحقق من الوقت المنقضي
    if last_accepted is not None:
        elapsed = (now_utc - last_accepted).total_seconds() / 60.0
        if elapsed < min_interval:
            return False, min_interval - elapsed

    # 4: الوقت انقضى أو أول مرة — سجّل وقت القبول
    with _ERP_THROTTLE_LOCK:
        _ERP_THROTTLE_LAST_ACCEPTED[key] = now_utc

    # حفظ في DB بشكل مباشر (synchronous) لضمان ظهور الوقت في الواجهة دائماً
    # ملاحظة: كنا نستخدم daemon thread لكنه كان يفشل على بعض بيئات الاستضافة
    # مما يجعل الـ UI يعرض "لم يُقبَل أي تحديث بعد" حتى لو التحديث اشتغل فعلاً
    try:
        iso = now_utc.isoformat()
        _s = SystemSetting.query.filter_by(
            setting_key=f'erp_bridge_last_accepted_{key}'
        ).first()
        if _s:
            _s.setting_value = iso
            _s.last_updated = datetime.utcnow()
        else:
            _s = SystemSetting(
                setting_key=f'erp_bridge_last_accepted_{key}',
                setting_value=iso
            )
            db.session.add(_s)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

    return True, 0.0


def _coerce_quantity(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(',', '')
    if not text:
        return 0.0

    try:
        return float(text)
    except ValueError:
        return 0.0


def _stringify_value(value, fallback='0'):
    if value is None:
        return fallback

    text = str(value).strip()
    return text if text else fallback


def _resolve_target_warehouse(warehouse_id=None, warehouse_name=None, auto_create=False):
    if warehouse_id is not None:
        return Warehouse.query.get(warehouse_id)

    clean_name = str(warehouse_name or '').strip()
    if clean_name:
        warehouse = (
            Warehouse.query
            .filter(func.lower(Warehouse.name) == clean_name.lower())
            .first()
        )
        if warehouse:
            return warehouse

        if auto_create:
            warehouse = Warehouse(
                name=clean_name,
                description='تم إنشاؤه تلقائياً من برنامج الربط.',
                is_active=True,
                created_at=datetime.utcnow()
            )
            db.session.add(warehouse)
            db.session.commit()
            return warehouse

    return Warehouse.query.first()


def _clear_stale_processing_if_needed(warehouse):
    if not warehouse:
        return False

    stale_minutes = _get_erp_processing_stale_minutes()

    runtime_payload = _get_fresh_bridge_runtime_for_warehouse(warehouse)
    runtime_status = str((runtime_payload or {}).get('status') or '').strip().lower()

    # لا نقتل المعالجة بناءً على نبضة "error" إلا لو انقضى وقت الـ stale فعلاً.
    # السبب: البرنامج قد يرسل "error" مؤقتاً أثناء إعادة المحاولة
    # بينما الموقع لا يزال يعالج snapshot سابق.
    if warehouse.is_processing and runtime_status == 'success':
        clear_upload_cancel(warehouse.id)
        warehouse.is_processing = False
        warehouse.last_process_status = 'success'
        warehouse.last_process_error = None
        warehouse.last_process_time = datetime.utcnow()
        db.session.commit()
        current_app.logger.info(
            'Auto-cleared processing flag for warehouse %s: bridge reported success.',
            warehouse.id
        )
        return True

    # السبب الرئيسي للـ 409 المتكرر: حالة 'cancelling' أو 'cancel_requested' عالقة.
    # نظّفها فوراً بغض النظر عن الوقت.
    _STUCK_CANCEL_STATUSES = {'cancelling', 'cancel_requested'}
    stuck_cancel = (
        (warehouse.last_process_status or '').strip().lower() in _STUCK_CANCEL_STATUSES
    )
    if stuck_cancel:
        clear_upload_cancel(warehouse.id)
        warehouse.is_processing = False
        warehouse.last_process_status = 'error'
        warehouse.last_process_error = (
            'Auto-cleared a stuck cancellation flag so the bridge can resume.'
        )
        warehouse.last_process_time = datetime.utcnow()
        db.session.commit()
        current_app.logger.warning(
            'Auto-cleared stuck cancel status (%s) for warehouse %s.',
            warehouse.last_process_status, warehouse.id
        )
        return True

    if not warehouse.is_processing:
        return False

    last_process_time = warehouse.last_process_time
    if not last_process_time:
        return False

    try:
        is_stale = (datetime.utcnow() - last_process_time) >= timedelta(minutes=stale_minutes)
    except Exception:
        return False

    if not is_stale:
        return False

    clear_upload_cancel(warehouse.id)
    warehouse.is_processing = False
    warehouse.last_process_status = 'error'
    warehouse.last_process_error = (
        f'Auto-cleared a stale processing flag after more than {stale_minutes} minutes.'
    )
    warehouse.last_process_time = datetime.utcnow()
    db.session.commit()
    return True


def _iter_chunks(values, chunk_size=400):
    sequence = [value for value in values if value]
    for index in range(0, len(sequence), chunk_size):
        yield sequence[index:index + chunk_size]


def _load_latest_daily_stock_history_map(product_names, target_date=None, warehouse_id=None):
    target_date = target_date or date.today()
    history_map = {}

    for name_chunk in _iter_chunks(set(product_names or [])):
        query = (
            ProductStockHistory.query
            .filter(
                ProductStockHistory.record_date == target_date,
                ProductStockHistory.product_name.in_(name_chunk)
            )
        )
        if warehouse_id is not None and hasattr(ProductStockHistory, 'warehouse_id'):
            query = query.filter(ProductStockHistory.warehouse_id == warehouse_id)

        rows = query.order_by(
            ProductStockHistory.product_name.asc(),
            ProductStockHistory.recorded_at.desc()
        ).all()

        for row in rows:
            if row.product_name not in history_map:
                history_map[row.product_name] = row

    return history_map


def _upsert_daily_stock_history(item_code, product_name, quantity, price=None, discount=None, history_cache=None, record_date=None, warehouse_id=None):
    """Keep at most one stock history row per product per day."""
    today = record_date or date.today()
    history_entry = None

    if history_cache is not None:
        history_entry = history_cache.get(product_name)
        if history_entry and history_entry.record_date != today:
            history_entry = None

    if history_entry is None:
        with db.session.no_autoflush:
            query = ProductStockHistory.query.filter_by(
                product_name=product_name,
                record_date=today
            )
            if warehouse_id is not None and hasattr(ProductStockHistory, 'warehouse_id'):
                query = query.filter(ProductStockHistory.warehouse_id == warehouse_id)
            history_entry = query.order_by(ProductStockHistory.recorded_at.desc()).first()
        if history_cache is not None and history_entry:
            history_cache[product_name] = history_entry

    if history_entry:
        history_entry.item_code = item_code
        history_entry.quantity = quantity
        history_entry.price = price
        history_entry.discount = discount
        if warehouse_id is not None and hasattr(history_entry, 'warehouse_id'):
            history_entry.warehouse_id = warehouse_id
        history_entry.recorded_at = datetime.utcnow()
        return history_entry

    history_entry = ProductStockHistory(
        item_code=item_code,
        product_name=product_name,
        quantity=quantity,
        price=price,
        discount=discount,
        warehouse_id=warehouse_id,
        record_date=today
    )
    db.session.add(history_entry)
    if history_cache is not None:
        history_cache[product_name] = history_entry
    return history_entry


def _prune_stock_history_if_needed():
    """حذف سجلات المخزون القديمة بذكاء لتوفير المساحة على السيرفر.

    تعمل هذه الدالة بعد كل رفع ناجح وتطبق حدّين:
    1. احتفظ فقط بآخر _STOCK_HISTORY_KEEP_DAYS يوم من السجلات.
    2. إذا تخطى إجمالي الصفوف _STOCK_HISTORY_MAX_ROWS، احذف الأقدم حتى
       تعود إلى 80% من الحد الأقصى.
    """
    try:
        cutoff_date = (datetime.utcnow() - timedelta(days=_STOCK_HISTORY_KEEP_DAYS)).date()

        # حذف السجلات الأقدم من الحد الزمني
        deleted_by_date = ProductStockHistory.query.filter(
            ProductStockHistory.record_date < cutoff_date
        ).delete(synchronize_session=False)

        if deleted_by_date > 0:
            db.session.commit()
            current_app.logger.info(
                'Stock history pruner: deleted %d rows older than %s.',
                deleted_by_date, cutoff_date
            )

        # فحص الحد الأقصى للصفوف
        total_rows = db.session.query(db.func.count(ProductStockHistory.id)).scalar() or 0
        if total_rows > _STOCK_HISTORY_MAX_ROWS:
            # احتفظ بـ 80% من الحد الأقصى (حذف الأقدم أولاً)
            target_rows = int(_STOCK_HISTORY_MAX_ROWS * 0.8)
            rows_to_delete = total_rows - target_rows

            # نجلب IDs الأقدم ونحذفها
            oldest_ids = (
                db.session.query(ProductStockHistory.id)
                .order_by(ProductStockHistory.record_date.asc(), ProductStockHistory.recorded_at.asc())
                .limit(rows_to_delete)
                .all()
            )
            oldest_id_list = [row[0] for row in oldest_ids]

            if oldest_id_list:
                ProductStockHistory.query.filter(
                    ProductStockHistory.id.in_(oldest_id_list)
                ).delete(synchronize_session=False)
                db.session.commit()
                current_app.logger.info(
                    'Stock history pruner: deleted %d rows (cap exceeded: %d > %d).',
                    len(oldest_id_list), total_rows, _STOCK_HISTORY_MAX_ROWS
                )
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Stock history pruner failed (non-fatal).')


def _raise_if_upload_cancel_requested(warehouse_id):
    if is_upload_cancel_requested(warehouse_id):
        raise UploadCancelledError('تم إيقاف عملية رفع الملف إجبارياً من صفحة الرفع.')


def _run_erp_stock_snapshot_in_background(app, warehouse_id, items, full_sync):
    with app.app_context():
        try:
            _run_with_sqlite_lock_retry(
                lambda: _apply_erp_stock_snapshot(
                    items=items,
                    warehouse_id=warehouse_id,
                    full_sync=full_sync,
                    assume_processing=True
                ),
                max_retries=3,
                retry_delay_seconds=2
            )
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception(
                'Background ERP stock sync failed for warehouse %s',
                warehouse_id
            )
            try:
                warehouse = Warehouse.query.get(warehouse_id)
                if warehouse and warehouse.is_processing:
                    warehouse.is_processing = False
                    warehouse.last_process_status = 'error'
                    warehouse.last_process_error = str(exc)[:500] or 'Background ERP sync failed.'
                    warehouse.last_process_time = datetime.utcnow()
                    db.session.commit()
            except Exception:
                db.session.rollback()
        finally:
            db.session.remove()


def _queue_erp_stock_snapshot(items, warehouse_id=None, full_sync=True):
    warehouse = _resolve_target_warehouse(warehouse_id)
    if not warehouse:
        raise ValueError('No target warehouse found.')

    if _clear_stale_processing_if_needed(warehouse):
        warehouse = Warehouse.query.get(warehouse.id)
    if warehouse.is_processing:
        raise RuntimeError('A stock update is already running for this warehouse.')

    clear_upload_cancel(warehouse.id)
    warehouse.is_processing = True
    warehouse.last_process_status = 'processing'
    warehouse.last_process_error = None
    warehouse.last_process_added = 0
    warehouse.last_process_updated = 0
    warehouse.last_process_reset = 0
    warehouse.last_process_data_rows = len(items or [])
    warehouse.last_process_time = datetime.utcnow()
    db.session.commit()

    app = current_app._get_current_object()
    worker = threading.Thread(
        target=_run_erp_stock_snapshot_in_background,
        args=(app, warehouse.id, list(items or []), full_sync),
        daemon=False,
        name=f'erp-stock-sync-{warehouse.id}-{int(time.time())}'
    )
    worker.start()

    return {
        'warehouse_id': warehouse.id,
        'warehouse_name': warehouse.name,
        'accepted_processing': True,
        'is_processing': True,
        'item_count': len(items or []),
        'full_sync': full_sync,
    }


def _apply_erp_stock_snapshot(items, warehouse_id=None, full_sync=True, assume_processing=False):
    warehouse = _resolve_target_warehouse(warehouse_id)
    if not warehouse:
        raise ValueError('No target warehouse found.')

    # تنظيف أي حالة عالقة (cancelling / cancel_requested / stale is_processing)
    if not assume_processing:
        if _clear_stale_processing_if_needed(warehouse):
            warehouse = Warehouse.query.get(warehouse.id)
        if warehouse.is_processing:
            raise RuntimeError('A stock update is already running for this warehouse.')

    if not assume_processing:
        clear_upload_cancel(warehouse.id)
        warehouse.is_processing = True
        warehouse.last_process_status = 'processing'
        warehouse.last_process_error = None
        warehouse.last_process_time = datetime.utcnow()
        db.session.commit()

    added_count = 0
    updated_count = 0
    reset_count = 0
    skipped_count = 0
    processed_names = set()
    processed_item_codes = set()
    normalized_items = []
    today = date.today()

    try:
        for raw_item in items:
            _raise_if_upload_cancel_requested(warehouse.id)

            if not isinstance(raw_item, dict):
                skipped_count += 1
                continue

            name = _stringify_value(
                raw_item.get('name') or raw_item.get('product_name'),
                fallback=''
            )
            if not name:
                skipped_count += 1
                continue

            item_code_text = _stringify_value(raw_item.get('item_code'), fallback='')
            quantity_text = _stringify_value(raw_item.get('quantity'), fallback='0')
            price_text = _stringify_value(raw_item.get('price'), fallback='0')
            discount_text = _stringify_value(raw_item.get('discount'), fallback='')
            quantity_value = _coerce_quantity(raw_item.get('quantity'))

            normalized_item = {
                'name': name,
                'item_code_text': item_code_text,
                'quantity_text': quantity_text,
                'price_text': price_text,
                'discount_text': discount_text,
                'quantity_value': quantity_value,
            }
            processed_names.add(name)
            if item_code_text:
                processed_item_codes.add(item_code_text)
            normalized_items.append(normalized_item)

        with db.session.no_autoflush:
            existing_products = ProductItem.query.filter_by(warehouse_id=warehouse.id).all()
        products_by_item_code = {
            (product.item_code or '').strip(): product
            for product in existing_products
            if (product.item_code or '').strip()
        }
        products_by_name = {
            (product.name or '').strip(): product
            for product in existing_products
            if (product.name or '').strip()
        }

        history_names = set(processed_names)
        if full_sync:
            history_names.update(products_by_name.keys())
        history_cache = _load_latest_daily_stock_history_map(
            history_names,
            target_date=today,
            warehouse_id=warehouse.id
        )

        for normalized_item in normalized_items:
            _raise_if_upload_cancel_requested(warehouse.id)

            name = normalized_item['name']
            item_code_text = normalized_item['item_code_text']
            quantity_text = normalized_item['quantity_text']
            price_text = normalized_item['price_text']
            discount_text = normalized_item['discount_text']
            quantity_value = normalized_item['quantity_value']

            existing_product = None
            if item_code_text:
                existing_product = products_by_item_code.get(item_code_text)

            if not existing_product:
                candidate_product = products_by_name.get(name)
                if candidate_product:
                    candidate_item_code = (candidate_product.item_code or '').strip()
                    if not item_code_text or not candidate_item_code or candidate_item_code == item_code_text:
                        existing_product = candidate_product

            should_write_history = False
            if existing_product:
                previous_name = (existing_product.name or '').strip()
                previous_item_code = (existing_product.item_code or '').strip()
                new_item_code = item_code_text or existing_product.item_code
                if (
                    (previous_name or '') != name or
                    (existing_product.item_code or '') != (new_item_code or '') or
                    (existing_product.quantity or '') != quantity_text or
                    (existing_product.price or '') != price_text or
                    (existing_product.discount or '') != discount_text
                ):
                    existing_product.name = name
                    existing_product.item_code = new_item_code
                    existing_product.quantity = quantity_text
                    existing_product.price = price_text
                    existing_product.discount = discount_text
                    updated_count += 1
                    should_write_history = True
                else:
                    skipped_count += 1

                if previous_name and products_by_name.get(previous_name) is existing_product and previous_name != name:
                    del products_by_name[previous_name]
                products_by_name[name] = existing_product

                if previous_item_code and products_by_item_code.get(previous_item_code) is existing_product and previous_item_code != (new_item_code or ''):
                    del products_by_item_code[previous_item_code]
                if new_item_code:
                    products_by_item_code[new_item_code] = existing_product
            else:
                existing_product = ProductItem(
                    item_code=item_code_text,
                    name=name,
                    quantity=quantity_text,
                    price=price_text,
                    discount=discount_text,
                    warehouse_id=warehouse.id
                )
                db.session.add(existing_product)
                products_by_name[name] = existing_product
                if item_code_text:
                    products_by_item_code[item_code_text] = existing_product
                added_count += 1
                should_write_history = True

            if should_write_history:
                _upsert_daily_stock_history(
                    item_code=item_code_text,
                    product_name=name,
                    quantity=quantity_value,
                    price=price_text,
                    discount=discount_text,
                    history_cache=history_cache,
                    record_date=today,
                    warehouse_id=warehouse.id
                )

        if full_sync:
            _raise_if_upload_cancel_requested(warehouse.id)

            missing_products = []
            seen_missing_product_ids = set()
            for product in products_by_name.values():
                product_name = (product.name or '').strip()
                product_item_code = (product.item_code or '').strip()

                was_processed = False
                if product_item_code:
                    was_processed = product_item_code in processed_item_codes
                elif product_name:
                    was_processed = product_name in processed_names

                if was_processed or product.id in seen_missing_product_ids:
                    continue

                seen_missing_product_ids.add(product.id)
                missing_products.append(product)

            for product in missing_products:
                _raise_if_upload_cancel_requested(warehouse.id)
                if product.quantity != '0':
                    product.quantity = '0'
                    reset_count += 1
                    _upsert_daily_stock_history(
                        item_code=product.item_code,
                        product_name=product.name,
                        quantity=0.0,
                        price=product.price,
                        discount=product.discount,
                        history_cache=history_cache,
                        record_date=today,
                        warehouse_id=warehouse.id
                    )

        warehouse.is_processing = False
        warehouse.last_process_added = added_count
        warehouse.last_process_updated = updated_count
        warehouse.last_process_reset = reset_count
        warehouse.last_process_status = 'success'
        warehouse.last_process_error = None
        warehouse.last_process_time = datetime.utcnow()
        warehouse.last_process_data_rows = len(processed_names)
        db.session.commit()
        clear_upload_cancel(warehouse.id)

        # تنظيف ذكي لسجل المخزون بعد كل رفع ناجح
        _prune_stock_history_if_needed()

        return {
            'warehouse_id': warehouse.id,
            'warehouse_name': warehouse.name,
            'processed': len(processed_names),
            'added': added_count,
            'updated': updated_count,
            'reset': reset_count,
            'skipped': skipped_count,
            'full_sync': full_sync,
        }
    except UploadCancelledError as exc:
        db.session.rollback()
        warehouse = Warehouse.query.get(warehouse.id)
        if warehouse:
            warehouse.is_processing = False
            warehouse.last_process_status = 'cancelled'
            warehouse.last_process_error = str(exc)
            warehouse.last_process_time = datetime.utcnow()
            db.session.commit()
        clear_upload_cancel(warehouse_id or (warehouse.id if warehouse else None))
        raise
    except Exception as exc:
        db.session.rollback()
        if _is_sqlite_lock_error(exc):
            raise
        warehouse = Warehouse.query.get(warehouse.id)
        if warehouse:
            warehouse.is_processing = False
            warehouse.last_process_status = 'error'
            warehouse.last_process_error = 'ERP bridge sync failed.'
            warehouse.last_process_time = datetime.utcnow()
            db.session.commit()
        clear_upload_cancel(warehouse_id or (warehouse.id if warehouse else None))
        raise

@api_bp.route('/login', methods=['POST'])
def api_login():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No input data provided'}), 400
    
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    remember_me = _coerce_bool(data.get('remember_me'), default=True)

    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password are required'}), 400

    # Only allow company login for now as per requirement "connect website with mobile application" for companies
    user = find_company_for_login(username, password)
    
    if user:
        if user.is_active:
            session['user_type'] = 'company'
            session.permanent = True
            login_user(user, remember=remember_me, duration=timedelta(days=60) if remember_me else None)
            
            try:
                user.last_login = datetime.utcnow()
                db.session.commit()
            except Exception:
                db.session.rollback()
            
            return jsonify({
                'success': True,
                'message': 'Login successful',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'company_name': user.company_name,
                    'email': user.email,
                    'phone': user.phone,
                    'avatar': user.avatar
                }
            })
        else:
            return jsonify({'success': False, 'message': 'Account is inactive'}), 403
    
    return jsonify({'success': False, 'message': 'Invalid username or password'}), 401

@api_bp.route('/logout', methods=['POST'])
@login_required
def api_logout():
    logout_user()
    session.pop('user_type', None)
    return jsonify({'success': True, 'message': 'Logged out successfully'})

@api_bp.route('/company/dashboard', methods=['GET'])
@login_required
def get_dashboard_data():
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
        
    # Gather dashboard stats
    # 1. Unread notifications
    unread_notifications_count = Notification.query.filter(
        or_(
            Notification.target_type == 'all',
            and_(Notification.target_type == 'specific', Notification.target_id == current_user.id)
        ),
        Notification.is_active == True,
        ~db.session.query(NotificationRead.id).filter(
            NotificationRead.notification_id == Notification.id,
            NotificationRead.company_id == current_user.id
        ).exists()
    ).count()

    # 2. Favorite products count
    favorites_count = FavoriteProduct.query.filter_by(company_id=current_user.id).count()

    # 3. Pending appointments
    pending_appointments = Appointment.query.filter_by(company_id=current_user.id, status='pending').count()

    # 4. Unread messages (Community/Private) - simplified logic
    # This might need adjustment based on exact logic in views.py
    
    return jsonify({
        'company_name': current_user.company_name,
        'unread_notifications': unread_notifications_count,
        'favorites_count': favorites_count,
        'pending_appointments': pending_appointments,
        'is_premium': current_user.is_premium,
        'premium_end_date': current_user.premium_end_date.isoformat() if current_user.premium_end_date else None
    })

@api_bp.route('/company/profile', methods=['GET'])
@login_required
def get_profile():
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    
    return jsonify({
        'id': current_user.id,
        'username': current_user.username,
        'company_name': current_user.company_name,
        'email': current_user.email,
        'phone': current_user.phone,
        'avatar': current_user.avatar,
        'is_active': current_user.is_active,
        'created_at': current_user.created_at.isoformat() if current_user.created_at else None
    })

@api_bp.route('/company/my_products', methods=['GET'])
@login_required
def get_my_products():
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
        
    favorites = FavoriteProduct.query.filter_by(company_id=current_user.id).order_by(FavoriteProduct.last_modified.desc()).all()
    
    products_data = []
    for fav in favorites:
        # Get latest stock info
        stock_record = ProductStockHistory.query.filter_by(product_name=fav.product_name)\
            .order_by(ProductStockHistory.record_date.desc(), ProductStockHistory.recorded_at.desc()).first()
            
        products_data.append({
            'id': fav.id,
            'product_name': fav.product_name,
            'quantity': fav.quantity, # This is the quantity the company "has" or "wants"? In FavoriteProduct it seems to be user defined.
            'current_stock': stock_record.quantity if stock_record else None,
            'price': stock_record.price if stock_record else fav.price,
            'notes': fav.notes,
            'last_modified': fav.last_modified.isoformat() if fav.last_modified else None
        })
        
    return jsonify(products_data)

@api_bp.route('/company/appointments', methods=['GET'])
@login_required
def get_appointments():
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
        
    appointments = Appointment.query.filter_by(company_id=current_user.id).order_by(Appointment.appointment_date.desc()).all()
    
    appointments_data = []
    for appt in appointments:
        appointments_data.append({
            'id': appt.id,
            'date': appt.appointment_date.isoformat(),
            'time': appt.appointment_time.strftime('%H:%M'),
            'purpose': appt.purpose,
            'product_item_name': appt.product_item_name,
            'status': appt.status,
            'admin_response': appt.admin_response,
            'created_at': appt.created_at.isoformat()
        })
        
    return jsonify(appointments_data)

@api_bp.route('/company/notifications', methods=['GET'])
@login_required
def get_notifications():
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
        
    # Fetch notifications targeted to all or specific to this company
    notifications = Notification.query.filter(
        or_(
            Notification.target_type == 'all',
            and_(Notification.target_type == 'specific', Notification.target_id == current_user.id)
        ),
        Notification.is_active == True
    ).order_by(Notification.created_at.desc()).limit(50).all()
    
    notif_data = []
    for notif in notifications:
        is_read = db.session.query(NotificationRead.id).filter(
            NotificationRead.notification_id == notif.id,
            NotificationRead.company_id == current_user.id
        ).first() is not None
        
        notif_data.append({
            'id': notif.id,
            'title': notif.title,
            'message': notif.message,
            'created_at': notif.created_at.isoformat(),
            'is_read': is_read
        })
        
    return jsonify(notif_data)

@api_bp.route('/company/mark_notification_read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403

    notification = Notification.query.get_or_404(notification_id)
    
    # Check if already read
    existing_read = NotificationRead.query.filter_by(
        notification_id=notification_id,
        company_id=current_user.id
    ).first()
    
    if not existing_read:
        new_read = NotificationRead(notification_id=notification_id, company_id=current_user.id)
        db.session.add(new_read)
        db.session.commit()
        
    return jsonify({'success': True})

@api_bp.route('/company/settings', methods=['GET', 'POST'])
@login_required
def company_settings():
    if session.get('user_type') != 'company':
        return jsonify({'error': 'Unauthorized'}), 403
    
    if request.method == 'POST':
        data = request.get_json()
        if not data:
             return jsonify({'success': False, 'message': 'No data provided'}), 400
             
        allow_messages = data.get('allow_messages_from_companies')
        if allow_messages is not None:
            # allow_messages should be boolean
            current_user.receive_messages_enabled = bool(allow_messages)
            try:
                db.session.commit()
                return jsonify({'success': True, 'message': 'Settings updated successfully'})
            except Exception as e:
                db.session.rollback()
                return jsonify({'success': False, 'message': str(e)}), 500
    
    # GET request
    system_subtitle_setting = SystemSetting.query.filter_by(setting_key='system_subtitle').first()
    system_subtitle = system_subtitle_setting.setting_value if system_subtitle_setting else 'نظام حجز المواعيد وإدارة الأرصدة المتكامل'
    
    current_logo_setting = SystemSetting.query.filter_by(setting_key='current_logo').first()
    current_logo_url = url_for('static', filename=f'logos/{current_logo_setting.setting_value}') if current_logo_setting and current_logo_setting.setting_value else None
    
    return jsonify({
        'receive_messages_enabled': current_user.receive_messages_enabled,
        'system_subtitle': system_subtitle,
        'current_logo_url': current_logo_url
    })


@api_bp.route('/integrations/erp/stock-sync', methods=['POST'])
def erp_stock_sync():
    expected_token = _get_erp_bridge_token()
    if not expected_token:
        return jsonify({
            'success': False,
            'message': 'ERP bridge token is not configured on the server.'
        }), 503

    if not _read_bridge_token_from_request(expected_token):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}

    warehouse_id = data.get('warehouse_id')
    try:
        warehouse_id = int(warehouse_id) if warehouse_id is not None else None
    except (TypeError, ValueError):
        return jsonify({
            'success': False,
            'message': 'warehouse_id must be an integer.'
        }), 400

    warehouse_name = str(data.get('warehouse_name') or data.get('warehouse') or '').strip()
    auto_create_warehouse = _parse_bool(data.get('auto_create_warehouse'), default=False)

    try:
        target_warehouse = _resolve_target_warehouse(
            warehouse_id=warehouse_id,
            warehouse_name=warehouse_name,
            auto_create=auto_create_warehouse
        )
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Warehouse resolve failed: {exc}'}), 500

    if not target_warehouse:
        return jsonify({'success': False, 'message': 'Warehouse not found.'}), 404

    if not target_warehouse.is_active:
        return jsonify({'success': False, 'message': 'Warehouse is inactive.'}), 400

    warehouse_id = target_warehouse.id

    # ── فلتر الفترة الزمنية ──────────────────────────────────────────────────
    # نستخدم رقم المخزن النهائي حتى يبقى كل مخزن له فترة قبول مستقلة.
    _wid_for_throttle = warehouse_id

    _should_process, _wait_minutes = _check_erp_bridge_throttle(_wid_for_throttle)
    if not _should_process:
        # الوقت المحدد لم ينقضِ — نرد بـ 200 OK حتى لا يتأثر برنامج الربط نهائياً
        return jsonify({
            'success': True,
            'skipped': True,
            'message': (
                f'Update received but skipped (throttled). '
                f'Next accepted in {_wait_minutes:.1f} min.'
            )
        }), 200
    # ─────────────────────────────────────────────────────────────────────────

    # ── حماية المعالجة المزدوجة ───────────────────────────────────────────────
    # إذا كان المخزن لا يزال يعالج تحديثاً سابقاً، نتجاهل التحديث الجديد
    # بصمت تام (200 OK) حتى لا يتأثر برنامج الربط نهائياً.
    try:
        _wh_check = Warehouse.query.get(warehouse_id)
        if _wh_check:
            # مهم: نظّف أي حالة عالقة أو مكتملة قبل منع التحديث الجديد.
            # بدون هذا التنظيف، قد يظل الجسر مرفوضاً حتى انتهاء مهلة الـ stale.
            _clear_stale_processing_if_needed(_wh_check)
            db.session.refresh(_wh_check)

        if _wh_check and _wh_check.is_processing:
            return jsonify({
                'success': True,
                'skipped': True,
                'message': (
                    f'Update received but skipped — warehouse is currently processing. '
                    f'Please wait until current processing finishes.'
                )
            }), 200
    except Exception:
        pass  # Non-fatal: proceed normally if check fails
    # ─────────────────────────────────────────────────────────────────────────

    items = data.get('items')
    if not isinstance(items, list):
        return jsonify({
            'success': False,
            'message': 'The request must include an items array.'
        }), 400

    full_sync = _parse_bool(data.get('full_sync'), default=True)

    try:
        # بعض بيئات الاستضافة (خصوصاً IIS/WSGI على ويندوز) قد لا تضمن استمرار Thread
        # بعد انتهاء الطلب، مما يؤدي إلى "نبض شغال" لكن الكميات لا تتحدّث فعلياً.
        #
        # لهذا ندعم وضعين:
        # - sync: تطبيق مباشر داخل الطلب (الأكثر موثوقية)
        # - background: قبول 202 وتشغيل في Thread
        requested_mode = str(data.get('sync_mode') or '').strip().lower()
        env_mode = str(os.environ.get('ERP_STOCK_SYNC_MODE') or '').strip().lower()
        sync_mode = requested_mode or env_mode or 'sync'

        if sync_mode in {'bg', 'background', 'async'}:
            result = _queue_erp_stock_snapshot(
                items=items,
                warehouse_id=warehouse_id,
                full_sync=full_sync
            )
            return jsonify({
                'success': True,
                'message': 'Stock snapshot accepted and started in the background.',
                'data': result
            }), 202

        # Default: synchronous apply
        result = _apply_erp_stock_snapshot(
            items=items,
            warehouse_id=warehouse_id,
            full_sync=full_sync,
            assume_processing=False
        )
        return jsonify({
            'success': True,
            'message': 'Stock snapshot applied successfully (sync mode).',
            'data': result
        }), 200
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(exc)}), 400
    except UploadCancelledError as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(exc)}), 409
    except RuntimeError as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(exc)}), 409
    except Exception as exc:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'Unexpected sync error: {exc}'
        }), 500


@api_bp.route('/integrations/erp/reset-processing-flag', methods=['POST'])
def erp_reset_processing_flag():
    """يسمح لبرنامج الربط بإعادة تعيين علامة المعالجة العالقة قسراً.
    يُستخدم عند تعطل السيرفر أو بقاء الحالة عالقة على 'cancelling'.
    """
    expected_token = _get_erp_bridge_token()
    if not expected_token:
        return jsonify({'success': False, 'message': 'ERP bridge token is not configured.'}), 503

    if not _read_bridge_token_from_request(expected_token):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    warehouse_id = data.get('warehouse_id')
    try:
        warehouse_id = int(warehouse_id) if warehouse_id is not None else None
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'warehouse_id must be an integer.'}), 400

    try:
        warehouse = _resolve_target_warehouse(warehouse_id)
        if not warehouse:
            return jsonify({'success': False, 'message': 'Warehouse not found.'}), 404

        old_status = warehouse.last_process_status
        old_processing = warehouse.is_processing

        clear_upload_cancel(warehouse.id)
        warehouse.is_processing = False
        warehouse.last_process_status = 'error'
        warehouse.last_process_error = 'Processing flag reset by ERP bridge (force reset).'
        warehouse.last_process_time = datetime.utcnow()
        db.session.commit()

        current_app.logger.warning(
            'ERP bridge force-reset warehouse %s: was_processing=%s, old_status=%s',
            warehouse.id, old_processing, old_status
        )
        return jsonify({
            'success': True,
            'message': 'Processing flag reset successfully.',
            'warehouse_id': warehouse.id,
            'was_processing': old_processing,
            'old_status': old_status
        }), 200
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Reset failed: {exc}'}), 500


@api_bp.route('/integrations/erp/sync-status', methods=['POST'])
def erp_sync_status():
    expected_token = _get_erp_bridge_token()
    if not expected_token:
        return jsonify({'success': False, 'message': 'ERP bridge token is not configured.'}), 503

    if not _read_bridge_token_from_request(expected_token):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    warehouse_id = data.get('warehouse_id')
    try:
        warehouse_id = int(warehouse_id) if warehouse_id is not None else None
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'warehouse_id must be an integer.'}), 400

    try:
        warehouse = _resolve_target_warehouse(warehouse_id)
        if not warehouse:
            return jsonify({'success': False, 'message': 'Warehouse not found.'}), 404

        if _clear_stale_processing_if_needed(warehouse):
            warehouse = Warehouse.query.get(warehouse.id)

        payload = {
            'warehouse_id': warehouse.id,
            'warehouse_name': warehouse.name,
            'is_processing': bool(warehouse.is_processing),
            'last_process_status': str(warehouse.last_process_status or ''),
            'last_process_error': str(warehouse.last_process_error or ''),
            'last_process_time_utc': (
                warehouse.last_process_time.isoformat() + 'Z'
                if warehouse.last_process_time else ''
            ),
            'last_process_added': int(warehouse.last_process_added or 0),
            'last_process_updated': int(warehouse.last_process_updated or 0),
            'last_process_reset': int(warehouse.last_process_reset or 0),
            'last_process_data_rows': int(warehouse.last_process_data_rows or 0),
        }
        return jsonify({
            'success': True,
            'message': 'ERP sync status fetched successfully.',
            'data': payload
        }), 200
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Status lookup failed: {exc}'}), 500


@api_bp.route('/integrations/erp/bridge-heartbeat', methods=['POST'])
def erp_bridge_heartbeat():
    try:
        expected_token = _get_erp_bridge_token()
        if not expected_token:
            return jsonify({
                'success': False,
                'message': 'ERP bridge token is not configured on the server.'
            }), 503

        if not _read_bridge_token_from_request(expected_token):
            return jsonify({'success': False, 'message': 'Unauthorized'}), 401

        data = request.get_json(silent=True) or {}
        heartbeat_warehouse_id = data.get('warehouse_id')
        try:
            heartbeat_warehouse_id = int(heartbeat_warehouse_id) if heartbeat_warehouse_id not in (None, '') else None
        except (TypeError, ValueError):
            heartbeat_warehouse_id = None

        heartbeat_warehouse_name = str(data.get('warehouse_name') or data.get('warehouse') or '').strip()
        resolved_warehouse = _resolve_target_warehouse(
            warehouse_id=heartbeat_warehouse_id,
            warehouse_name=heartbeat_warehouse_name,
            auto_create=False
        )
        if resolved_warehouse:
            heartbeat_warehouse_id = resolved_warehouse.id
            heartbeat_warehouse_name = resolved_warehouse.name

        heartbeat = {
            'status': str(data.get('status') or '').strip() or 'unknown',
            'message': str(data.get('message') or '').strip()[:500],
            'machine_name': str(data.get('machine_name') or '').strip()[:100],
            'warehouse_id': heartbeat_warehouse_id,
            'warehouse_name': heartbeat_warehouse_name,
            'interval_minutes': data.get('interval_minutes'),
            'last_success_utc': str(data.get('last_success_utc') or '').strip(),
            'last_failure_utc': str(data.get('last_failure_utc') or '').strip(),
            'last_error': str(data.get('last_error') or '').strip()[:500],
            'next_run_utc': str(data.get('next_run_utc') or '').strip(),
            'updated_at_utc': datetime.utcnow().isoformat() + 'Z'
        }

        try:
            runtime_status = _get_bridge_runtime_status()
            if not isinstance(runtime_status, dict):
                runtime_status = {}

            warehouse_statuses = runtime_status.get('warehouses')
            if not isinstance(warehouse_statuses, dict):
                warehouse_statuses = {}

            if heartbeat_warehouse_id:
                warehouse_statuses[str(heartbeat_warehouse_id)] = heartbeat

            runtime_status.update(heartbeat)
            runtime_status['warehouses'] = warehouse_statuses

            _save_bridge_runtime_status(runtime_status)
            return jsonify({
                'success': True,
                'message': 'Bridge heartbeat saved successfully.',
                'data': heartbeat
            }), 200
        except OperationalError as exc:
            db.session.rollback()
            if _is_sqlite_lock_error(exc):
                return jsonify({
                    'success': True,
                    'message': 'Bridge heartbeat skipped because the database was busy.',
                    'data': heartbeat
                }), 200
            raise
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Unexpected ERP bridge heartbeat failure")
        return jsonify({
            'success': False,
            'message': f'Unexpected heartbeat error: {exc}'
        }), 500

@api_bp.route('/company/book_appointment', methods=['POST'])
@login_required
def book_appointment():
    if session.get('user_type') != 'company':
        return jsonify({'success': False, 'message': 'غير مصرح لك بحجز المواعيد.'}), 403

    maintenance_mode_setting = SystemSetting.query.filter_by(setting_key='maintenance_mode').first()
    if maintenance_mode_setting and maintenance_mode_setting.setting_value == 'true':
        allow_company_during_maintenance = session.get('allow_company_login_during_maintenance', False)
        is_admin_testing = session.get('is_admin_logged', False)
        is_company_test_mode_session = session.get('company_test_mode', False)
        if not (allow_company_during_maintenance or is_admin_testing or is_company_test_mode_session):
            return jsonify({'success': False, 'message': 'الموقع قيد الصيانة حالياً. لا يمكن حجز المواعيد.'}), 503

    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400

        appointment_date_str = data.get('appointment_date')
        appointment_time_str = data.get('appointment_time')
        purpose = data.get('purpose', '').strip()
        product_item_name = data.get('product_item_name', '').strip()
        phone_number = data.get('phone_number', '').strip()
        notes = data.get('notes', '').strip()
        collection_amount_str = str(data.get('collection_amount', '')).strip() # Ensure string for strip

        if not all([appointment_date_str, appointment_time_str, purpose, product_item_name, phone_number]):
            return jsonify({'success': False, 'message': 'يرجى تزويد جميع المعلومات المطلوبة (التاريخ، الوقت، الغرض، الصنف، رقم الموبايل).'}), 400

        appointment_date = datetime.strptime(appointment_date_str, '%Y-%m-%d').date()
        appointment_time = datetime.strptime(appointment_time_str, '%H:%M').time()
        
        collection_amount = None
        if collection_amount_str and collection_amount_str.lower() != 'none' and collection_amount_str != '':
             try:
                 collection_amount = float(collection_amount_str)
             except ValueError:
                 pass

        if appointment_date < date.today():
            return jsonify({'success': False, 'message': 'لا يمكن حجز موعد في تاريخ ماضٍ.'}), 400

        min_time = time(10, 0)
        max_time = time(16, 0)
        if not (min_time <= appointment_time <= max_time):
            return jsonify({'success': False, 'message': 'المواعيد متاحة فقط من الساعة 10:00 صباحاً حتى 04:00 عصراً.'}), 400

        disabled_days_setting = SystemSetting.query.filter_by(setting_key='disabled_days').first()
        disabled_days_list = []
        if disabled_days_setting and disabled_days_setting.setting_value:
            try:
                disabled_days_list = json.loads(disabled_days_setting.setting_value)
            except json.JSONDecodeError:
                disabled_days_list = []
        if str(appointment_date.weekday()) in disabled_days_list:
            disabled_days_message_setting = SystemSetting.query.filter_by(setting_key='disabled_days_message').first()
            disabled_days_message = disabled_days_message_setting.setting_value if disabled_days_message_setting else 'عذراً، هذا اليوم معطل لتلقي الطلبات.'
            return jsonify({'success': False, 'message': disabled_days_message}), 400

        max_daily_requests_setting = SystemSetting.query.filter_by(setting_key='max_daily_requests').first()
        max_daily_requests = int(max_daily_requests_setting.setting_value) if max_daily_requests_setting and max_daily_requests_setting.setting_value.isdigit() else 10

        today_appointments_count = Appointment.query.filter(
            Appointment.appointment_date == date.today(),
            Appointment.status != 'rejected'
        ).count()
        if today_appointments_count >= max_daily_requests:
            return jsonify({'success': False, 'message': f'عذراً، لقد تم الوصول للحد الأقصى من طلبات المواعيد لهذا اليوم ({max_daily_requests} موعد). يرجى المحاولة في يوم آخر.'}), 400

        if not phone_number.startswith('01') or len(phone_number) != 11 or not phone_number.isdigit():
            return jsonify({'success': False, 'message': 'يرجى إدخال رقم موبايل صحيح مكون من 11 رقم ويبدأ بـ 01.'}), 400

        new_appointment = Appointment(
            company_id=current_user.id,
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            purpose=purpose,
            product_item_name=product_item_name,
            notes=notes if notes else None,
            collection_amount=collection_amount,
            status='pending',
            created_at=datetime.utcnow()
        )
        db.session.add(new_appointment)
        db.session.commit()

        admin_notification = Notification(
            title=f'طلب موعد جديد من {current_user.company_name} عبر توبي',
            message=f'الشركة {current_user.company_name} طلبت موعداً بتاريخ {appointment_date_str} الساعة {appointment_time_str} لغرض: {purpose}. الصنف: {product_item_name}.',
            target_type='all',
            created_by=None, # Assuming this is accepted by DB as per views.py usage
            created_at=datetime.utcnow()
        )
        db.session.add(admin_notification)
        db.session.commit()

        return jsonify({'success': True, 'message': 'تم إرسال طلب الموعد بنجاح. سيتم مراجعته من قبل الإدارة قريباً.'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ داخلي أثناء حجز الموعد: {str(e)}'}), 500

@api_bp.route('/admin/current_invite_code_legacy', methods=['GET']) # تم نقله إلى views.py
@login_required
def get_current_invite_code_legacy():
    if session.get('user_type') != 'admin':
        return jsonify({'success': False, 'message': 'غير مصرح'}), 403
    
    setting = SystemSetting.query.filter_by(setting_key='invite_code').first()
    invite_code = (setting.setting_value if setting else '') or ''
    return jsonify({'success': True, 'invite_code': invite_code})


# ─── Public read-only endpoint (no auth) — for desktop HTA viewer ───
# This endpoint only READS the current invite code, no modifications possible.
@api_bp.route('/public/invite_code', methods=['GET'])
def get_public_invite_code():
    """يُرجع كود الدعوة الحالي للقراءة فقط — لا يتطلب تسجيل دخول."""
    setting = SystemSetting.query.filter_by(setting_key='invite_code').first()
    invite_code = (setting.setting_value if setting else '') or ''
    if not invite_code:
        return jsonify({'success': False, 'message': 'لم يتم تعيين كود دعوة بعد'})
    return jsonify({'success': True, 'invite_code': invite_code})
