from django.contrib import admin
from billing.models import CommercialLicense


@admin.register(CommercialLicense)
class CommercialLicenseAdmin(admin.ModelAdmin):
    list_display = ("license_key_short", "licensee_name", "licensee_email",
                    "is_active", "pdf_downloaded", "issued_at", "expires_at")
    list_filter = ("is_active", "pdf_downloaded")
    search_fields = ("license_key", "licensee_name", "licensee_email")
    readonly_fields = ("issued_at",)

    def license_key_short(self, obj):
        return obj.license_key[:20] + "…" if len(obj.license_key) > 20 else obj.license_key
    license_key_short.short_description = "License Key"
