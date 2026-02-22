"""
tests/unit/test_collections.py

Unit tests for collection creation, membership, plan gating, and public views.
"""

import json

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Collection, CollectionMembership, Drop, Plan, UserProfile


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(username, plan=Plan.FREE, password="pw"):
    u = User.objects.create_user(username, email=f"{username}@test.com", password=password)
    UserProfile.objects.filter(user=u).update(plan=plan)
    u.refresh_from_db()
    return u


def _make_drop(user=None, key="testkey", ns="c", kind="text", content="hello"):
    return Drop.objects.create(
        ns=ns, key=key, kind=kind, content=content,
        owner=user, locked=user is not None,
    )


def _create(client, name, slug=""):
    return client.post(
        "/collections/create/",
        json.dumps({"name": name, "slug": slug}),
        content_type="application/json",
        HTTP_ACCEPT="application/json",
    )


def _add(client, collection_id, ns, key):
    return client.post(
        f"/collections/{collection_id}/add/",
        json.dumps({"ns": ns, "key": key}),
        content_type="application/json",
    )


def _remove(client, collection_id, ns, key):
    return client.post(
        f"/collections/{collection_id}/remove/",
        json.dumps({"ns": ns, "key": key}),
        content_type="application/json",
    )


def _rename(client, collection_id, name, slug=""):
    return client.post(
        f"/collections/{collection_id}/rename/",
        json.dumps({"name": name, "slug": slug}),
        content_type="application/json",
    )


def _delete(client, collection_id):
    return client.post(f"/collections/{collection_id}/delete/")


# ── Plan gating ───────────────────────────────────────────────────────────────

class TestCollectionPlanGating(TestCase):
    def setUp(self):
        self.free_user    = _make_user("free_col",    Plan.FREE)
        self.starter_user = _make_user("starter_col", Plan.STARTER)
        self.pro_user     = _make_user("pro_col",     Plan.PRO)

    def test_anon_cannot_create(self):
        res = _create(self.client, "my col")
        self.assertEqual(res.status_code, 302)  # redirect to login

    def test_free_cannot_create(self):
        self.client.force_login(self.free_user)
        res = _create(self.client, "my col")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(Collection.objects.filter(owner=self.free_user).exists())

    def test_starter_can_create(self):
        self.client.force_login(self.starter_user)
        res = _create(self.client, "my collection")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(Collection.objects.filter(owner=self.starter_user).exists())

    def test_pro_can_create(self):
        self.client.force_login(self.pro_user)
        res = _create(self.client, "pro col")
        self.assertEqual(res.status_code, 201)

    def test_starter_capped_at_10(self):
        self.client.force_login(self.starter_user)
        for i in range(10):
            _create(self.client, f"col {i}", slug=f"col-{i}")
        self.assertEqual(Collection.objects.filter(owner=self.starter_user).count(), 10)
        res = _create(self.client, "one too many", slug="one-too-many")
        self.assertEqual(res.status_code, 403)
        self.assertIn("limit", res.json()["error"])

    def test_pro_unlimited(self):
        self.client.force_login(self.pro_user)
        for i in range(15):
            _create(self.client, f"col {i}", slug=f"col-{i}")
        self.assertEqual(Collection.objects.filter(owner=self.pro_user).count(), 15)


# ── Create collection ─────────────────────────────────────────────────────────

class TestCollectionCreate(TestCase):
    def setUp(self):
        self.user = _make_user("creator", Plan.STARTER)
        self.client.force_login(self.user)

    def test_creates_with_auto_slug(self):
        res = _create(self.client, "My Cool Drops")
        self.assertEqual(res.status_code, 201)
        col = Collection.objects.get(owner=self.user)
        self.assertEqual(col.name, "My Cool Drops")
        self.assertEqual(col.slug, "my-cool-drops")

    def test_creates_with_explicit_slug(self):
        res = _create(self.client, "stuff", "my-stuff")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Collection.objects.get(owner=self.user).slug, "my-stuff")

    def test_duplicate_slug_rejected(self):
        _create(self.client, "first", "dupes")
        res = _create(self.client, "second", "dupes")
        self.assertEqual(res.status_code, 409)

    def test_empty_name_rejected(self):
        res = _create(self.client, "")
        self.assertEqual(res.status_code, 400)

    def test_invalid_slug_rejected(self):
        res = _create(self.client, "name", "bad slug!")
        self.assertEqual(res.status_code, 400)

    def test_url_in_response(self):
        res = _create(self.client, "mydrops", "mydrops")
        self.assertIn("/@creator/mydrops/", res.json()["url"])


# ── Membership ────────────────────────────────────────────────────────────────

class TestCollectionMembership(TestCase):
    def setUp(self):
        self.user  = _make_user("member_owner", Plan.STARTER)
        self.other = _make_user("member_other", Plan.STARTER)
        self.client.force_login(self.user)
        res = _create(self.client, "testcol", "testcol")
        self.col_id = res.json()["id"]
        self.drop = _make_drop(self.user, key="mydrop")

    def test_add_drop(self):
        res = _add(self.client, self.col_id, "c", "mydrop")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(CollectionMembership.objects.filter(
            collection_id=self.col_id, ns="c", key="mydrop"
        ).exists())

    def test_add_nonexistent_drop_rejected(self):
        res = _add(self.client, self.col_id, "c", "doesnotexist")
        self.assertEqual(res.status_code, 404)

    def test_add_duplicate_idempotent(self):
        _add(self.client, self.col_id, "c", "mydrop")
        res = _add(self.client, self.col_id, "c", "mydrop")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["created"])
        self.assertEqual(CollectionMembership.objects.filter(
            collection_id=self.col_id
        ).count(), 1)

    def test_remove_drop(self):
        _add(self.client, self.col_id, "c", "mydrop")
        res = _remove(self.client, self.col_id, "c", "mydrop")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["removed"])
        self.assertFalse(CollectionMembership.objects.filter(
            collection_id=self.col_id, key="mydrop"
        ).exists())

    def test_other_user_cannot_add(self):
        self.client.force_login(self.other)
        res = _add(self.client, self.col_id, "c", "mydrop")
        self.assertEqual(res.status_code, 403)

    def test_other_user_cannot_remove(self):
        _add(self.client, self.col_id, "c", "mydrop")
        self.client.force_login(self.other)
        res = _remove(self.client, self.col_id, "c", "mydrop")
        self.assertEqual(res.status_code, 403)


