"""
Tests for Plan.LIMITS schema and PlanLimit consistency.

Ensures all plans have expected fields, limits are sensible,
and plan hierarchy is correct.
"""

import pytest
from core.models import Plan


# ── Schema completeness ──────────────────────────────────────────────────────

REQUIRED_FIELDS = [
    "label", "price_monthly", "max_file_mb", "max_text_kb",
    "max_expiry_days", "clipboard_idle_hours", "clipboard_max_lifetime_days",
    "anon_file_lifetime_days", "storage_gb", "renewals",
    "password_protection", "max_folders", "webhooks", "api_keys",
    "scheduled_drops", "helpbot_hourly", "smart_parse", "api_fetch",
    "remote_upload",
]


class TestPlanSchema:
    @pytest.mark.parametrize("plan_key", [Plan.ANON, Plan.FREE, Plan.STARTER, Plan.PRO])
    def test_has_all_fields(self, plan_key):
        limits = Plan.LIMITS[plan_key]
        for field in REQUIRED_FIELDS:
            assert field in limits, f"{plan_key} missing {field}"

    def test_four_plans_exist(self):
        assert len(Plan.LIMITS) == 4

    def test_plan_labels_unique(self):
        labels = [v["label"] for v in Plan.LIMITS.values()]
        assert len(labels) == len(set(labels))


# ── File limits ──────────────────────────────────────────────────────────────

class TestPlanFileLimits:
    def test_anon_free_same_file_limit(self):
        assert Plan.LIMITS[Plan.ANON]["max_file_mb"] == Plan.LIMITS[Plan.FREE]["max_file_mb"]

    def test_starter_larger_than_free(self):
        assert Plan.LIMITS[Plan.STARTER]["max_file_mb"] > Plan.LIMITS[Plan.FREE]["max_file_mb"]

    def test_pro_larger_than_starter(self):
        assert Plan.LIMITS[Plan.PRO]["max_file_mb"] > Plan.LIMITS[Plan.STARTER]["max_file_mb"]

    def test_free_file_limit_is_200mb(self):
        assert Plan.LIMITS[Plan.FREE]["max_file_mb"] == 200

    def test_starter_file_limit_is_1gb(self):
        assert Plan.LIMITS[Plan.STARTER]["max_file_mb"] == 1024

    def test_pro_file_limit_is_5gb(self):
        assert Plan.LIMITS[Plan.PRO]["max_file_mb"] == 5120

    def test_pro_text_limit_is_10mb(self):
        assert Plan.LIMITS[Plan.PRO]["max_text_kb"] == 10240


# ── Expiry ────────────────────────────────────────────────────────────────────

class TestPlanExpiry:
    def test_anon_no_custom_expiry(self):
        assert Plan.LIMITS[Plan.ANON]["max_expiry_days"] is None

    def test_free_no_custom_expiry(self):
        assert Plan.LIMITS[Plan.FREE]["max_expiry_days"] is None

    def test_starter_can_set_custom_expiry(self):
        assert Plan.LIMITS[Plan.STARTER]["max_expiry_days"] is not None

    def test_starter_max_expiry_is_1_year(self):
        assert Plan.LIMITS[Plan.STARTER]["max_expiry_days"] == 365

    def test_pro_max_expiry_is_3_years(self):
        assert Plan.LIMITS[Plan.PRO]["max_expiry_days"] == 365 * 3

    def test_pro_longer_expiry_than_starter(self):
        assert Plan.LIMITS[Plan.PRO]["max_expiry_days"] > Plan.LIMITS[Plan.STARTER]["max_expiry_days"]


# ── Idle / lifetime ──────────────────────────────────────────────────────────

class TestPlanIdleLifetime:
    def test_anon_clipboard_max_lifetime_7_days(self):
        assert Plan.LIMITS[Plan.ANON]["clipboard_max_lifetime_days"] == 7

    def test_free_clipboard_max_lifetime_30_days(self):
        assert Plan.LIMITS[Plan.FREE]["clipboard_max_lifetime_days"] == 30

    def test_paid_plans_no_clipboard_ceiling(self):
        assert Plan.LIMITS[Plan.STARTER]["clipboard_max_lifetime_days"] is None
        assert Plan.LIMITS[Plan.PRO]["clipboard_max_lifetime_days"] is None

    def test_free_idle_hours_48(self):
        assert Plan.LIMITS[Plan.FREE]["clipboard_idle_hours"] == 48

    def test_anon_idle_hours_24(self):
        assert Plan.LIMITS[Plan.ANON]["clipboard_idle_hours"] == 24

    def test_paid_no_idle_expiry(self):
        assert Plan.LIMITS[Plan.STARTER]["clipboard_idle_hours"] is None
        assert Plan.LIMITS[Plan.PRO]["clipboard_idle_hours"] is None


# ── Storage ──────────────────────────────────────────────────────────────────

class TestPlanStorage:
    def test_anon_no_storage(self):
        assert Plan.LIMITS[Plan.ANON]["storage_gb"] is None

    def test_free_no_storage(self):
        assert Plan.LIMITS[Plan.FREE]["storage_gb"] is None

    def test_starter_storage_5gb(self):
        assert Plan.LIMITS[Plan.STARTER]["storage_gb"] == 5

    def test_pro_storage_20gb(self):
        assert Plan.LIMITS[Plan.PRO]["storage_gb"] == 20


# ── Password protection ──────────────────────────────────────────────────────

class TestPlanPasswordProtection:
    def test_anon_no_password(self):
        assert Plan.LIMITS[Plan.ANON]["password_protection"] is False

    def test_free_no_password(self):
        assert Plan.LIMITS[Plan.FREE]["password_protection"] is False

    def test_starter_has_password(self):
        assert Plan.LIMITS[Plan.STARTER]["password_protection"] is True

    def test_pro_has_password(self):
        assert Plan.LIMITS[Plan.PRO]["password_protection"] is True


# ── Folder limits ─────────────────────────────────────────────────────────────

class TestPlanFolders:
    def test_anon_no_folders(self):
        assert Plan.LIMITS[Plan.ANON]["max_folders"] == 0

    def test_free_no_folders(self):
        assert Plan.LIMITS[Plan.FREE]["max_folders"] == 0

    def test_starter_limited_folders(self):
        assert Plan.LIMITS[Plan.STARTER]["max_folders"] == 10

    def test_pro_unlimited_folders(self):
        assert Plan.LIMITS[Plan.PRO]["max_folders"] is None


# ── Feature flags ─────────────────────────────────────────────────────────────

class TestPlanFeatures:
    def test_only_pro_has_remote_upload(self):
        assert Plan.LIMITS[Plan.PRO]["remote_upload"] is True
        assert Plan.LIMITS[Plan.STARTER]["remote_upload"] is False
        assert Plan.LIMITS[Plan.FREE]["remote_upload"] is False
        assert Plan.LIMITS[Plan.ANON]["remote_upload"] is False

    def test_all_plans_have_smart_parse(self):
        for plan in Plan.LIMITS:
            assert Plan.LIMITS[plan]["smart_parse"] is True

    def test_all_plans_have_api_fetch(self):
        for plan in Plan.LIMITS:
            assert Plan.LIMITS[plan]["api_fetch"] is True

    def test_pricing_hierarchy(self):
        prices = [Plan.LIMITS[p]["price_monthly"] for p in
                  [Plan.ANON, Plan.FREE, Plan.STARTER, Plan.PRO]]
        assert prices == sorted(prices)
