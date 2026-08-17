"""Canonical, display-ready company activity calculations.

The activity report must not infer activity from account creation.  A company
is considered active only when there is evidence of either a successful login
or a later authenticated use of the platform.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pytz


CAIRO_TIMEZONE = pytz.timezone('Africa/Cairo')
ONLINE_WINDOW = timedelta(minutes=2)


@dataclass(frozen=True)
class CompanyActivitySnapshot:
    """The single activity definition consumed by the admin report."""

    timestamp: Optional[datetime]
    formatted_timestamp: Optional[str]
    source: Optional[str]
    time_ago: Optional[str]
    css_class: str
    is_today: bool
    is_in_last_7_days: bool
    is_inactive: bool
    has_invalid_timestamp: bool
    is_online: bool


def _to_cairo(value: Optional[datetime]) -> Optional[datetime]:
    """Treat legacy naive database timestamps as UTC, then convert to Cairo."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = pytz.utc.localize(value)
    return value.astimezone(CAIRO_TIMEZONE)


def _humanize_elapsed(delta: timedelta) -> str:
    total_seconds = max(0, int(delta.total_seconds()))
    if total_seconds < 60:
        return 'الآن'

    minutes = total_seconds // 60
    if minutes < 60:
        return 'منذ دقيقة واحدة' if minutes == 1 else f'منذ {minutes} دقيقة'

    hours = minutes // 60
    if hours < 24:
        return 'منذ ساعة واحدة' if hours == 1 else f'منذ {hours} ساعة'

    days = hours // 24
    if days < 30:
        return 'منذ يوم واحد' if days == 1 else f'منذ {days} يوم'

    months = days // 30
    if months < 12:
        return 'منذ شهر واحد' if months == 1 else f'منذ {months} شهر'

    years = days // 365
    return 'منذ سنة واحدة' if years == 1 else f'منذ {years} سنة'


def company_activity_snapshot(company, now: Optional[datetime] = None) -> CompanyActivitySnapshot:
    """Return the latest verified activity and its reporting classification.

    ``last_login`` is the authoritative authentication event.  When the user
    stays signed in, client-presence signals record a newer, authenticated use
    and therefore supersede it.  ``created_at`` is deliberately excluded.
    """
    now_cairo = _to_cairo(now) if now else datetime.now(CAIRO_TIMEZONE)
    if now_cairo is None:
        now_cairo = datetime.now(CAIRO_TIMEZONE)

    login_at = _to_cairo(getattr(company, 'last_login', None))
    client_seen_at = _to_cairo(getattr(company, 'last_client_seen_at', None))
    mobile_active_at = _to_cairo(getattr(company, 'last_active', None))

    candidates = []
    if login_at:
        candidates.append((login_at, 'تسجيل دخول ناجح'))
    if client_seen_at:
        candidates.append((client_seen_at, 'استخدام مصادق عليه للمنصة'))
    # ``last_active`` existed before presence tracking and has a creation-time
    # default in some legacy records.  It is reliable only after a known login.
    if mobile_active_at and login_at and mobile_active_at >= login_at:
        candidates.append((mobile_active_at, 'استخدام تطبيق الهاتف'))

    timestamp, source = max(candidates, key=lambda item: item[0]) if candidates else (None, None)

    if timestamp is None:
        return CompanyActivitySnapshot(
            timestamp=None,
            formatted_timestamp=None,
            source=None,
            time_ago=None,
            css_class='time-old',
            is_today=False,
            is_in_last_7_days=False,
            is_inactive=True,
            has_invalid_timestamp=False,
            is_online=False,
        )

    # Future timestamps are data errors.  Surface them without counting them as
    # recent activity, so they cannot silently inflate the report.
    if timestamp > now_cairo:
        return CompanyActivitySnapshot(
            timestamp=timestamp,
            formatted_timestamp=timestamp.strftime('%Y-%m-%d %I:%M %p'),
            source=source,
            time_ago='تاريخ غير صالح',
            css_class='time-old',
            is_today=False,
            is_in_last_7_days=False,
            is_inactive=False,
            has_invalid_timestamp=True,
            is_online=False,
        )

    today_start = now_cairo.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now_cairo - timedelta(days=7)
    is_today = timestamp >= today_start
    is_in_last_7_days = timestamp >= seven_days_ago

    return CompanyActivitySnapshot(
        timestamp=timestamp,
        formatted_timestamp=timestamp.strftime('%Y-%m-%d %I:%M %p'),
        source=source,
        time_ago=_humanize_elapsed(now_cairo - timestamp),
        css_class='time-recent' if is_today else ('time-week' if is_in_last_7_days else 'time-old'),
        is_today=is_today,
        is_in_last_7_days=is_in_last_7_days,
        is_inactive=not is_in_last_7_days,
        has_invalid_timestamp=False,
        is_online=timestamp >= now_cairo - ONLINE_WINDOW,
    )
