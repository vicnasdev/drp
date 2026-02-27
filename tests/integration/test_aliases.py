"""
Integration tests: alias CRUD.

POST /auth/aliases/create/          — create alias
GET  /auth/aliases/                 — list aliases
POST /auth/aliases/<id>/delete/     — delete alias
"""

import json
import pytest

from core.models import Alias, Drop

pytestmark = pytest.mark.django_db


class TestCreateAlias:
    """POST /auth/aliases/create/"""

    def test_create_alias(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "aliased", "key": "al-c1"})

        resp = client.post(
            "/auth/aliases/create/",
            data=json.dumps({"alias": "my-note", "key": "al-c1"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["alias"] == "my-note"
        assert data["key"] == "al-c1"

    def test_create_duplicate_alias(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "x", "key": "al-c2"})
        client.post(
            "/auth/aliases/create/",
            data=json.dumps({"alias": "dup", "key": "al-c2"}),
            content_type="application/json",
        )
        resp = client.post(
            "/auth/aliases/create/",
            data=json.dumps({"alias": "dup", "key": "al-c2"}),
            content_type="application/json",
        )
        assert resp.status_code == 409

    def test_create_alias_nonexistent_drop(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post(
            "/auth/aliases/create/",
            data=json.dumps({"alias": "ghost", "key": "nonexistent"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_create_alias_requires_login(self, client, fake_b2):
        resp = client.post(
            "/auth/aliases/create/",
            data=json.dumps({"alias": "x", "key": "y"}),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_create_alias_missing_fields(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post(
            "/auth/aliases/create/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400


class TestListAliases:
    """GET /auth/aliases/"""

    def test_list_empty(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.get("/auth/aliases/")
        assert resp.status_code == 200
        assert resp.json()["aliases"] == []

    def test_list_with_aliases(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "x", "key": "al-l1"})
        client.post(
            "/auth/aliases/create/",
            data=json.dumps({"alias": "first", "key": "al-l1"}),
            content_type="application/json",
        )

        resp = client.get("/auth/aliases/")
        aliases = resp.json()["aliases"]
        assert len(aliases) == 1
        assert aliases[0]["alias"] == "first"
        assert aliases[0]["key"] == "al-l1"

    def test_list_requires_login(self, client, fake_b2):
        resp = client.get("/auth/aliases/")
        assert resp.status_code == 401


class TestDeleteAlias:
    """POST /auth/aliases/<id>/delete/"""

    def test_delete_alias(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "x", "key": "al-d1"})
        resp = client.post(
            "/auth/aliases/create/",
            data=json.dumps({"alias": "del-me", "key": "al-d1"}),
            content_type="application/json",
        )
        alias_id = resp.json()["id"]

        resp = client.post(f"/auth/aliases/{alias_id}/delete/")
        assert resp.status_code == 200
        assert not Alias.objects.filter(pk=alias_id).exists()

    def test_delete_nonexistent(self, client, fake_b2, starter_user):
        client.force_login(starter_user)
        resp = client.post("/auth/aliases/99999/delete/")
        assert resp.status_code == 404

    def test_cannot_delete_others(self, client, fake_b2, starter_user, free_user):
        client.force_login(starter_user)
        client.post("/save/", {"content": "x", "key": "al-d2"})
        resp = client.post(
            "/auth/aliases/create/",
            data=json.dumps({"alias": "theirs", "key": "al-d2"}),
            content_type="application/json",
        )
        alias_id = resp.json()["id"]

        client.force_login(free_user)
        resp = client.post(f"/auth/aliases/{alias_id}/delete/")
        assert resp.status_code == 404
        assert Alias.objects.filter(pk=alias_id).exists()

    def test_delete_preserves_drop(self, client, fake_b2, starter_user):
        """Deleting an alias doesn't delete the underlying drop."""
        client.force_login(starter_user)
        client.post("/save/", {"content": "safe", "key": "al-d3"})
        resp = client.post(
            "/auth/aliases/create/",
            data=json.dumps({"alias": "temp", "key": "al-d3"}),
            content_type="application/json",
        )
        alias_id = resp.json()["id"]
        client.post(f"/auth/aliases/{alias_id}/delete/")

        assert Drop.objects.filter(key="al-d3").exists()
