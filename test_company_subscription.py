from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest

from company_subscription import (
    company_subscription_snapshot,
    deactivate_expired_subscription,
)


class CompanySubscriptionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 14, 12, 0, 0)

    def company(self, **kwargs):
        defaults = {
            'is_premium': False,
            'subscription_plan': 'standard',
            'premium_end_date': None,
            'premium_trial_active': False,
            'premium_trial_end': None,
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_current_paid_subscription_is_premium(self):
        snapshot = company_subscription_snapshot(self.company(
            is_premium=True,
            subscription_plan='premium',
            premium_end_date=self.now + timedelta(days=1),
        ), now=self.now)

        self.assertTrue(snapshot.is_active)
        self.assertEqual(snapshot.label, 'بريميوم')

    def test_expired_paid_subscription_is_not_premium_and_is_normalized(self):
        company = self.company(
            is_premium=True,
            subscription_plan='premium',
            premium_end_date=self.now - timedelta(seconds=1),
        )
        snapshot = company_subscription_snapshot(company, now=self.now)

        self.assertFalse(snapshot.is_active)
        self.assertEqual(snapshot.label, 'بريميوم منتهٍ')
        self.assertTrue(deactivate_expired_subscription(company, now=self.now))
        self.assertFalse(company.is_premium)

    def test_expired_trial_is_never_displayed_as_active_premium(self):
        company = self.company(
            is_premium=False,
            subscription_plan='trial',
            premium_end_date=self.now - timedelta(days=1),
            premium_trial_active=True,
            premium_trial_end=self.now - timedelta(days=1),
        )
        snapshot = company_subscription_snapshot(company, now=self.now)

        self.assertFalse(snapshot.is_active)
        self.assertEqual(snapshot.label, 'تجربة منتهية')
        self.assertTrue(deactivate_expired_subscription(company, now=self.now))
        self.assertFalse(company.premium_trial_active)

    def test_permanent_premium_without_end_date_stays_active(self):
        snapshot = company_subscription_snapshot(self.company(is_premium=True), now=self.now)

        self.assertTrue(snapshot.is_active)
        self.assertEqual(snapshot.label, 'بريميوم')

    def test_company_model_is_verified_and_is_premium_active(self):
        from models import Company

        # Active premium company
        active_comp = Company(
            company_name='Test Pharma',
            is_premium=True,
            premium_end_date=datetime.utcnow() + timedelta(days=30),
        )
        self.assertTrue(active_comp.is_premium_active)
        self.assertTrue(active_comp.is_verified)

        # Expired premium company - MUST NOT BE VERIFIED
        expired_comp = Company(
            company_name='Expired Pharma',
            is_premium=True,
            premium_end_date=datetime.utcnow() - timedelta(days=5),
        )
        self.assertFalse(expired_comp.is_premium_active)
        self.assertFalse(expired_comp.is_verified)

        # Expired trial company - MUST NOT BE VERIFIED
        expired_trial = Company(
            company_name='Trial Pharma',
            is_premium=False,
            premium_trial_active=True,
            premium_trial_end=datetime.utcnow() - timedelta(days=1),
        )
        self.assertFalse(expired_trial.is_premium_active)
        self.assertFalse(expired_trial.is_verified)

        # Regular unpaid company
        regular_comp = Company(
            company_name='Regular Pharma',
            is_premium=False,
        )
        self.assertFalse(regular_comp.is_premium_active)
        self.assertFalse(regular_comp.is_verified)

        # Official STOCK FLOW account is always verified
        official_comp = Company(
            company_name='STOCK FLOW',
            is_premium=False,
        )
        self.assertTrue(official_comp.is_verified)


if __name__ == '__main__':
    unittest.main()
