"""
tests/unit/test_plan_limits.py

Unit tests for Plan.LIMITS constants and UserProfile plan-derived properties.
No DB required for pure constant checks; Django TestCase used for profile tests.
"""

import pytest
from django.test import TestCase
from django.contrib.auth.models import User

from core.models import Plan, UserProfile


# ── Plan.LIMITS completeness ──────────────────────────────────────────────────

class TestPlanLimitsSchema(TestCase):
    """
    Every plan must define every field — no silent KeyError at runtime.
    Tests go through Plan.get() so DB changes are visible.
    Rows are seeded from Plan.LIMITS in setUp() (same as migration 0006/0007).
    """

    REQUIRED_FIELDS = [
        "label", "price_monthly", "max_file_mb", "max_text_kb",
        "max_expiry_days", "clipboard_idle_hours", "clipboard_max_lifetime_days",
        "anon_file_lifetime_days",
        "storage_gb", "renewals", "password_protection", "max_collections",
        "max_groups", "webhooks", "api_keys", "scheduled_drops",
    ]

    def setUp(self):
        from core.models import PlanLimit
        for plan_key, data in Plan.LIMITS.items():
            PlanLimit.objects.update_or_create(plan=plan_key, defaults=data)
        PlanLimit.invalidate_cache()

    def _check_plan(self, plan_key):
        for field in self.REQUIRED_FIELDS:
            # Plan.get() must not raise — it should return a value (possibly None)
            try:
                Plan.get(plan_key, field)
            except Exception as e:
                self.fail(f"{plan_key} field '{field}' raised via Plan.get(): {e}")

    def test_anon_has_all_fields(self):
        self._check_plan(Plan.ANON)

    def test_free_has_all_fields(self):
        self._check_plan(Plan.FREE)

    def test_starter_has_all_fields(self):
        self._check_plan(Plan.STARTER)

    def test_pro_has_all_fields(self):
        self._check_plan(Plan.PRO)

    def test_anon_file_lifetime_is_90(self):
        self.assertEqual(Plan.get(Plan.ANON, "anon_file_lifetime_days"), 90)

    def test_free_file_lifetime_is_90(self):
        self.assertEqual(Plan.get(Plan.FREE, "anon_file_lifetime_days"), 90)

    def test_paid_file_lifetime_is_none(self):
        self.assertIsNone(Plan.get(Plan.STARTER, "anon_file_lifetime_days"))
        self.assertIsNone(Plan.get(Plan.PRO, "anon_file_lifetime_days"))


# ── File / text size limits ───────────────────────────────────────────────────

class TestPlanFileLimits(TestCase):
    def test_anon_free_same_file_limit(self):
        self.assertEqual(Plan.get(Plan.ANON, "max_file_mb"), Plan.get(Plan.FREE, "max_file_mb"))

    def test_starter_larger_than_free(self):
        self.assertGreater(Plan.get(Plan.STARTER, "max_file_mb"), Plan.get(Plan.FREE, "max_file_mb"))

    def test_pro_larger_than_starter(self):
        self.assertGreater(Plan.get(Plan.PRO, "max_file_mb"), Plan.get(Plan.STARTER, "max_file_mb"))

    def test_pro_file_limit_is_5gb(self):
        self.assertEqual(Plan.get(Plan.PRO, "max_file_mb"), 5120)

    def test_starter_file_limit_is_1gb(self):
        self.assertEqual(Plan.get(Plan.STARTER, "max_file_mb"), 1024)

    def test_free_file_limit_is_200mb(self):
        self.assertEqual(Plan.get(Plan.FREE, "max_file_mb"), 200)

    def test_pro_text_limit_is_10mb(self):
        self.assertEqual(Plan.get(Plan.PRO, "max_text_kb"), 10240)


# ── Expiry rules ──────────────────────────────────────────────────────────────

class TestPlanExpiry(TestCase):
    def test_anon_no_custom_expiry(self):
        self.assertIsNone(Plan.get(Plan.ANON, "max_expiry_days"))

    def test_free_no_custom_expiry(self):
        self.assertIsNone(Plan.get(Plan.FREE, "max_expiry_days"))

    def test_starter_can_set_custom_expiry(self):
        self.assertIsNotNone(Plan.get(Plan.STARTER, "max_expiry_days"))

    def test_starter_max_expiry_is_1_year(self):
        self.assertEqual(Plan.get(Plan.STARTER, "max_expiry_days"), 365)

    def test_pro_max_expiry_is_3_years(self):
        self.assertEqual(Plan.get(Plan.PRO, "max_expiry_days"), 365 * 3)

    def test_pro_longer_expiry_than_starter(self):
        self.assertGreater(
            Plan.get(Plan.PRO, "max_expiry_days"),
            Plan.get(Plan.STARTER, "max_expiry_days"),
        )

    def test_anon_clipboard_max_lifetime_7_days(self):
        self.assertEqual(Plan.get(Plan.ANON, "clipboard_max_lifetime_days"), 7)

    def test_free_clipboard_max_lifetime_30_days(self):
        self.assertEqual(Plan.get(Plan.FREE, "clipboard_max_lifetime_days"), 30)

    def test_paid_plans_no_clipboard_ceiling(self):
        # Paid plans use explicit expiry — no automatic ceiling
        self.assertIsNone(Plan.get(Plan.STARTER, "clipboard_max_lifetime_days"))
        self.assertIsNone(Plan.get(Plan.PRO, "clipboard_max_lifetime_days"))

    def test_free_idle_hours_48(self):
        self.assertEqual(Plan.get(Plan.FREE, "clipboard_idle_hours"), 48)

    def test_anon_idle_hours_24(self):
        self.assertEqual(Plan.get(Plan.ANON, "clipboard_idle_hours"), 24)


