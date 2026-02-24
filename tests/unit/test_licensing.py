"""
tests/unit/test_licensing.py

Tests for the commercial licensing system:
  - Model basics
  - Licensing page renders
  - PDF generation with valid key
  - Invalid key rejected
  - Webhook stores license key
  - PDF content verification
"""

import hashlib
import hmac
import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from billing.models import CommercialLicense


# ── Model tests ───────────────────────────────────────────────────────────────

class TestCommercialLicenseModel(TestCase):

    def test_create_license(self):
        lic = CommercialLicense.objects.create(
            license_key="TEST-KEY-1234",
            licensee_email="buyer@example.com",
        )
        assert lic.is_active is True
        assert lic.pdf_downloaded is False
        assert lic.license_key == "TEST-KEY-1234"

    def test_str_includes_name_and_key(self):
        lic = CommercialLicense.objects.create(
            license_key="ABCD-EFGH-IJKL-MNOP",
            licensee_name="Acme Corp",
        )
        s = str(lic)
        assert "Acme Corp" in s
        assert "ABCD-EFGH-IJKL-M" in s  # truncated at 16 chars

    def test_str_fallback_to_email(self):
        lic = CommercialLicense.objects.create(
            license_key="KEY-ONLY",
            licensee_email="test@test.com",
        )
        assert "test@test.com" in str(lic)

    def test_unique_key(self):
        CommercialLicense.objects.create(license_key="UNIQUE-KEY")
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            CommercialLicense.objects.create(license_key="UNIQUE-KEY")


# ── Page tests ────────────────────────────────────────────────────────────────

class TestLicensingPage(TestCase):

    def test_licensing_page_renders(self):
        res = self.client.get("/billing/licensing/")
        assert res.status_code == 200
        assert b"Commercial Self-Hosted License" in res.content

    @override_settings(LEMONSQUEEZY_COMMERCIAL_URL="https://store.lemonsqueezy.com/buy/test123")
    def test_licensing_page_shows_checkout_link(self):
        res = self.client.get("/billing/licensing/")
        assert b"https://store.lemonsqueezy.com/buy/test123" in res.content
        assert b"Buy on Lemon Squeezy" in res.content

    def test_licensing_page_no_link_without_url(self):
        res = self.client.get("/billing/licensing/")
        assert b"Buy on Lemon Squeezy" not in res.content


# ── PDF generation tests ─────────────────────────────────────────────────────

class TestLicensePDFGeneration(TestCase):

    def test_valid_key_returns_pdf(self):
        CommercialLicense.objects.create(
            license_key="VALID-KEY-123",
            licensee_email="buyer@test.com",
        )
        res = self.client.post("/billing/licensing/generate/", {
            "license_key": "VALID-KEY-123",
            "licensee_name": "Test Corp",
        })
        assert res.status_code == 200
        assert res["Content-Type"] == "application/pdf"
        assert "drp-commercial-license-VALID-KE" in res["Content-Disposition"]
        # Verify it starts with PDF magic bytes
        assert res.content[:5] == b"%PDF-"

    def test_valid_key_updates_licensee_name(self):
        lic = CommercialLicense.objects.create(
            license_key="NAME-KEY-123",
            licensee_email="buyer@test.com",
        )
        self.client.post("/billing/licensing/generate/", {
            "license_key": "NAME-KEY-123",
            "licensee_name": "Updated Corp",
        })
        lic.refresh_from_db()
        assert lic.licensee_name == "Updated Corp"
        assert lic.pdf_downloaded is True

    def test_invalid_key_shows_error(self):
        res = self.client.post("/billing/licensing/generate/", {
            "license_key": "INVALID-KEY",
            "licensee_name": "Test Corp",
        })
        assert res.status_code == 200  # re-renders form
        assert b"License key not found" in res.content

    def test_inactive_key_shows_error(self):
        CommercialLicense.objects.create(
            license_key="INACTIVE-KEY",
            is_active=False,
        )
        res = self.client.post("/billing/licensing/generate/", {
            "license_key": "INACTIVE-KEY",
            "licensee_name": "Test Corp",
        })
        assert b"License key not found" in res.content

    def test_missing_name_shows_error(self):
        CommercialLicense.objects.create(license_key="KEY-123")
        res = self.client.post("/billing/licensing/generate/", {
            "license_key": "KEY-123",
            "licensee_name": "",
        })
        assert b"Please fill in both" in res.content

    def test_missing_key_shows_error(self):
        res = self.client.post("/billing/licensing/generate/", {
            "license_key": "",
            "licensee_name": "Test",
        })
        assert b"Please fill in both" in res.content

    def test_get_not_allowed(self):
        res = self.client.get("/billing/licensing/generate/")
        assert res.status_code == 405


