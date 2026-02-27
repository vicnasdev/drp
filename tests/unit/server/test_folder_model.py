"""
Tests for Folder, FolderItem, FolderMember, FolderInviteToken models.

Covers path resolution, ancestry, membership, invite tokens.
"""

import pytest
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import User

from core.models import Folder, FolderItem, FolderMember, FolderInviteToken, Drop

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return User.objects.create_user('alice', 'alice@test.com', 'pw')


@pytest.fixture
def other_user(db):
    return User.objects.create_user('bob', 'bob@test.com', 'pw')


# ── Folder creation & paths ──────────────────────────────────────────────────

class TestFolderPaths:
    def test_full_path_single_level(self, user):
        f = Folder.objects.create(owner=user, slug='notes', name='Notes')
        assert f.full_path == 'notes'

    def test_full_path_nested(self, user):
        parent = Folder.objects.create(owner=user, slug='docs', name='Docs')
        child = Folder.objects.create(owner=user, parent=parent, slug='work', name='Work')
        assert child.full_path == 'docs/work'

    def test_full_path_deeply_nested(self, user):
        a = Folder.objects.create(owner=user, slug='a', name='A')
        b = Folder.objects.create(owner=user, parent=a, slug='b', name='B')
        c = Folder.objects.create(owner=user, parent=b, slug='c', name='C')
        assert c.full_path == 'a/b/c'

    def test_url_path(self, user):
        f = Folder.objects.create(owner=user, slug='notes', name='Notes')
        assert f.url_path == '/@alice/notes/'

    def test_str_includes_username(self, user):
        f = Folder.objects.create(owner=user, slug='notes', name='Notes')
        assert '@alice' in str(f)
        assert 'notes' in str(f)


# ── Ancestry ─────────────────────────────────────────────────────────────────

class TestFolderAncestry:
    def test_root_has_no_ancestors(self, user):
        f = Folder.objects.create(owner=user, slug='top', name='Top')
        assert f.get_ancestors() == []

    def test_child_has_one_ancestor(self, user):
        parent = Folder.objects.create(owner=user, slug='parent', name='Parent')
        child = Folder.objects.create(owner=user, parent=parent, slug='child', name='Child')
        ancestors = child.get_ancestors()
        assert len(ancestors) == 1
        assert ancestors[0].pk == parent.pk

    def test_grandchild_ancestors_ordered_root_first(self, user):
        a = Folder.objects.create(owner=user, slug='a', name='A')
        b = Folder.objects.create(owner=user, parent=a, slug='b', name='B')
        c = Folder.objects.create(owner=user, parent=b, slug='c', name='C')
        ancestors = c.get_ancestors()
        assert [x.slug for x in ancestors] == ['a', 'b']


# ── resolve_path ──────────────────────────────────────────────────────────────

class TestFolderResolvePath:
    def test_resolve_single_segment(self, user):
        f = Folder.objects.create(owner=user, slug='notes', name='Notes')
        assert Folder.resolve_path(user, 'notes') == f

    def test_resolve_nested_path(self, user):
        parent = Folder.objects.create(owner=user, slug='docs', name='Docs')
        child = Folder.objects.create(owner=user, parent=parent, slug='work', name='Work')
        assert Folder.resolve_path(user, 'docs/work') == child

    def test_resolve_empty_returns_none(self, user):
        assert Folder.resolve_path(user, '') is None

    def test_resolve_nonexistent_returns_none(self, user):
        assert Folder.resolve_path(user, 'does/not/exist') is None

    def test_resolve_strips_slashes(self, user):
        f = Folder.objects.create(owner=user, slug='notes', name='Notes')
        assert Folder.resolve_path(user, '/notes/') == f


# ── can_edit ──────────────────────────────────────────────────────────────────

class TestFolderCanEdit:
    def test_owner_can_edit(self, user):
        f = Folder.objects.create(owner=user, slug='x', name='X')
        assert f.can_edit(user)

    def test_other_cannot_edit(self, user, other_user):
        f = Folder.objects.create(owner=user, slug='x', name='X')
        assert not f.can_edit(other_user)

    def test_admin_member_can_edit(self, user, other_user):
        f = Folder.objects.create(owner=user, slug='x', name='X')
        FolderMember.objects.create(folder=f, user=other_user, role=FolderMember.ROLE_ADMIN)
        assert f.can_edit(other_user)

    def test_reader_cannot_edit(self, user, other_user):
        f = Folder.objects.create(owner=user, slug='x', name='X')
        FolderMember.objects.create(folder=f, user=other_user, role=FolderMember.ROLE_READER)
        assert not f.can_edit(other_user)


# ── FolderItem ────────────────────────────────────────────────────────────────

class TestFolderItem:
    def test_add_item(self, user):
        f = Folder.objects.create(owner=user, slug='items', name='Items')
        item = FolderItem.objects.create(folder=f, key='mykey')
        assert item.url_path == '/mykey/'
        assert f.items.count() == 1

    def test_unique_key_per_folder(self, user):
        f = Folder.objects.create(owner=user, slug='items', name='Items')
        FolderItem.objects.create(folder=f, key='k1')
        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            FolderItem.objects.create(folder=f, key='k1')

    def test_same_key_different_folders(self, user):
        f1 = Folder.objects.create(owner=user, slug='a', name='A')
        f2 = Folder.objects.create(owner=user, slug='b', name='B')
        FolderItem.objects.create(folder=f1, key='k1')
        FolderItem.objects.create(folder=f2, key='k1')
        assert FolderItem.objects.filter(key='k1').count() == 2


# ── FolderInviteToken ────────────────────────────────────────────────────────

class TestFolderInviteToken:
    def test_not_expired_when_fresh(self, user):
        f = Folder.objects.create(owner=user, slug='inv', name='Inv')
        t = FolderInviteToken.objects.create(
            folder=f, token='abc123', created_by=user,
            expires_at=timezone.now() + timedelta(days=7))
        assert not t.is_expired()

    def test_expired_by_time(self, user):
        f = Folder.objects.create(owner=user, slug='inv2', name='Inv2')
        t = FolderInviteToken.objects.create(
            folder=f, token='def456', created_by=user,
            expires_at=timezone.now() - timedelta(hours=1))
        assert t.is_expired()

    def test_expired_by_max_uses(self, user):
        f = Folder.objects.create(owner=user, slug='inv3', name='Inv3')
        t = FolderInviteToken.objects.create(
            folder=f, token='ghi789', created_by=user,
            max_uses=1, use_count=1)
        assert t.is_expired()

    def test_not_expired_under_max_uses(self, user):
        f = Folder.objects.create(owner=user, slug='inv4', name='Inv4')
        t = FolderInviteToken.objects.create(
            folder=f, token='jkl012', created_by=user,
            max_uses=5, use_count=2)
        assert not t.is_expired()
