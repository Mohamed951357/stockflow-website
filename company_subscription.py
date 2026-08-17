"""One authoritative definition of a company's effective subscription state."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class CompanySubscriptionSnapshot:
    state: str
    label: str
    css_class: str
    is_active: bool
    should_deactivate_premium: bool
    should_deactivate_trial: bool


def company_subscription_snapshot(company, now: Optional[datetime] = None) -> CompanySubscriptionSnapshot:
    """Calculate the subscription shown to admins and granted to the company.

    ``is_premium`` alone is not sufficient: it can remain True after a plan or
    trial has expired.  An end timestamp is authoritative whenever it exists;
    a missing end timestamp represents an intentionally permanent plan.
    """
    now = now or datetime.utcnow()
    is_premium = bool(getattr(company, 'is_premium', False))
    plan = (getattr(company, 'subscription_plan', '') or '').strip().lower()
    end_at = getattr(company, 'premium_end_date', None)
    trial_active = bool(getattr(company, 'premium_trial_active', False))
    trial_end_at = getattr(company, 'premium_trial_end', None)
    is_trial = (
        plan == 'trial'
        or trial_active
        or (
            plan in {'', 'standard', 'free'}
            and trial_end_at is not None
        )
    )
    is_expired = bool(end_at and end_at <= now)
    trial_expired = bool(trial_active and trial_end_at and trial_end_at <= now)

    should_deactivate_premium = is_premium and is_expired
    should_deactivate_trial = trial_expired

    if is_premium and not is_expired:
        if is_trial:
            return CompanySubscriptionSnapshot(
                state='trial',
                label='تجربة بريميوم',
                css_class='trial',
                is_active=True,
                should_deactivate_premium=False,
                should_deactivate_trial=should_deactivate_trial,
            )
        return CompanySubscriptionSnapshot(
            state='premium',
            label='بريميوم',
            css_class='premium',
            is_active=True,
            should_deactivate_premium=False,
            should_deactivate_trial=should_deactivate_trial,
        )

    if is_expired or trial_expired:
        return CompanySubscriptionSnapshot(
            state='expired_trial' if is_trial else 'expired',
            label='تجربة منتهية' if is_trial else 'بريميوم منتهٍ',
            css_class='expired',
            is_active=False,
            should_deactivate_premium=should_deactivate_premium,
            should_deactivate_trial=should_deactivate_trial,
        )

    return CompanySubscriptionSnapshot(
        state='regular',
        label='عادي',
        css_class='regular',
        is_active=False,
        should_deactivate_premium=False,
        should_deactivate_trial=False,
    )


def deactivate_expired_subscription(company, now: Optional[datetime] = None) -> bool:
    """Persist only stale expiry flags; historical dates are retained for audit."""
    snapshot = company_subscription_snapshot(company, now=now)
    changed = False
    if snapshot.should_deactivate_premium and getattr(company, 'is_premium', False):
        company.is_premium = False
        changed = True
    if snapshot.should_deactivate_trial and getattr(company, 'premium_trial_active', False):
        company.premium_trial_active = False
        changed = True
    return changed


def deactivate_all_expired_subscriptions(db_session, now: Optional[datetime] = None) -> int:
    """Deactivate expired subscriptions for all companies in the database."""
    try:
        from models import Company
        now = now or datetime.utcnow()
        companies = Company.query.filter(
            (Company.is_premium == True) | (Company.premium_trial_active == True)
        ).all()
        count = 0
        for comp in companies:
            if deactivate_expired_subscription(comp, now=now):
                count += 1
        if count > 0:
            try:
                db_session.commit()
            except Exception:
                db_session.rollback()
        return count
    except Exception:
        return 0

