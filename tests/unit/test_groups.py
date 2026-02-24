"""
tests/unit/test_groups.py

Unit tests for Group, GroupMembership, and invite flow.
"""

import json

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import (
    Group, GroupMembership, GroupInviteToken,
    Plan, UserProfile,
)


def _make_user(username, plan=Plan.FREE, password="pw"):
    u = User.objects.create_user(username, email=f"{username}@test.com", password=password)
    UserProfile.objects.filter(user=u).update(plan=plan)
    u.refresh_from_db()
    return u


class TestGroupModel(TestCase):
    def test_group_str(self):
        g = Group.objects.create(handle="myteam", name="My Team")
        self.assertEqual(str(g), "@myteam")

    def test_membership_roles(self):
        g = Group.objects.create(handle="team1", name="Team 1")
        u = _make_user("member1")
        m = GroupMembership.objects.create(group=g, user=u, role=GroupMembership.ROLE_WRITER)
        self.assertEqual(m.role, "writer")

    def test_invite_token_single_use(self):
        g = Group.objects.create(handle="team2", name="Team 2")
        u = _make_user("admin2", Plan.STARTER)
        invite = GroupInviteToken.objects.create(
            group=g, token="test123", role=GroupMembership.ROLE_READER,
            created_by=u, max_uses=1, use_count=0,
        )
        self.assertFalse(invite.is_expired())
        invite.use_count = 1
        self.assertTrue(invite.is_expired())


