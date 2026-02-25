from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import render, redirect
from django.urls import path
from django.utils.html import format_html

from .models import (
    UserProfile, Drop, BugReport, EmailVerification,
    Collection, CollectionMembership, PlanLimit,
    Group, GroupMembership, GroupInviteToken,
    APIToken, Alias, DropTemplate,
    FeatureProposal, FeatureVote, DropLike,
)


# ── Broadcast email form ──────────────────────────────────────────────────────

class BroadcastEmailForm:
    """Thin wrapper — we use a plain template form, no Django forms dep needed."""
    pass


# ── UserProfile inline ────────────────────────────────────────────────────────

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'profile'
    fields = ('plan', 'plan_since', 'storage_used_bytes', 'email_verified')
    readonly_fields = ('storage_used_bytes',)


# ── UserAdmin ─────────────────────────────────────────────────────────────────

class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('email', 'get_plan', 'get_storage', 'date_joined', 'is_active')
    search_fields = ('email', 'username')
    actions = ['broadcast_email_action']

    @admin.display(description='plan')
    def get_plan(self, obj):
        return obj.profile.plan if hasattr(obj, 'profile') else '—'

    @admin.display(description='storage used')
    def get_storage(self, obj):
        if not hasattr(obj, 'profile'):
            return '—'
        mb = obj.profile.storage_used_bytes / (1024 ** 2)
        return f'{mb:.1f} MB'

    # Custom URL for the broadcast page
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('broadcast-email/', self.admin_site.admin_view(self.broadcast_email_view),
                 name='auth_user_broadcast_email'),
        ]
        return custom + urls

    def broadcast_email_view(self, request):
        """Admin page to compose and send a broadcast email."""
        from django.contrib.auth.models import User

        groups = {
            'all': ('All users', User.objects.filter(is_active=True)),
            'free': ('Free accounts', User.objects.filter(is_active=True, profile__plan='free')),
            'starter': ('Starter accounts', User.objects.filter(is_active=True, profile__plan='starter')),
            'pro': ('Pro accounts', User.objects.filter(is_active=True, profile__plan='pro')),
            'paid': ('All paid accounts', User.objects.filter(is_active=True, profile__plan__in=['starter', 'pro'])),
        }

        if request.method == 'POST':
            group_key = request.POST.get('group', 'all')
            subject = request.POST.get('subject', '').strip()
            body_text = request.POST.get('body', '').strip()
            preview = request.POST.get('preview')

            _, qs = groups.get(group_key, groups['all'])
            recipients = list(qs.values_list('email', flat=True))

            if preview:
                # Show preview without sending
                return render(request, 'admin/broadcast_email.html', {
                    'title': 'Broadcast Email',
                    'groups': [(k, v[0]) for k, v in groups.items()],
                    'group_key': group_key,
                    'subject': subject,
                    'body': body_text,
                    'preview_recipients': recipients,
                    'preview_count': len(recipients),
                    'opts': self.model._meta,
                })

            if not subject or not body_text:
                messages.error(request, 'Subject and body are required.')
            elif not recipients:
                messages.warning(request, 'No recipients in that group.')
            else:
                # Send individually so each TO shows only their own address
                sent = 0
                failed = 0
                for email in recipients:
                    try:
                        send_mail(
                            subject=subject,
                            message=body_text,
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=[email],
                            fail_silently=False,
                        )
                        sent += 1
                    except Exception:
                        failed += 1

                if sent:
                    messages.success(request, f'Sent to {sent} user(s).' + (f' {failed} failed.' if failed else ''))
                else:
                    messages.error(request, f'All {failed} sends failed. Check your email backend.')
                return redirect('..')

        return render(request, 'admin/broadcast_email.html', {
            'title': 'Broadcast Email',
            'groups': [(k, v[0]) for k, v in groups.items()],
            'group_key': 'all',
            'subject': '',
            'body': '',
            'opts': self.model._meta,
        })

    @admin.action(description='📧 Broadcast email to selected users')
    def broadcast_email_action(self, request, queryset):
        """Redirect to broadcast page pre-scoped to selected users — handled via session."""
        request.session['broadcast_user_ids'] = list(queryset.values_list('id', flat=True))
        return redirect('admin:auth_user_broadcast_email')


