"""
Seed the PlanLimit table from the Plan.LIMITS dict.
Run once at deploy. Re-running is safe (update_or_create).
"""
from django.db import migrations


SEED = {
    "anon": {
        "label":                       "Anonymous",
        "price_monthly":               0,
        "max_file_mb":                 200,
        "max_text_kb":                 500,
        "max_expiry_days":             None,
        "clipboard_idle_hours":        24,
        "clipboard_max_lifetime_days": 7,
        "storage_gb":                  None,
        "renewals":                    0,
        "password_protection":         False,
        "max_collections":             0,
    },
    "free": {
        "label":                       "Free",
        "price_monthly":               0,
        "max_file_mb":                 200,
        "max_text_kb":                 500,
        "max_expiry_days":             None,
        "clipboard_idle_hours":        48,
        "clipboard_max_lifetime_days": 30,
        "storage_gb":                  None,
        "renewals":                    0,
        "password_protection":         False,
        "max_collections":             0,
    },
    "starter": {
        "label":                       "Starter",
        "price_monthly":               3,
        "max_file_mb":                 1024,
        "max_text_kb":                 2048,
        "max_expiry_days":             365,
        "clipboard_idle_hours":        None,
        "clipboard_max_lifetime_days": None,
        "storage_gb":                  5,
        "renewals":                    None,   # unlimited
        "password_protection":         True,
        "max_collections":             10,
    },
    "pro": {
        "label":                       "Pro",
        "price_monthly":               8,
        "max_file_mb":                 5120,
        "max_text_kb":                 10240,
        "max_expiry_days":             365 * 3,
        "clipboard_idle_hours":        None,
        "clipboard_max_lifetime_days": None,
        "storage_gb":                  20,
        "renewals":                    None,   # unlimited
        "password_protection":         True,
        "max_collections":             None,   # unlimited
    },
}


def seed_plan_limits(apps, schema_editor):
    PlanLimit = apps.get_model('core', 'PlanLimit')
    for plan_key, data in SEED.items():
        PlanLimit.objects.update_or_create(plan=plan_key, defaults=data)


def unseed_plan_limits(apps, schema_editor):
    PlanLimit = apps.get_model('core', 'PlanLimit')
    PlanLimit.objects.filter(plan__in=SEED.keys()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_planlimit_email_prefs'),
    ]

    operations = [
        migrations.RunPython(seed_plan_limits, reverse_code=unseed_plan_limits),
    ]
