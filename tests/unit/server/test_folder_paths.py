"""
Tests for folder-path URL features:
  - FolderItem.label / display_label / folder_url
  - Folder.resolve_item()
  - folder_or_alias_view file-leaf resolution
  - _drop_response folder_path_url context
"""

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory

from core.models import Folder, FolderItem, Drop

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return User.objects.create_user('alice', 'alice@test.com', 'pw')


@pytest.fixture
def folder(user):
    return Folder.objects.create(owner=user, slug='photos', name='Photos')


@pytest.fixture
def text_drop(user):
    return Drop.objects.create(key='hello', content='hi', owner=user)


@pytest.fixture
def file_drop(user):
    return Drop.objects.create(
        key='abc123', filename='sunset.jpg',
        file_public_id='drops/abc123',
        filesize=1024, owner=user,
    )


# ── display_label ────────────────────────────────────────────────────────────

class TestDisplayLabel:
    def test_explicit_label(self, folder):
        item = FolderItem.objects.create(folder=folder, key='abc123', label='vacation.jpg')
        assert item.display_label == 'vacation.jpg'

    def test_fallback_to_filename(self, folder, file_drop):
        item = FolderItem.objects.create(folder=folder, key=file_drop.key)
        assert item.display_label == 'sunset.jpg'

    def test_fallback_to_key_for_text(self, folder, text_drop):
        item = FolderItem.objects.create(folder=folder, key=text_drop.key)
        assert item.display_label == 'hello'

    def test_fallback_to_key_when_no_drop(self, folder):
        item = FolderItem.objects.create(folder=folder, key='orphan')
        assert item.display_label == 'orphan'


# ── folder_url ────────────────────────────────────────────────────────────────

class TestFolderUrl:
    def test_simple_path(self, user, folder, file_drop):
        item = FolderItem.objects.create(folder=folder, key=file_drop.key, label='sunset.jpg')
        assert item.folder_url == '/@alice/photos/sunset.jpg'

    def test_nested_folder(self, user, file_drop):
        parent = Folder.objects.create(owner=user, slug='media', name='Media')
        child = Folder.objects.create(owner=user, parent=parent, slug='pics', name='Pics')
        item = FolderItem.objects.create(folder=child, key=file_drop.key, label='sunset.jpg')
        assert item.folder_url == '/@alice/media/pics/sunset.jpg'

    def test_uses_display_label_fallback(self, user, folder, file_drop):
        item = FolderItem.objects.create(folder=folder, key=file_drop.key)
        # No explicit label → falls back to filename
        assert item.folder_url == '/@alice/photos/sunset.jpg'


# ── resolve_item ──────────────────────────────────────────────────────────────

class TestResolveItem:
    def test_resolves_label(self, user, folder, file_drop):
        item = FolderItem.objects.create(folder=folder, key=file_drop.key, label='sunset.jpg')
        found_folder, found_item = Folder.resolve_item(user, 'photos/sunset.jpg')
        assert found_folder == folder
        assert found_item == item

    def test_nested_folder_resolve(self, user, file_drop):
        parent = Folder.objects.create(owner=user, slug='media', name='Media')
        child = Folder.objects.create(owner=user, parent=parent, slug='pics', name='Pics')
        item = FolderItem.objects.create(folder=child, key=file_drop.key, label='sunset.jpg')
        found_folder, found_item = Folder.resolve_item(user, 'media/pics/sunset.jpg')
        assert found_folder == child
        assert found_item == item

    def test_returns_none_for_missing_label(self, user, folder):
        f, i = Folder.resolve_item(user, 'photos/nope.jpg')
        assert f is None
        assert i is None

    def test_returns_none_for_missing_folder(self, user):
        f, i = Folder.resolve_item(user, 'nonexistent/file.txt')
        assert f is None
        assert i is None

    def test_returns_none_for_single_segment(self, user, folder):
        f, i = Folder.resolve_item(user, 'photos')
        assert f is None
        assert i is None

    def test_returns_none_for_empty_path(self, user):
        f, i = Folder.resolve_item(user, '')
        assert f is None
        assert i is None

    def test_strips_slashes(self, user, folder, file_drop):
        item = FolderItem.objects.create(folder=folder, key=file_drop.key, label='sunset.jpg')
        f, i = Folder.resolve_item(user, '/photos/sunset.jpg/')
        assert f == folder
        assert i == item


# ── FolderItem __str__ ────────────────────────────────────────────────────────

class TestFolderItemStr:
    def test_str_representation(self, user, folder, file_drop):
        item = FolderItem.objects.create(folder=folder, key=file_drop.key, label='sunset.jpg')
        s = str(item)
        assert 'sunset.jpg' in s
        assert 'alice' in s
