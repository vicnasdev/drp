from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import render, redirect
from django.urls import path
from django.utils.html import format_html

from .models import (
    UserProfile, PlanLimit,
    Folder, FolderGroup, FolderShareToken,
    Group, GroupMember,
    FileBookmark, FolderBookmark,
    Like, CrashReport,
    EmailTemplate,
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

        # Build domain for default from_email
        domain = getattr(settings, 'DOMAIN', 'localhost')
        if domain.startswith('http'):
            domain = domain.split('//')[1].rstrip('/')
        default_from = f'admin@{domain}'

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
            from_email = request.POST.get('from_email', '').strip() or default_from
            specific_email = request.POST.get('specific_email', '').strip()
            preview = request.POST.get('preview')

            # Determine recipients: specific user overrides group
            if specific_email:
                recipients = [specific_email]
            else:
                _, qs = groups.get(group_key, groups['all'])
                recipients = list(qs.values_list('email', flat=True))

            if preview:
                return render(request, 'admin/broadcast_email.html', {
                    'title': 'Broadcast Email',
                    'groups': [(k, v[0]) for k, v in groups.items()],
                    'group_key': group_key,
                    'subject': subject,
                    'body': body_text,
                    'from_email': from_email,
                    'default_from': default_from,
                    'specific_email': specific_email,
                    'preview_recipients': recipients,
                    'preview_count': len(recipients),
                    'opts': self.model._meta,
                })

            if not subject or not body_text:
                messages.error(request, 'Subject and body are required.')
            elif not recipients:
                messages.warning(request, 'No recipients in that group.')
            else:
                sent = 0
                failed = 0
                for email in recipients:
                    try:
                        send_mail(
                            subject=subject,
                            message=body_text,
                            from_email=from_email,
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
            'from_email': default_from,
            'default_from': default_from,
            'specific_email': '',
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

@admin.register(PlanLimit)
class PlanLimitAdmin(admin.ModelAdmin):
    list_display = (
        'plan', 'label', 'price_monthly',
        'max_file_mb', 'max_text_kb', 'storage_gb',
        'max_folders', 'webhooks', 'api_keys', 'scheduled_drops',
        'password_protection', 'remote_upload',
    )
    ordering = ('price_monthly',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        PlanLimit.invalidate_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        PlanLimit.invalidate_cache()


# ── Folder admin ────────────────────────────────────────────────────────────────

class FolderGroupInline(admin.TabularInline):
    model = FolderGroup
    extra = 0
    fields = ('group', 'role')
    raw_id_fields = ('group',)


class FolderShareTokenInline(admin.TabularInline):
    model = FolderShareToken
    extra = 0
    fields = ('token', 'created_by', 'expires_at', 'created_at')
    readonly_fields = ('token', 'created_at')
    raw_id_fields = ('created_by',)


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ('slug', 'owner', 'is_public', 'created_at')
    search_fields = ('slug',)
    list_filter = ('is_public',)
    readonly_fields = ('created_at',)
    raw_id_fields = ('owner', 'parent')
    inlines = (FolderGroupInline, FolderShareTokenInline)


# ── Group admin ─────────────────────────────────────────────────────────────────

class GroupMemberInline(admin.TabularInline):
    model = GroupMember
    extra = 0
    fields = ('user', 'role', 'joined_at')
    readonly_fields = ('joined_at',)
    raw_id_fields = ('user',)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'member_count')
    search_fields = ('name',)
    raw_id_fields = ('owner',)
    inlines = (GroupMemberInline,)

    @admin.display(description='members')
    def member_count(self, obj):
        return obj.members.count()


# ── Bookmark admin ──────────────────────────────────────────────────────────────

@admin.register(FileBookmark)
class FileBookmarkAdmin(admin.ModelAdmin):
    list_display = ('user', 'file_key', 'created_at')
    search_fields = ('file_key', 'user__username')
    raw_id_fields = ('user',)


@admin.register(FolderBookmark)
class FolderBookmarkAdmin(admin.ModelAdmin):
    list_display = ('user', 'folder', 'created_at')
    raw_id_fields = ('user', 'folder', 'share_token')


# ── Like admin ──────────────────────────────────────────────────────────────────

@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ('drop', 'user', 'ip', 'created_at')
    raw_id_fields = ('drop', 'user')


# ── CrashReport admin ──────────────────────────────────────────────────────────

@admin.register(CrashReport)
class CrashReportAdmin(admin.ModelAdmin):
    list_display = ('fingerprint', 'exc_type', 'title', 'hit_count', 'last_seen_at')
    search_fields = ('fingerprint', 'title', 'exc_type')
    readonly_fields = ('fingerprint', 'hit_count', 'last_seen_at')


# ── EmailTemplate admin ────────────────────────────────────────────────────────

@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ('slug', 'subject', 'from_email', 'description', 'updated_at')
    search_fields = ('slug', 'subject', 'description')
    readonly_fields = ('updated_at',)
    fieldsets = (
        (None, {'fields': ('slug', 'description', 'subject', 'body_html', 'from_email')}),
        ('Plain-text override', {'classes': ('collapse',), 'fields': ('body_text',),
                                  'description': 'Leave blank to auto-generate from HTML.'}),
        ('Meta', {'fields': ('updated_at',)}),
    )

