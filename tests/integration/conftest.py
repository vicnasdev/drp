import pytest
from django.contrib.auth.models import User

from core.models import UserProfile


@pytest.fixture
def user(db):
    u = User.objects.create_user(username="testbot", password="testpass")
    UserProfile.objects.create(user=u)
    return u
