from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest

import pytz

from company_activity import CAIRO_TIMEZONE, company_activity_snapshot


UTC = pytz.utc


class CompanyActivitySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.now = CAIRO_TIMEZONE.localize(datetime(2026, 8, 14, 12, 0, 0))

    def company(self, *, last_login=None, last_client_seen_at=None, created_at=None):
        return SimpleNamespace(
            last_login=last_login,
            last_client_seen_at=last_client_seen_at,
            created_at=created_at,
        )

    def test_account_creation_is_not_activity(self):
        snapshot = company_activity_snapshot(
            self.company(created_at=datetime(2026, 8, 14, 9, 0, 0)),
            now=self.now,
        )

        self.assertIsNone(snapshot.timestamp)
        self.assertTrue(snapshot.is_inactive)
        self.assertFalse(snapshot.is_today)

    def test_successful_login_is_active_today(self):
        snapshot = company_activity_snapshot(
            self.company(last_login=datetime(2026, 8, 14, 8, 30, 0)),
            now=self.now,
        )

        self.assertTrue(snapshot.is_today)
        self.assertTrue(snapshot.is_in_last_7_days)
        self.assertEqual(snapshot.source, 'تسجيل دخول ناجح')

    def test_newer_authenticated_use_supersedes_login(self):
        snapshot = company_activity_snapshot(
            self.company(
                last_login=datetime(2026, 8, 12, 8, 30, 0),
                last_client_seen_at=datetime(2026, 8, 14, 8, 30, 0),
            ),
            now=self.now,
        )

        self.assertTrue(snapshot.is_today)
        self.assertEqual(snapshot.source, 'استخدام مصادق عليه للمنصة')
        self.assertEqual(snapshot.timestamp, CAIRO_TIMEZONE.localize(datetime(2026, 8, 14, 11, 30, 0)))

    def test_seven_day_window_includes_today_and_excludes_stale_activity(self):
        within_window = company_activity_snapshot(
            self.company(last_login=datetime(2026, 8, 8, 10, 0, 0)),
            now=self.now,
        )
        stale = company_activity_snapshot(
            self.company(last_login=datetime(2026, 8, 6, 10, 0, 0)),
            now=self.now,
        )

        self.assertTrue(within_window.is_in_last_7_days)
        self.assertFalse(within_window.is_inactive)
        self.assertFalse(stale.is_in_last_7_days)
        self.assertTrue(stale.is_inactive)

    def test_future_timestamp_is_reported_but_never_counted_as_active(self):
        future_utc = self.now.astimezone(UTC).replace(tzinfo=None) + timedelta(minutes=1)
        snapshot = company_activity_snapshot(
            self.company(last_login=future_utc),
            now=self.now,
        )

        self.assertTrue(snapshot.has_invalid_timestamp)
        self.assertFalse(snapshot.is_today)
        self.assertFalse(snapshot.is_in_last_7_days)

    def test_recent_presence_marks_company_online(self):
        snapshot = company_activity_snapshot(
            self.company(last_login=datetime(2026, 8, 14, 8, 59, 0)),
            now=self.now,
        )

        self.assertTrue(snapshot.is_online)

    def test_stale_presence_does_not_mark_company_online(self):
        snapshot = company_activity_snapshot(
            self.company(last_login=datetime(2026, 8, 14, 8, 57, 0)),
            now=self.now,
        )

        self.assertFalse(snapshot.is_online)

    def test_mobile_activity_after_login_is_the_latest_appearance(self):
        company = self.company(last_login=datetime(2026, 8, 10, 9, 0, 0))
        company.last_active = datetime(2026, 8, 14, 8, 59, 0)

        snapshot = company_activity_snapshot(company, now=self.now)

        self.assertEqual(snapshot.source, 'استخدام تطبيق الهاتف')
        self.assertTrue(snapshot.is_online)


if __name__ == '__main__':
    unittest.main()