admin.site.site_header = "drp"
admin.site.site_title  = "drp"
admin.site.index_title = "Dashboard"

admin.site.unregister(User)
admin.site.register(User, UserAdmin)


# ── Drop admin ────────────────────────────────────────────────────────────────

@admin.register(Drop)
class DropAdmin(admin.ModelAdmin):
    list_display = ('key', 'kind', 'owner', 'owner_group', 'locked', 'is_public', 'filesize', 'created_at', 'expires_at', 'visible_from')
    list_filter = ('kind', 'locked', 'is_public', 'burn')
    search_fields = ('key', 'owner__email', 'filename')
    readonly_fields = ('created_at', 'last_accessed_at', 'renewal_count', 'view_count', 'last_viewed_at')
    raw_id_fields = ('owner', 'owner_group')


# ── UserProfile admin ─────────────────────────────────────────────────────────

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'storage_used_bytes', 'email_verified', 'plan_since')
    list_filter = ('plan', 'email_verified')
    search_fields = ('user__email',)
    actions = ['upgrade_to_starter', 'upgrade_to_pro', 'downgrade_to_free']

    @admin.action(description='Upgrade to Starter')
    def upgrade_to_starter(self, request, queryset):
        from django.utils import timezone
        from .models import Plan
        queryset.update(plan=Plan.STARTER, plan_since=timezone.now())
        for profile in queryset:
            for drop in profile.user.drops.filter(expires_at__isnull=False):
                drop.recalculate_expiry_for_plan(Plan.STARTER)

    @admin.action(description='Upgrade to Pro')
    def upgrade_to_pro(self, request, queryset):
        from django.utils import timezone
        from .models import Plan
        queryset.update(plan=Plan.PRO, plan_since=timezone.now())
        for profile in queryset:
            for drop in profile.user.drops.filter(expires_at__isnull=False):
                drop.recalculate_expiry_for_plan(Plan.PRO)

    @admin.action(description='Downgrade to Free')
    def downgrade_to_free(self, request, queryset):
        from .models import Plan
        queryset.update(plan=Plan.FREE, plan_since=None)

# ── BugReport admin ───────────────────────────────────────────────────────────

@admin.register(BugReport)
class BugReportAdmin(admin.ModelAdmin):
    list_display  = ('created_at', 'category', 'user', 'hide_identity', 'short_desc', 'github_link')
    list_filter   = ('category', 'hide_identity')
    search_fields = ('description', 'user__email')
    readonly_fields = ('created_at', 'github_issue_url', 'user', 'category',
                       'description', 'hide_identity')

    @admin.display(description='description')
    def short_desc(self, obj):
        return obj.description[:60] + ('…' if len(obj.description) > 60 else '')

    @admin.display(description='issue')
    def github_link(self, obj):
        if obj.github_issue_url:
            return format_html('<a href="{}" target="_blank">view →</a>', obj.github_issue_url)
        return '—'


# ── EmailVerification admin ───────────────────────────────────────────────────

@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display  = ('user', 'created_at', 'is_expired')
    search_fields = ('user__email',)
    readonly_fields = ('user', 'token', 'created_at')


# ── Collection admin ──────────────────────────────────────────────────────────

class CollectionMembershipInline(admin.TabularInline):
    model = CollectionMembership
    extra = 0
    fields = ('ns', 'key', 'added_at')
    readonly_fields = ('added_at',)


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display  = ('__str__', 'owner', 'parent', 'owner_group', 'slug', 'public_inbox', 'member_count', 'created_at')
    list_filter   = ('owner__profile__plan', 'public_inbox')
    search_fields = ('slug', 'name', 'owner__username', 'owner__email')
    readonly_fields = ('created_at',)
    raw_id_fields = ('owner', 'owner_group', 'parent')
    inlines = (CollectionMembershipInline,)

    @admin.display(description='drops')
    def member_count(self, obj):
        return obj.memberships.count()

