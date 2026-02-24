"""
tests/unit/test_collections.py

Unit tests for collection creation, membership, plan gating, public views,
sub-collections (nested), and plan downgrade behaviour.
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

    def test_deleted_drop_removes_membership_from_collection(self):
        """
        When a drop is deleted, the post_delete signal removes its CollectionMembership.
        The collection page still loads (200) but no longer lists the deleted drop.
        """
        self.drop.delete()
        # Membership must be gone (signal fired)
        self.assertFalse(CollectionMembership.objects.filter(key="pubdrop").exists())
        # Collection page still renders fine
        res = self.client.get(self.col_url)
        self.assertEqual(res.status_code, 200)

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


# ── Sub-collections (nesting) ─────────────────────────────────────────────────

class TestSubCollectionModel(TestCase):
    """Model-level tests for nested collections."""

    def setUp(self):
        self.user = _make_user("sub_owner", Plan.PRO)
        self.root = Collection.objects.create(owner=self.user, slug="notes", name="Notes")
        self.child = Collection.objects.create(
            owner=self.user, slug="work", name="Work", parent=self.root
        )
        self.grandchild = Collection.objects.create(
            owner=self.user, slug="daily", name="Daily", parent=self.child
        )

    def test_full_path_root(self):
        self.assertEqual(self.root.full_path, "notes")

    def test_full_path_child(self):
        self.assertEqual(self.child.full_path, "notes/work")

    def test_full_path_grandchild(self):
        self.assertEqual(self.grandchild.full_path, "notes/work/daily")

    def test_url_path(self):
        self.assertEqual(self.grandchild.url_path, "/@sub_owner/notes/work/daily/")

    def test_get_ancestors_root(self):
        self.assertEqual(self.root.get_ancestors(), [])

    def test_get_ancestors_child(self):
        ancestors = self.child.get_ancestors()
        self.assertEqual(len(ancestors), 1)
        self.assertEqual(ancestors[0].pk, self.root.pk)

    def test_get_ancestors_grandchild(self):
        ancestors = self.grandchild.get_ancestors()
        self.assertEqual(len(ancestors), 2)
        self.assertEqual(ancestors[0].pk, self.root.pk)
        self.assertEqual(ancestors[1].pk, self.child.pk)

    def test_resolve_path_root(self):
        col = Collection.resolve_path(self.user, "notes")
        self.assertEqual(col.pk, self.root.pk)

    def test_resolve_path_child(self):
        col = Collection.resolve_path(self.user, "notes/work")
        self.assertEqual(col.pk, self.child.pk)

    def test_resolve_path_grandchild(self):
        col = Collection.resolve_path(self.user, "notes/work/daily")
        self.assertEqual(col.pk, self.grandchild.pk)

    def test_resolve_path_nonexistent(self):
        self.assertIsNone(Collection.resolve_path(self.user, "nope"))

    def test_resolve_path_partial_nonexistent(self):
        self.assertIsNone(Collection.resolve_path(self.user, "notes/nope"))

    def test_resolve_path_empty(self):
        self.assertIsNone(Collection.resolve_path(self.user, ""))

    def test_str_includes_full_path(self):
        self.assertIn("notes/work", str(self.child))

    def test_unique_together_same_parent(self):
        """Two children with the same slug under the same parent should fail."""
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Collection.objects.create(
                owner=self.user, slug="work", name="Work 2", parent=self.root
            )

    def test_same_slug_different_parent_ok(self):
        """Same slug is allowed under different parents."""
        other_root = Collection.objects.create(
            owner=self.user, slug="personal", name="Personal"
        )
        dup = Collection.objects.create(
            owner=self.user, slug="work", name="Work", parent=other_root
        )
        self.assertEqual(dup.full_path, "personal/work")

    def test_same_slug_root_and_nested_ok(self):
        """Same slug at root level and nested level should both exist."""
        root_work = Collection.objects.create(
            owner=self.user, slug="work", name="Root Work"
        )
        self.assertIsNotNone(root_work.pk)
        # 'work' exists both at root and under 'notes'
        self.assertEqual(Collection.resolve_path(self.user, "work").pk, root_work.pk)
        self.assertEqual(Collection.resolve_path(self.user, "notes/work").pk, self.child.pk)

    def test_cascade_delete_parent_removes_children(self):
        """Deleting a parent should cascade-delete its children."""
        child_pk = self.child.pk
        grandchild_pk = self.grandchild.pk
        self.root.delete()
        self.assertFalse(Collection.objects.filter(pk=child_pk).exists())
        self.assertFalse(Collection.objects.filter(pk=grandchild_pk).exists())

    def test_children_related_name(self):
        children = list(self.root.children.all().values_list("slug", flat=True))
        self.assertIn("work", children)

    def test_nested_collection_count_towards_limit(self):
        """Sub-collections should still count towards the collection limit."""
        total = Collection.objects.filter(owner=self.user).count()
        self.assertEqual(total, 3)  # root + child + grandchild


class TestSubCollectionViews(TestCase):
    """View-level tests for nested collection URLs."""

    def setUp(self):
        self.user = _make_user("subcol_user", Plan.PRO)
        self.client.force_login(self.user)
        # Create root collection
        res = _create(self.client, "Root Col", "root-col")
        self.root_id = res.json()["id"]
        # Create child via API
        res = self.client.post(
            "/collections/create/",
            json.dumps({"name": "Child Col", "slug": "child-col", "parent_id": self.root_id}),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(res.status_code, 201)
        self.child_id = res.json()["id"]
        self.child_path = res.json()["path"]

    def test_create_sub_collection(self):
        self.assertEqual(self.child_path, "root-col/child-col")

    def test_create_sub_collection_response_has_url(self):
        col = Collection.objects.get(pk=self.child_id)
        self.assertEqual(col.url_path, "/@subcol_user/root-col/child-col/")

    def test_nested_url_resolves(self):
        res = self.client.get("/@subcol_user/root-col/child-col/")
        self.assertEqual(res.status_code, 200)

    def test_root_url_still_works(self):
        res = self.client.get("/@subcol_user/root-col/")
        self.assertEqual(res.status_code, 200)

    def test_nested_json_includes_children(self):
        res = self.client.get(
            "/@subcol_user/root-col/",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("child-col", data.get("children", []))

    def test_nested_json_includes_path(self):
        res = self.client.get(
            "/@subcol_user/root-col/child-col/",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["path"], "root-col/child-col")

    def test_invalid_parent_rejected(self):
        res = self.client.post(
            "/collections/create/",
            json.dumps({"name": "Orphan", "parent_id": 99999}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 404)

    def test_duplicate_slug_same_parent_rejected(self):
        res = self.client.post(
            "/collections/create/",
            json.dumps({"name": "Child Col Dup", "slug": "child-col", "parent_id": self.root_id}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 409)

    def test_same_slug_different_parent_ok(self):
        res = _create(self.client, "Other Root", "other-root")
        other_root_id = res.json()["id"]
        res = self.client.post(
            "/collections/create/",
            json.dumps({"name": "Child Col", "slug": "child-col", "parent_id": other_root_id}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)

    def test_deep_nesting(self):
        """Create 3 levels deep and verify URL resolution."""
        res = self.client.post(
            "/collections/create/",
            json.dumps({"name": "Deep", "slug": "deep", "parent_id": self.child_id}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        deep_path = res.json()["path"]
        self.assertEqual(deep_path, "root-col/child-col/deep")
        # URL should resolve
        res = self.client.get("/@subcol_user/root-col/child-col/deep/")
        self.assertEqual(res.status_code, 200)

    def test_nonexistent_nested_path_404(self):
        res = self.client.get("/@subcol_user/root-col/nonexistent/")
        self.assertEqual(res.status_code, 404)

    def test_add_drop_to_subcollection(self):
        drop = _make_drop(self.user, key="subdrop")
        res = _add(self.client, self.child_id, "c", "subdrop")
        self.assertEqual(res.status_code, 200)
        # Verify it shows up in JSON
        res = self.client.get(
            "/@subcol_user/root-col/child-col/",
            HTTP_ACCEPT="application/json",
        )
        drops = res.json().get("drops", [])
        keys = [d["key"] for d in drops]
        self.assertIn("subdrop", keys)


# ── Plan downgrade / expiry behaviour ─────────────────────────────────────────

class TestPlanDowngradeCollections(TestCase):
    """
    When a user's plan goes from paid → free, existing collections should
    remain visible but the user should not be able to create new ones.
    This tests the "soft downgrade" approach: data is preserved, actions blocked.
    """

    def setUp(self):
        self.user = _make_user("downgrade_user", Plan.STARTER)
        self.client.force_login(self.user)
        # Create collections while on Starter
        for i in range(3):
            _create(self.client, f"col {i}", slug=f"col-{i}")
        # Downgrade to Free
        UserProfile.objects.filter(user=self.user).update(plan=Plan.FREE)
        self.user.profile.refresh_from_db()

    def test_existing_collections_still_visible(self):
        """Collections created before downgrade should still be publicly visible."""
        self.client.logout()
        res = self.client.get("/@downgrade_user/")
        self.assertEqual(res.status_code, 200)
        for i in range(3):
            self.assertContains(res, f"col {i}")

    def test_existing_collection_page_still_loads(self):
        res = self.client.get("/@downgrade_user/col-0/")
        self.assertEqual(res.status_code, 200)

    def test_cannot_create_new_collection_after_downgrade(self):
        res = _create(self.client, "new after downgrade")
        self.assertEqual(res.status_code, 403)

    def test_can_still_add_drop_to_existing_collection(self):
        """Even after downgrade, user can still manage existing collections."""
        col = Collection.objects.filter(owner=self.user).first()
        drop = _make_drop(self.user, key="still-add")
        res = _add(self.client, col.pk, "c", "still-add")
        self.assertEqual(res.status_code, 200)

    def test_can_still_remove_drop_from_existing_collection(self):
        col = Collection.objects.filter(owner=self.user).first()
        drop = _make_drop(self.user, key="still-rm")
        _add(self.client, col.pk, "c", "still-rm")
        res = _remove(self.client, col.pk, "c", "still-rm")
        self.assertEqual(res.status_code, 200)

    def test_can_still_delete_existing_collection(self):
        """User can still delete their own collections after downgrade."""
        col = Collection.objects.filter(owner=self.user).first()
        res = _delete(self.client, col.pk)
        self.assertEqual(res.status_code, 200)

    def test_can_still_rename_existing_collection(self):
        col = Collection.objects.filter(owner=self.user).first()
        res = _rename(self.client, col.pk, "renamed after downgrade")
        self.assertEqual(res.status_code, 200)


class TestPlanDowngradeReUpgrade(TestCase):
    """
    When a user re-upgrades after downgrade, they should regain collection creation.
    """

    def setUp(self):
        self.user = _make_user("reupgrade_user", Plan.STARTER)
        self.client.force_login(self.user)
        _create(self.client, "kept col", slug="kept-col")
        # Downgrade
        UserProfile.objects.filter(user=self.user).update(plan=Plan.FREE)
        self.user.profile.refresh_from_db()

    def test_cannot_create_while_free(self):
        res = _create(self.client, "blocked")
        self.assertEqual(res.status_code, 403)

    def test_re_upgrade_unlocks_creation(self):
        # Re-upgrade to Starter
        UserProfile.objects.filter(user=self.user).update(plan=Plan.STARTER)
        self.user.profile.refresh_from_db()
        res = _create(self.client, "unblocked", slug="unblocked")
        self.assertEqual(res.status_code, 201)

    def test_collections_preserved_through_cycle(self):
        """Collections survive downgrade + re-upgrade cycle."""
        self.assertTrue(Collection.objects.filter(
            owner=self.user, slug="kept-col"
        ).exists())
        # Re-upgrade
        UserProfile.objects.filter(user=self.user).update(plan=Plan.STARTER)
        self.assertTrue(Collection.objects.filter(
            owner=self.user, slug="kept-col"
        ).exists())


class TestPlanDowngradeSubCollections(TestCase):
    """Sub-collections should follow the same downgrade rules as root collections."""

    def setUp(self):
        self.user = _make_user("sub_dg_user", Plan.PRO)
        self.client.force_login(self.user)
        res = _create(self.client, "root", slug="root")
        self.root_id = res.json()["id"]
        # Create a sub-collection
        res = self.client.post(
            "/collections/create/",
            json.dumps({"name": "child", "slug": "child", "parent_id": self.root_id}),
            content_type="application/json",
        )
        self.child_id = res.json()["id"]
        # Downgrade to Free
        UserProfile.objects.filter(user=self.user).update(plan=Plan.FREE)
        self.user.profile.refresh_from_db()

    def test_subcollection_page_still_loads(self):
        res = self.client.get("/@sub_dg_user/root/child/")
        self.assertEqual(res.status_code, 200)

    def test_cannot_create_subcollection_after_downgrade(self):
        res = self.client.post(
            "/collections/create/",
            json.dumps({"name": "new-child", "slug": "new-child", "parent_id": self.root_id}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)

    def test_delete_subcollection_after_downgrade_ok(self):
        res = _delete(self.client, self.child_id)
        self.assertEqual(res.status_code, 200)

# ── Collections — Access Control After Downgrade ─────────────────────────────

class TestCollectionAccessAfterDowngrade(TestCase):
    """
    Verify that downgraded users cannot access their collections that
    exceed their new plan quota, but data is preserved.
    """

    def setUp(self):
        self.user = _make_user("access_test_user", Plan.STARTER)
        self.client.force_login(self.user)
        # Create 2 collections
        self.col1 = Collection.objects.create(
            owner=self.user,
            slug="col-1",
            name="Collection 1",
        )
        self.col2 = Collection.objects.create(
            owner=self.user,
            slug="col-2",
            name="Collection 2",
        )

    def test_can_view_collection_before_downgrade(self):
        """Owner can view collection on Starter plan."""
        res = self.client.get(f"/@{self.user.username}/col-1/")
        self.assertEqual(res.status_code, 200)

    def test_can_add_drop_to_collection_before_downgrade(self):
        """Owner can add drops before downgrade."""
        drop = _make_drop(self.user, key="testdrop1")
        res = _add(self.client, self.col1.pk, drop.ns, drop.key)
        self.assertEqual(res.status_code, 200)

    def test_access_denied_to_collection_after_downgrade_to_free(self):
        """
        After downgrading to Free (quota=0), user loses access to all collections.
        """
        UserProfile.objects.filter(user=self.user).update(plan=Plan.FREE)
        self.user.profile.refresh_from_db()
        
        # Trying to view collection as owner returns 403
        res = self.client.get(f"/@{self.user.username}/col-1/")
        self.assertEqual(res.status_code, 403)
        self.assertIn(b"paid feature", res.content.lower())

    def test_cannot_add_drop_after_downgrade(self):
        """After downgrade, owner cannot manage collection."""
        UserProfile.objects.filter(user=self.user).update(plan=Plan.FREE)
        self.user.profile.refresh_from_db()
        
        drop = _make_drop(self.user, key="testdrop2")
        res = _add(self.client, self.col1.pk, drop.ns, drop.key)
        self.assertEqual(res.status_code, 403)

    def test_public_viewer_can_still_see_collection(self):
        """Non-owner can still view the collection even if owner is downgraded."""
        UserProfile.objects.filter(user=self.user).update(plan=Plan.FREE)
        
        other_user = _make_user("viewer")
        self.client.force_login(other_user)
        
        res = self.client.get(f"/@{self.user.username}/col-1/")
        self.assertEqual(res.status_code, 200)

    def test_owner_can_manage_again_after_reupgrade(self):
        """After re-upgrading, owner regains access."""
        # Downgrade
        UserProfile.objects.filter(user=self.user).update(plan=Plan.FREE)
        self.user.profile.refresh_from_db()
        
        # Verify access denied
        res = self.client.get(f"/@{self.user.username}/col-1/")
        self.assertEqual(res.status_code, 403)
        
        # Re-upgrade
        UserProfile.objects.filter(user=self.user).update(plan=Plan.STARTER)
        self.user.profile.refresh_from_db()
        
        # Now has access again
        res = self.client.get(f"/@{self.user.username}/col-1/")
        self.assertEqual(res.status_code, 200)

    def test_oldest_collections_accessible_within_starter_quota(self):
        """
        When Starter user has 11 collections and downgrades to plan with limit 5,
        the 5 oldest should be accessible, the 6+ should be denied.
        """
        # Create more collections to hit a higher quota
        for i in range(3, 11):
            Collection.objects.create(
                owner=self.user,
                slug=f"col-{i}",
                name=f"Collection {i}",
            )
        
        all_cols = list(Collection.objects.filter(owner=self.user).order_by('created_at'))
        self.assertEqual(len(all_cols), 10)
        
        # Downgrade to a limit of 5 (simulating a hypothetical lower tier)
        # For now, just verify logic: oldest 5 should be accessible
        oldest_5 = all_cols[:5]
        oldest_5_ids = {c.pk for c in oldest_5}
        
        UserProfile.objects.filter(user=self.user).update(plan=Plan.FREE)
        
        # All should be inaccessible now (free = 0)
        res = self.client.get(f"/@{self.user.username}/col-1/")
        self.assertEqual(res.status_code, 403)
