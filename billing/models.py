from django.db import models


class CommercialLicense(models.Model):
    """
    Tracks commercial self-hosted license keys issued through Lemon Squeezy.
    User purchases → LS generates key → webhook stores it here →
    user fills form on /licensing/ → gets PDF.
    """
    license_key    = models.CharField(max_length=128, unique=True, db_index=True)
    licensee_name  = models.CharField(max_length=256, blank=True, default="")
    licensee_email = models.EmailField(blank=True, default="")
    order_id       = models.CharField(max_length=64, blank=True, default="")
    ls_customer_id = models.CharField(max_length=64, blank=True, default="")
    issued_at      = models.DateTimeField(auto_now_add=True)
    expires_at     = models.DateTimeField(null=True, blank=True)
    is_active      = models.BooleanField(default=True)
    pdf_downloaded = models.BooleanField(default=False,
                                         help_text="True after licensee has downloaded the PDF at least once.")

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        name = self.licensee_name or self.licensee_email or "—"
        return f"{name} — {self.license_key[:16]}…"