@admin.register(PlanLimit)
class PlanLimitAdmin(admin.ModelAdmin):
    list_display = (
        'plan', 'label', 'price_monthly',
        'max_file_mb', 'max_text_kb', 'storage_gb',
        'max_collections', 'max_groups', 'webhooks', 'api_keys', 'scheduled_drops',
        'password_protection', 'remote_upload',
    )
    ordering = ('price_monthly',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        PlanLimit.invalidate_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        PlanLimit.invalidate_cache()


# ── Group admin ─────────────────────────────────────────────────────────────────

class GroupMembershipInline(admin.TabularInline):
    model = GroupMembership
    extra = 0
    fields = ('user', 'role', 'joined_at')
    readonly_fields = ('joined_at',)
    raw_id_fields = ('user',)


class GroupInviteTokenInline(admin.TabularInline):
    model = GroupInviteToken
    extra = 0
    fields = ('token', 'role', 'max_uses', 'use_count', 'expires_at', 'created_at')
    readonly_fields = ('created_at', 'use_count')


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('handle', 'name', 'created_by', 'member_count', 'created_at')
    search_fields = ('handle', 'name')
    readonly_fields = ('created_at',)
    raw_id_fields = ('created_by',)
    inlines = (GroupMembershipInline, GroupInviteTokenInline)

    @admin.display(description='members')
    def member_count(self, obj):
        return obj.memberships.count()


# ── APIToken admin ──────────────────────────────────────────────────────────────

@admin.register(APIToken)
class APITokenAdmin(admin.ModelAdmin):
    list_display = ('prefix', 'user', 'label', 'created_at', 'expires_at', 'last_used')
    search_fields = ('prefix', 'user__email', 'label')
    readonly_fields = ('created_at', 'last_used', 'token_hash', 'prefix')
    raw_id_fields = ('user',)


# ── Alias admin ─────────────────────────────────────────────────────────────────

@admin.register(Alias)
class AliasAdmin(admin.ModelAdmin):
    list_display = ('alias', 'owner', 'ns', 'key', 'created_at')
    search_fields = ('alias', 'owner__email', 'key')
    readonly_fields = ('created_at',)
    raw_id_fields = ('owner',)


# ── DropTemplate admin ──────────────────────────────────────────────────────────

@admin.register(DropTemplate)
class DropTemplateAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'owner', 'owner_group', 'burn', 'password', 'created_at')
    search_fields = ('slug', 'name', 'owner__email')
    readonly_fields = ('created_at',)
    raw_id_fields = ('owner', 'owner_group')


# ── FeatureProposal + FeatureVote admin ─────────────────────────────────────────

class FeatureVoteInline(admin.TabularInline):
    model = FeatureVote
    extra = 0
    fields = ('user', 'weight', 'created_at')
    readonly_fields = ('created_at',)
    raw_id_fields = ('user',)


@admin.register(FeatureProposal)
class FeatureProposalAdmin(admin.ModelAdmin):
    list_display = ('title', 'proposed_by', 'total_weight', 'staff_pick', 'closed', 'created_at')
    list_filter = ('closed', 'staff_pick')
    list_editable = ('staff_pick',)
    search_fields = ('title', 'description')
    readonly_fields = ('created_at',)
    raw_id_fields = ('proposed_by',)
    inlines = (FeatureVoteInline,)
    actions = ['promote_to_github', 'close_proposals']

    @admin.action(description="Promote selected to GitHub issue & delete")
    def promote_to_github(self, request, queryset):
        from core.management.commands.promote_feature import (
            _ensure_label, _create_issue,
        )
        _ensure_label()
        ok, fail = 0, 0
        for proposal in queryset.filter(closed=False):
            score = proposal.total_weight()
            url = _create_issue(proposal, score)
            if url:
                proposal.delete()
                ok += 1
            else:
                fail += 1
        if ok:
            messages.success(request, f"{ok} proposal(s) promoted to GitHub.")
        if fail:
            messages.warning(request, f"{fail} proposal(s) failed (check GITHUB_ISSUES_TOKEN).")

    @admin.action(description="Close selected proposals (no issue)")
    def close_proposals(self, request, queryset):
        updated = queryset.update(closed=True)
        messages.success(request, f"{updated} proposal(s) closed.")


@admin.register(DropLike)
class DropLikeAdmin(admin.ModelAdmin):
    list_display = ('drop', 'user', 'created_at')
    raw_id_fields = ('drop', 'user')
    readonly_fields = ('created_at',)