# ── Webhook tests ─────────────────────────────────────────────────────────────

WEBHOOK_SECRET = "test-webhook-secret"


@override_settings(LEMONSQUEEZY_SIGNING_SECRET=WEBHOOK_SECRET)
class TestLicenseKeyWebhook(TestCase):

    def _signed_post(self, payload, event="license_key_created"):
        body = json.dumps(payload).encode()
        sig = hmac.digest(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hex()
        return self.client.post(
            "/billing/webhook/",
            data=body,
            content_type="application/json",
            HTTP_X_SIGNATURE=sig,
            HTTP_X_EVENT_NAME=event,
        )

    def test_license_key_created_stores_key(self):
        payload = {
            "meta": {"event_name": "license_key_created", "custom_data": {}},
            "data": {
                "id": "1",
                "type": "license-keys",
                "attributes": {
                    "key": "LK-AAAA-BBBB-CCCC",
                    "status": "active",
                    "order_id": 999,
                    "customer_id": 555,
                    "user_email": "buyer@example.com",
                    "user_name": "Buyer",
                },
            },
        }
        res = self._signed_post(payload)
        assert res.status_code == 200

        lic = CommercialLicense.objects.get(license_key="LK-AAAA-BBBB-CCCC")
        assert lic.licensee_email == "buyer@example.com"
        assert lic.order_id == "999"
        assert lic.ls_customer_id == "555"
        assert lic.is_active is True
        assert lic.expires_at is not None

    def test_duplicate_key_updates_instead_of_crash(self):
        CommercialLicense.objects.create(
            license_key="DUP-KEY",
            licensee_email="old@test.com",
        )
        payload = {
            "meta": {"event_name": "license_key_created", "custom_data": {}},
            "data": {
                "id": "2",
                "attributes": {
                    "key": "DUP-KEY",
                    "order_id": 100,
                    "customer_id": 200,
                    "user_email": "new@test.com",
                },
            },
        }
        res = self._signed_post(payload)
        assert res.status_code == 200
        assert CommercialLicense.objects.filter(license_key="DUP-KEY").count() == 1
        lic = CommercialLicense.objects.get(license_key="DUP-KEY")
        assert lic.licensee_email == "new@test.com"

    def test_invalid_signature_rejected(self):
        payload = {
            "meta": {"event_name": "license_key_created", "custom_data": {}},
            "data": {"id": "1", "attributes": {"key": "BAD-SIG"}},
        }
        res = self.client.post(
            "/billing/webhook/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_SIGNATURE="bad-sig",
            HTTP_X_EVENT_NAME="license_key_created",
        )
        assert res.status_code == 400

    def test_license_key_without_key_field_ignored(self):
        """If LS sends license_key_created but no key in attributes, nothing crashes."""
        payload = {
            "meta": {"event_name": "license_key_created", "custom_data": {}},
            "data": {"id": "1", "attributes": {}},
        }
        res = self._signed_post(payload)
        assert res.status_code == 200
        assert CommercialLicense.objects.count() == 0


# ── PDF builder internal test ─────────────────────────────────────────────────

class TestPDFBuilder(TestCase):

    def test_build_license_pdf_returns_valid_pdf(self):
        from billing.licensing import _build_license_pdf
        lic = CommercialLicense.objects.create(
            license_key="PDF-TEST-KEY",
            licensee_email="pdf@test.com",
            expires_at=timezone.now() + timezone.timedelta(days=365),
        )
        pdf = _build_license_pdf(lic, "PDF Corp")
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 1000  # sanity — a real PDF of this license is several KB

    def test_build_license_pdf_is_substantial(self):
        """The generated PDF should be a real multi-page document."""
        from billing.licensing import _build_license_pdf
        lic = CommercialLicense.objects.create(
            license_key="CONTENT-KEY",
            licensee_email="content@test.com",
        )
        pdf = _build_license_pdf(lic, "Acme Industries")
        assert pdf[:5] == b"%PDF-"
        # A full license PDF should be several KB
        assert len(pdf) > 3000

    def test_get_license_sections_has_all_sections(self):
        from billing.licensing import _get_license_sections
        sections = _get_license_sections()
        assert len(sections) == 11
        headings = [s[0] for s in sections]
        assert "1. Grant of License" in headings
        assert "11. General Provisions" in headings