# ── Storage quota ─────────────────────────────────────────────────────────────

class TestPlanStorage(TestCase):
    def test_anon_no_storage(self):
        self.assertIsNone(Plan.get(Plan.ANON, "storage_gb"))

    def test_free_no_storage(self):
        self.assertIsNone(Plan.get(Plan.FREE, "storage_gb"))

    def test_starter_storage_5gb(self):
        self.assertEqual(Plan.get(Plan.STARTER, "storage_gb"), 5)

    def test_pro_storage_20gb(self):
        self.assertEqual(Plan.get(Plan.PRO, "storage_gb"), 20)


# ── Password protection flag ──────────────────────────────────────────────────

class TestPlanPasswordProtection(TestCase):
    def test_anon_no_password_protection(self):
        self.assertFalse(Plan.get(Plan.ANON, "password_protection"))

    def test_free_no_password_protection(self):
        self.assertFalse(Plan.get(Plan.FREE, "password_protection"))

    def test_starter_has_password_protection(self):
        self.assertTrue(Plan.get(Plan.STARTER, "password_protection"))

    def test_pro_has_password_protection(self):
        self.assertTrue(Plan.get(Plan.PRO, "password_protection"))


# ── UserProfile properties ────────────────────────────────────────────────────

class TestUserProfileProperties(TestCase):
    def _make_user(self, plan):
        u = User.objects.create_user(f"u_{plan}", password="pw")
        UserProfile.objects.filter(user=u).update(plan=plan)
        u.refresh_from_db()
        return u

    def test_free_is_not_paid(self):
        u = self._make_user(Plan.FREE)
        self.assertFalse(u.profile.is_paid)

    def test_starter_is_paid(self):
        u = self._make_user(Plan.STARTER)
        self.assertTrue(u.profile.is_paid)

    def test_pro_is_paid(self):
        u = self._make_user(Plan.PRO)
        self.assertTrue(u.profile.is_paid)

    def test_free_storage_quota_is_none(self):
        u = self._make_user(Plan.FREE)
        self.assertIsNone(u.profile.storage_quota_bytes)

    def test_starter_storage_quota_is_5gb(self):
        u = self._make_user(Plan.STARTER)
        expected = 5 * 1024 ** 3
        self.assertEqual(u.profile.storage_quota_bytes, expected)

    def test_pro_storage_quota_is_20gb(self):
        u = self._make_user(Plan.PRO)
        expected = 20 * 1024 ** 3
        self.assertEqual(u.profile.storage_quota_bytes, expected)

    def test_storage_available_none_when_no_quota(self):
        u = self._make_user(Plan.FREE)
        self.assertIsNone(u.profile.storage_available_bytes())

    def test_storage_available_decreases_with_usage(self):
        u = self._make_user(Plan.STARTER)
        UserProfile.objects.filter(user=u).update(storage_used_bytes=1024 ** 3)
        u.profile.refresh_from_db()
        available = u.profile.storage_available_bytes()
        self.assertEqual(available, 4 * 1024 ** 3)


# ── PlanLimit DB model ────────────────────────────────────────────────────────

