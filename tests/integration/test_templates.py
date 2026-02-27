"""
Integration tests: drop template CRUD (paid users only).

POST /auth/templates/create/           — create template
GET  /auth/templates/                  — list templates
GET  /auth/templates/<slug>/           — get template
POST /auth/templates/<id>/delete/      — delete template
"""

import json
import pytest

from core.models import DropTemplate

pytestmark = pytest.mark.django_db


class TestCreateTemplate:
    """POST /auth/templates/create/"""

    def test_paid_creates_template(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post(
            "/auth/templates/create/",
            data=json.dumps({
                "slug": "standup",
                "name": "Daily Standup",
                "content": "Yesterday:\nToday:\nBlockers:",
                "burn": False,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["slug"] == "standup"
        assert data["name"] == "Daily Standup"

    def test_free_user_rejected(self, client, fake_b2, free_user):
        client.force_login(free_user)
        resp = client.post(
            "/auth/templates/create/",
            data=json.dumps({"slug": "x", "name": "X"}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_duplicate_slug(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        payload = json.dumps({"slug": "dup", "name": "Dup"})
        client.post("/auth/templates/create/", data=payload, content_type="application/json")
        resp = client.post("/auth/templates/create/", data=payload, content_type="application/json")
        assert resp.status_code == 409

    def test_missing_fields(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post(
            "/auth/templates/create/",
            data=json.dumps({"slug": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_template_with_all_options(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post(
            "/auth/templates/create/",
            data=json.dumps({
                "slug": "secret-note",
                "name": "Secret",
                "content": "CONFIDENTIAL",
                "burn": True,
                "expiry_days": 7,
                "password": True,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        tpl = DropTemplate.objects.get(slug="secret-note", owner=starter_user)
        assert tpl.burn is True
        assert tpl.expiry_days == 7
        assert tpl.password is True


class TestListTemplates:
    """GET /auth/templates/"""

    def test_list_empty(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.get("/auth/templates/")
        assert resp.status_code == 200
        assert resp.json()["templates"] == []

    def test_list_shows_templates(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post(
            "/auth/templates/create/",
            data=json.dumps({"slug": "list-t", "name": "List Test"}),
            content_type="application/json",
        )

        resp = client.get("/auth/templates/")
        templates = resp.json()["templates"]
        assert len(templates) == 1
        assert templates[0]["slug"] == "list-t"

    def test_list_free_rejected(self, client, fake_b2, free_user):
        client.force_login(free_user)
        resp = client.get("/auth/templates/")
        assert resp.status_code == 403


class TestGetTemplate:
    """GET /auth/templates/<slug>/"""

    def test_get_by_slug(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post(
            "/auth/templates/create/",
            data=json.dumps({
                "slug": "fetch-me",
                "name": "Fetch",
                "content": "template body",
            }),
            content_type="application/json",
        )

        resp = client.get("/auth/templates/fetch-me/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "fetch-me"
        assert data["content"] == "template body"

    def test_get_nonexistent(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.get("/auth/templates/ghost/")
        assert resp.status_code == 404

    def test_cannot_get_others_template(self, client, fake_b2, starter_user, pro_user):
        client.force_login(starter_user)
        client.post(
            "/auth/templates/create/",
            data=json.dumps({"slug": "private-t", "name": "Private"}),
            content_type="application/json",
        )

        client.force_login(pro_user)
        resp = client.get("/auth/templates/private-t/")
        assert resp.status_code == 404


class TestDeleteTemplate:
    """POST /auth/templates/<id>/delete/"""

    def test_delete_template(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post(
            "/auth/templates/create/",
            data=json.dumps({"slug": "del-t", "name": "Delete Me"}),
            content_type="application/json",
        )
        tpl_id = resp.json()["id"]

        resp = client.post(f"/auth/templates/{tpl_id}/delete/")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert not DropTemplate.objects.filter(pk=tpl_id).exists()

    def test_delete_nonexistent(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post("/auth/templates/99999/delete/")
        assert resp.status_code == 404

    def test_cannot_delete_others(self, client, fake_b2, starter_user, pro_user):
        client.force_login(starter_user)
        resp = client.post(
            "/auth/templates/create/",
            data=json.dumps({"slug": "theirs-t", "name": "Theirs"}),
            content_type="application/json",
        )
        tpl_id = resp.json()["id"]

        client.force_login(pro_user)
        resp = client.post(f"/auth/templates/{tpl_id}/delete/")
        assert resp.status_code == 404
        assert DropTemplate.objects.filter(pk=tpl_id).exists()
