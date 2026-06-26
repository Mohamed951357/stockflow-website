from threading import Lock
from time import monotonic

from flask import current_app
from sqlalchemy import text


_UPLOAD_CONTROL_STATE_KEY = 'warehouse_upload_control_state'
_DB_CANCEL_CACHE_TTL_SECONDS = 1.0
_DB_CANCELLED_STATUSES = {'cancelling', 'cancel_requested'}


class UploadCancelledError(RuntimeError):
    pass


def _get_state():
    state = current_app.extensions.get(_UPLOAD_CONTROL_STATE_KEY)
    if state is None:
        state = {
            'cancel_requested': set(),
            'db_cancel_cache': {},
            'lock': Lock(),
        }
        current_app.extensions[_UPLOAD_CONTROL_STATE_KEY] = state
    return state


def _is_upload_cancel_requested_in_db(warehouse_id):
    try:
        from models import db

        with db.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT is_processing, last_process_status
                    FROM warehouse
                    WHERE id = :warehouse_id
                    """
                ),
                {'warehouse_id': int(warehouse_id)}
            ).mappings().first()
    except Exception:
        try:
            current_app.logger.exception(
                'Failed to read upload cancellation state from database for warehouse %s',
                warehouse_id
            )
        except Exception:
            pass
        return False

    if not row:
        return False

    # مهم: لا نعتبر "cancelling/cancel_requested" سبباً لإلغاء الرفع
    # إلا إذا كانت هناك عملية معالجة جارية فعلاً.
    #
    # السبب: قد تبقى last_process_status على cancelling بسبب توقف/كراش قديم
    # بينما is_processing=False. في هذه الحالة يجب أن يسمح الموقع ببدء مزامنة جديدة.
    try:
        is_processing = bool(row.get('is_processing'))
    except Exception:
        is_processing = False
    if not is_processing:
        return False

    status = str(row.get('last_process_status') or '').strip().lower()
    return status in _DB_CANCELLED_STATUSES


def request_upload_cancel(warehouse_id):
    if warehouse_id is None:
        return

    state = _get_state()
    with state['lock']:
        state['cancel_requested'].add(int(warehouse_id))
        state['db_cancel_cache'].pop(int(warehouse_id), None)


def clear_upload_cancel(warehouse_id):
    if warehouse_id is None:
        return

    state = _get_state()
    with state['lock']:
        state['cancel_requested'].discard(int(warehouse_id))
        state['db_cancel_cache'].pop(int(warehouse_id), None)


def is_upload_cancel_requested(warehouse_id):
    if warehouse_id is None:
        return False

    state = _get_state()
    with state['lock']:
        warehouse_id = int(warehouse_id)
        if warehouse_id in state['cancel_requested']:
            return True

        cached_entry = state['db_cancel_cache'].get(warehouse_id)
        now = monotonic()
        if cached_entry and (now - cached_entry['checked_at']) < _DB_CANCEL_CACHE_TTL_SECONDS:
            return cached_entry['is_cancel_requested']

    is_cancel_requested = _is_upload_cancel_requested_in_db(warehouse_id)

    with state['lock']:
        state['db_cancel_cache'][warehouse_id] = {
            'checked_at': monotonic(),
            'is_cancel_requested': is_cancel_requested,
        }

    return is_cancel_requested