class TestPlanLimitModel(TestCase):
    """PlanLimit rows in DB should match the hardcoded LIMITS dict exactly."""

    def setUp(self):
        # Seed rows the same way migration 0006 does
        from core.models import PlanLimit
        for plan_key, data in Plan.LIMITS.items():
            PlanLimit.objects.update_or_create(plan=plan_key, defaults={
                k: v for k, v in data.items() if k != 'label' or True
            })
        # Force cache reload
        PlanLimit.invalidate_cache()

    def test_all_four_plans_seeded(self):
        from core.models import PlanLimit
        self.assertEqual(PlanLimit.objects.count(), 4)

    def test_plan_get_reads_from_db_not_dict(self):
        """Plan.get() should now return values from PlanLimit, not LIMITS."""
        from core.models import PlanLimit
        # Change a DB value
        PlanLimit.objects.filter(plan=Plan.STARTER).update(max_file_mb=9999)
        PlanLimit.invalidate_cache()
        self.assertEqual(Plan.get(Plan.STARTER, 'max_file_mb'), 9999)

    def test_invalidate_cache_forces_reload(self):
        from core.models import PlanLimit
        PlanLimit.objects.filter(plan=Plan.PRO).update(storage_gb=99)
        PlanLimit.invalidate_cache()
        self.assertEqual(Plan.get(Plan.PRO, 'storage_gb'), 99)

    def test_all_as_dicts_returns_all_plans(self):
        from core.models import PlanLimit
        PlanLimit.invalidate_cache()
        d = PlanLimit.all_as_dicts()
        self.assertIn(Plan.ANON, d)
        self.assertIn(Plan.FREE, d)
        self.assertIn(Plan.STARTER, d)
        self.assertIn(Plan.PRO, d)

    def test_as_dict_has_all_required_fields(self):
        from core.models import PlanLimit
        PlanLimit.invalidate_cache()
        d = PlanLimit.all_as_dicts()
        required = [
            'label', 'price_monthly', 'max_file_mb', 'max_text_kb',
            'max_expiry_days', 'clipboard_idle_hours', 'clipboard_max_lifetime_days',
            'anon_file_lifetime_days',
            'storage_gb', 'renewals', 'password_protection', 'max_collections',
        ]
        for plan_key in (Plan.ANON, Plan.FREE, Plan.STARTER, Plan.PRO):
            for field in required:
                self.assertIn(field, d[plan_key], msg=f"{plan_key} missing {field} in PlanLimit")

    def test_unknown_plan_falls_back_to_anon(self):
        from core.models import PlanLimit
        PlanLimit.invalidate_cache()
        val = PlanLimit.get('nonexistent', 'max_file_mb')
        self.assertEqual(val, Plan.LIMITS[Plan.ANON]['max_file_mb'])

    def test_max_collections_starter(self):
        from core.models import PlanLimit
        PlanLimit.invalidate_cache()
        self.assertEqual(Plan.get(Plan.STARTER, 'max_collections'), 10)

    def test_max_collections_pro_unlimited(self):
        from core.models import PlanLimit
        PlanLimit.invalidate_cache()
        self.assertIsNone(Plan.get(Plan.PRO, 'max_collections'))

    def test_max_collections_free_zero(self):
        from core.models import PlanLimit
        PlanLimit.invalidate_cache()
        self.assertEqual(Plan.get(Plan.FREE, 'max_collections'), 0)


# ── Email preferences ─────────────────────────────────────────────────────────

class TestEmailPreferences(TestCase):
    def _make_user(self, plan=Plan.FREE):
        u = User.objects.create_user('emailpref_user', password='pw')
        UserProfile.objects.filter(user=u).update(plan=plan)
        u.refresh_from_db()
        return u

    def test_notify_product_updates_default_true(self):
        u = self._make_user()
        self.assertTrue(u.profile.notify_product_updates)

    def test_notify_billing_default_true(self):
        u = self._make_user()
        self.assertTrue(u.profile.notify_billing)

    def test_notify_bug_fix_default_true(self):
        u = self._make_user()
        self.assertTrue(u.profile.notify_bug_fix)

    def test_can_opt_out_product_updates(self):
        u = self._make_user()
        UserProfile.objects.filter(user=u).update(notify_product_updates=False)
        u.profile.refresh_from_db()
        self.assertFalse(u.profile.notify_product_updates)

    def test_can_opt_out_billing(self):
        u = self._make_user()
        UserProfile.objects.filter(user=u).update(notify_billing=False)
        u.profile.refresh_from_db()
        self.assertFalse(u.profile.notify_billing)

    def test_account_settings_saves_all_three_prefs(self):
        from django.test import Client
        u = self._make_user()
        c = Client()
        c.force_login(u)
        # All three checked
        res = c.post('/auth/account/settings/', {
            'notify_bug_fix': '1',
            'notify_product_updates': '1',
            'notify_billing': '1',
        })
        self.assertIn(res.status_code, (200, 302))
        u.profile.refresh_from_db()
        self.assertTrue(u.profile.notify_bug_fix)
        self.assertTrue(u.profile.notify_product_updates)
        self.assertTrue(u.profile.notify_billing)

    def test_account_settings_opt_out_all(self):
        from django.test import Client
        u = self._make_user()
        c = Client()
        c.force_login(u)
        # No checkboxes submitted = all False
        res = c.post('/auth/account/settings/', {})
        self.assertIn(res.status_code, (200, 302))
        u.profile.refresh_from_db()
        self.assertFalse(u.profile.notify_bug_fix)
        self.assertFalse(u.profile.notify_product_updates)
        self.assertFalse(u.profile.notify_billing)

    def test_account_settings_partial_opt_out(self):
        from django.test import Client
        u = self._make_user()
        c = Client()
        c.force_login(u)
        # Only billing kept on
        res = c.post('/auth/account/settings/', {'notify_billing': '1'})
        self.assertIn(res.status_code, (200, 302))
        u.profile.refresh_from_db()
        self.assertFalse(u.profile.notify_bug_fix)
        self.assertFalse(u.profile.notify_product_updates)
        self.assertTrue(u.profile.notify_billing)
