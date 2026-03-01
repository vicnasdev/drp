from django.contrib import admin

from api.models import CrashReport


@admin.register(CrashReport)
class CrashReportAdmin(admin.ModelAdmin):
    list_display = ("fingerprint_short", "exc_type", "command", "hit_count",
                    "issue_url", "first_seen", "last_seen")
    list_filter = ("command", "exc_type")
    search_fields = ("fingerprint", "exc_type", "exc_message")
    readonly_fields = ("fingerprint", "exc_type", "exc_message", "traceback",
                       "command", "cli_version", "python_version", "platform",
                       "hit_count", "first_seen", "last_seen")

    @admin.display(description="Fingerprint")
    def fingerprint_short(self, obj):
        return obj.fingerprint[:12]