class TestGroupCreateView(TestCase):
    def setUp(self):
        self.free_user = _make_user("free_grp", Plan.FREE)
        self.starter_user = _make_user("starter_grp", Plan.STARTER)

    def test_free_cannot_create_group(self):
        self.client.force_login(self.free_user)
        res = self.client.post(
            "/groups/create/",
            json.dumps({"handle": "myteam", "name": "My Team"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)

    def test_paid_can_create_group(self):
        self.client.force_login(self.starter_user)
        res = self.client.post(
            "/groups/create/",
            json.dumps({"handle": "paidteam", "name": "Paid Team"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["handle"], "paidteam")
        # Creator should be admin
        self.assertTrue(
            GroupMembership.objects.filter(
                group__handle="paidteam",
                user=self.starter_user,
                role=GroupMembership.ROLE_ADMIN,
            ).exists()
        )

    def test_duplicate_handle_rejected(self):
        self.client.force_login(self.starter_user)
        self.client.post(
            "/groups/create/",
            json.dumps({"handle": "dupteam"}),
            content_type="application/json",
        )
        res = self.client.post(
            "/groups/create/",
            json.dumps({"handle": "dupteam"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 409)

    def test_handle_conflict_with_username(self):
        self.client.force_login(self.starter_user)
        res = self.client.post(
            "/groups/create/",
            json.dumps({"handle": self.free_user.username}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 409)


class TestGroupInviteJoin(TestCase):
    def setUp(self):
        self.admin = _make_user("grp_admin", Plan.STARTER)
        self.joiner = _make_user("grp_joiner", Plan.FREE)
        self.client.force_login(self.admin)
        res = self.client.post(
            "/groups/create/",
            json.dumps({"handle": "inviteteam", "name": "Invite Team"}),
            content_type="application/json",
        )
        self.group = Group.objects.get(handle="inviteteam")

    def test_admin_can_create_invite(self):
        res = self.client.post(
            f"/groups/{self.group.pk}/invite/",
            json.dumps({"role": "writer"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertIn("token", res.json())

    def test_non_admin_cannot_invite(self):
        # joiner is not a member yet
        self.client.force_login(self.joiner)
        res = self.client.post(
            f"/groups/{self.group.pk}/invite/",
            json.dumps({"role": "reader"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)

    def test_join_with_valid_token(self):
        # Create invite
        res = self.client.post(
            f"/groups/{self.group.pk}/invite/",
            json.dumps({"role": "reader", "max_uses": 1}),
            content_type="application/json",
        )
        token = res.json()["token"]

        # Switch to joiner
        self.client.force_login(self.joiner)
        res = self.client.post(
            "/groups/join/",
            json.dumps({"token": token}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(
            GroupMembership.objects.filter(
                group=self.group, user=self.joiner
            ).exists()
        )

    def test_join_with_invalid_token(self):
        self.client.force_login(self.joiner)
        res = self.client.post(
            "/groups/join/",
            json.dumps({"token": "bogus"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 404)

    def test_non_member_blocked(self):
        """Non-member accessing group sees is_member=false."""
        self.client.force_login(self.joiner)
        res = self.client.get(
            f"/@inviteteam/",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["is_member"])


class TestRoleEnforcement(TestCase):
    def setUp(self):
        self.admin = _make_user("role_admin", Plan.STARTER)
        self.member = _make_user("role_member", Plan.FREE)
        self.client.force_login(self.admin)
        self.client.post(
            "/groups/create/",
            json.dumps({"handle": "roleteam"}),
            content_type="application/json",
        )
        self.group = Group.objects.get(handle="roleteam")
        # Add member as reader
        GroupMembership.objects.create(
            group=self.group, user=self.member, role=GroupMembership.ROLE_READER,
        )

    def test_admin_can_change_role(self):
        res = self.client.post(
            f"/groups/{self.group.pk}/members/{self.member.pk}/role/",
            json.dumps({"role": "writer"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        m = GroupMembership.objects.get(group=self.group, user=self.member)
        self.assertEqual(m.role, "writer")

    def test_non_admin_cannot_change_role(self):
        self.client.force_login(self.member)
        res = self.client.post(
            f"/groups/{self.group.pk}/members/{self.admin.pk}/role/",
            json.dumps({"role": "reader"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)

    def test_admin_can_remove_member(self):
        res = self.client.post(
            f"/groups/{self.group.pk}/members/{self.member.pk}/remove/",
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(
            GroupMembership.objects.filter(
                group=self.group, user=self.member
            ).exists()
        )

# ── Group Plan Downgrade Tests ───────────────────────────────────────────────────

class TestPlanDowngradeGroups(TestCase):
    """
    When a user's plan goes from paid → free, existing groups should
    remain visible but the user (group creator) cannot manage them.
    This tests the "soft downgrade" approach: data is preserved, actions blocked.
    """

    def setUp(self):
        self.user = _make_user("downgrade_group_user", Plan.STARTER)
        self.client.force_login(self.user)
        # Create 3 groups while on Starter
        for i in range(3):
            Group.objects.create(
                handle=f"dg-group-{i}",
                name=f"Downgrade Group {i}",
                created_by=self.user,
            )
            # Add user as admin
            GroupMembership.objects.create(
                group=Group.objects.get(handle=f"dg-group-{i}"),
                user=self.user,
                role=GroupMembership.ROLE_ADMIN,
            )
        # Downgrade to Free
        UserProfile.objects.filter(user=self.user).update(plan=Plan.FREE)
        self.user.profile.refresh_from_db()

    def test_groups_still_exist_after_downgrade(self):
        """Groups created before downgrade should still exist in DB."""
        self.assertEqual(Group.objects.filter(created_by=self.user).count(), 3)

    def test_cannot_create_new_group_after_downgrade(self):
        """Free user cannot create new groups."""
        res = self.client.post(
            "/groups/create/",
            json.dumps({"handle": "newgroupfail", "name": "New Group"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)

    def test_cannot_invite_to_owned_group_after_downgrade(self):
        """Creator cannot manage (invite) their groups after downgrade."""
        group = Group.objects.filter(created_by=self.user).first()
        res = self.client.post(
            f"/groups/{group.pk}/invite/",
            json.dumps({"role": "reader", "max_uses": 1}),
            content_type="application/json",
        )
        # Access denied due to plan downgrade
        self.assertEqual(res.status_code, 403)
        self.assertIn(b"paid feature", res.content.lower())

    def test_cannot_change_member_role_after_downgrade(self):
        """Admin cannot manage members of group after downgrade."""
        group = Group.objects.filter(created_by=self.user).first()
        other_user = _make_user("other_member")
        GroupMembership.objects.create(
            group=group, user=other_user, role=GroupMembership.ROLE_READER
        )
        res = self.client.post(
            f"/groups/{group.pk}/members/{other_user.pk}/role/",
            json.dumps({"role": "writer"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)

    def test_cannot_remove_member_after_downgrade(self):
        """Admin cannot remove members after downgrade."""
        group = Group.objects.filter(created_by=self.user).first()
        other_user = _make_user("other_member2")
        GroupMembership.objects.create(
            group=group, user=other_user, role=GroupMembership.ROLE_READER
        )
        res = self.client.post(
            f"/groups/{group.pk}/members/{other_user.pk}/remove/",
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)

    def test_other_admin_can_still_manage_group(self):
        """Other admins (not the creator) can still manage the group."""
        group = Group.objects.filter(created_by=self.user).first()
        other_user = _make_user("other_admin")
        GroupMembership.objects.create(
            group=group, user=other_user, role=GroupMembership.ROLE_ADMIN
        )
        
        self.client.force_login(other_user)
        res = self.client.post(
            f"/groups/{group.pk}/invite/",
            json.dumps({"role": "reader", "max_uses": 1}),
            content_type="application/json",
        )
        # Other admin can still manage
        self.assertEqual(res.status_code, 201)


class TestPlanDowngradeGroupReUpgrade(TestCase):
    """
    When a user re-upgrades after downgrade, they should regain group
    management access.
    """

    def setUp(self):
        self.user = _make_user("reupgrade_group_user", Plan.STARTER)
        self.client.force_login(self.user)
        self.group = Group.objects.create(
            handle="reupgrade-group",
            name="Reupgrade Group",
            created_by=self.user,
        )
        GroupMembership.objects.create(
            group=self.group, user=self.user, role=GroupMembership.ROLE_ADMIN
        )
        # Downgrade
        UserProfile.objects.filter(user=self.user).update(plan=Plan.FREE)
        self.user.profile.refresh_from_db()

    def test_cannot_invite_while_free(self):
        res = self.client.post(
            f"/groups/{self.group.pk}/invite/",
            json.dumps({"role": "reader"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)

    def test_re_upgrade_unlocks_group_management(self):
        # Re-upgrade to Starter
        UserProfile.objects.filter(user=self.user).update(plan=Plan.STARTER)
        self.user.profile.refresh_from_db()
        res = self.client.post(
            f"/groups/{self.group.pk}/invite/",
            json.dumps({"role": "reader", "max_uses": 1}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)

    def test_group_persists_through_cycle(self):
        """Group survives downgrade + re-upgrade cycle."""
        self.assertTrue(
            Group.objects.filter(
                handle="reupgrade-group", created_by=self.user
            ).exists()
        )
        # Re-upgrade
        UserProfile.objects.filter(user=self.user).update(plan=Plan.STARTER)
        self.assertTrue(
            Group.objects.filter(
                handle="reupgrade-group", created_by=self.user
            ).exists()
        )