# ── Rename and delete ─────────────────────────────────────────────────────────

class TestCollectionRenameDelete(TestCase):
    def setUp(self):
        self.user  = _make_user("rd_owner", Plan.STARTER)
        self.other = _make_user("rd_other", Plan.STARTER)
        self.client.force_login(self.user)
        res = _create(self.client, "original", "original")
        self.col_id = res.json()["id"]

    def test_rename(self):
        res = _rename(self.client, self.col_id, "renamed", "renamed")
        self.assertEqual(res.status_code, 200)
        col = Collection.objects.get(pk=self.col_id)
        self.assertEqual(col.name, "renamed")
        self.assertEqual(col.slug, "renamed")

    def test_rename_auto_slug(self):
        res = _rename(self.client, self.col_id, "New Name")
        self.assertEqual(res.status_code, 200)
        col = Collection.objects.get(pk=self.col_id)
        self.assertEqual(col.slug, "new-name")

    def test_rename_conflict_rejected(self):
        _create(self.client, "other", "other")
        res = _rename(self.client, self.col_id, "other", "other")
        self.assertEqual(res.status_code, 409)

    def test_other_cannot_rename(self):
        self.client.force_login(self.other)
        res = _rename(self.client, self.col_id, "hacked", "hacked")
        self.assertEqual(res.status_code, 403)

    def test_delete(self):
        res = _delete(self.client, self.col_id)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Collection.objects.filter(pk=self.col_id).exists())

    def test_delete_removes_memberships(self):
        drop = _make_drop(self.user, key="delmem")
        _add(self.client, self.col_id, "c", "delmem")
        _delete(self.client, self.col_id)
        self.assertFalse(CollectionMembership.objects.filter(
            collection_id=self.col_id
        ).exists())

    def test_other_cannot_delete(self):
        self.client.force_login(self.other)
        res = _delete(self.client, self.col_id)
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Collection.objects.filter(pk=self.col_id).exists())


# ── Public views ──────────────────────────────────────────────────────────────

class TestCollectionPublicViews(TestCase):
    def setUp(self):
        self.owner  = _make_user("pub_owner", Plan.STARTER)
        self.viewer = _make_user("pub_viewer", Plan.FREE)
        self.client.force_login(self.owner)
        res = _create(self.client, "public col", "public-col")
        self.col_id  = res.json()["id"]
        self.col_url = res.json()["url"]
        self.drop = _make_drop(self.owner, key="pubdrop")
        _add(self.client, self.col_id, "c", "pubdrop")

    def test_list_page_public(self):
        self.client.logout()
        res = self.client.get("/@pub_owner/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "public col")

    def test_detail_page_public(self):
        self.client.logout()
        res = self.client.get(self.col_url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "pubdrop")

    def test_detail_page_does_not_show_owner_controls_to_viewer(self):
        self.client.force_login(self.viewer)
        res = self.client.get(self.col_url)
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "deleteBtn")

    def test_owner_sees_controls(self):
        res = self.client.get(self.col_url)
        self.assertContains(res, "deleteBtn")

    def test_deleted_drop_shown_gracefully(self):
        self.drop.delete()
        res = self.client.get(self.col_url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "deleted")

    def test_password_protected_drop_shown_with_lock_icon(self):
        from django.contrib.auth.hashers import make_password
        Drop.objects.filter(key="pubdrop").update(password_hash=make_password("secret"))
        res = self.client.logout() or self.client.get(self.col_url)
        self.assertEqual(res.status_code, 200)
        # lock icon should appear in the listing
        self.assertContains(res, "🔒")

    def test_unknown_username_404(self):
        res = self.client.get("/@nobody/")
        self.assertEqual(res.status_code, 404)

    def test_unknown_collection_slug_404(self):
        res = self.client.get("/@pub_owner/nope/")
        self.assertEqual(res.status_code, 404)


# ── Orphan cleanup signal ─────────────────────────────────────────────────────

class TestOrphanCleanup(TestCase):
    def setUp(self):
        self.user = _make_user("orphan_owner", Plan.STARTER)
        self.client.force_login(self.user)
        res = _create(self.client, "cleanup col", "cleanup-col")
        self.col_id = res.json()["id"]
        self.drop = _make_drop(self.user, key="orphandrop")
        _add(self.client, self.col_id, "c", "orphandrop")

    def test_deleting_drop_removes_membership(self):
        self.assertTrue(CollectionMembership.objects.filter(key="orphandrop").exists())
        self.drop.delete()
        self.assertFalse(CollectionMembership.objects.filter(key="orphandrop").exists())

    def test_collection_survives_drop_deletion(self):
        self.drop.delete()
        self.assertTrue(Collection.objects.filter(pk=self.col_id).exists())
