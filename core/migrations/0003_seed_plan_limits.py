"""Seed the three default PlanLimits rows."""

from django.db import migrations


def seed_plan_limits(apps, schema_editor):
    PlanLimits = apps.get_model("core", "PlanLimits")
    defaults = {
        "free": {
            "storage_bytes": 1 * 1024**3,
            "max_file_bytes": 200 * 1024**2,
            "max_expiry_days": 7,
            "max_folders": 3,
            "password_protected": False,
            "custom_keys": True,
            "helpbot_calls_per_hr": 5,
        },
        "starter": {
            "storage_bytes": 5 * 1024**3,
            "max_file_bytes": 1 * 1024**3,
            "max_expiry_days": 365,
            "max_folders": 10,
            "password_protected": True,
            "custom_keys": True,
            "helpbot_calls_per_hr": 30,
        },
        "pro": {
            "storage_bytes": 20 * 1024**3,
            "max_file_bytes": 5 * 1024**3,
            "max_expiry_days": 365 * 3,
            "max_folders": None,
            "password_protected": True,
            "custom_keys": True,
            "helpbot_calls_per_hr": 120,
        },
    }
    for plan, limits in defaults.items():
        PlanLimits.objects.get_or_create(plan=plan, defaults=limits)


def unseed(apps, schema_editor):
    PlanLimits = apps.get_model("core", "PlanLimits")
    PlanLimits.objects.filter(plan__in=["free", "starter", "pro"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_plan_limits"),
    ]

    operations = [
        migrations.RunPython(seed_plan_limits, unseed),
    ]
