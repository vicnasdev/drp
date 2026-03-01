from django.contrib import admin

from .models import PlanLimits, UserProfile


@admin.register(PlanLimits)
class PlanLimitsAdmin(admin.ModelAdmin):
    list_display = ("plan", "storage_bytes", "max_file_bytes", "max_expiry_days",
                    "password_protected", "helpbot_calls_per_hr")
    list_editable = ("storage_bytes", "max_file_bytes", "max_expiry_days",
                     "password_protected", "helpbot_calls_per_hr")
    ordering = ("plan",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "storage_used", "is_anonymous", "created_at")
    list_filter = ("plan", "is_anonymous")
    search_fields = ("user__username", "user__email")
