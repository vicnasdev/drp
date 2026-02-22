"""
Add anon_file_lifetime_days to PlanLimit.

Seed values:
  anon    → 90  (existing hardcoded behaviour)
  free    → 90  (same)
  starter → None (never expire by time — storage quota is the constraint)
  pro     → None (same)
"""
from django.db import migrations, models


SEEDS = {
    "anon":    90,
    "free":    90,
    "starter": None,
    "pro":     None,
}


def seed_anon_file_lifetime(apps, schema_editor):
    PlanLimit = apps.get_model("core", "PlanLimit")
    for plan_key, days in SEEDS.items():
        PlanLimit.objects.filter(plan=plan_key).update(anon_file_lifetime_days=days)


def reverse_anon_file_lifetime(apps, schema_editor):
    PlanLimit = apps.get_model("core", "PlanLimit")
    PlanLimit.objects.update(anon_file_lifetime_days=None)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_seed_plan_limits"),
    ]

    operations = [
        migrations.AddField(
            model_name="planlimit",
            name="anon_file_lifetime_days",
            field=models.PositiveIntegerField(
                null=True,
                blank=True,
                help_text=(
                    "Hard ceiling (days from creation) for file drops with no explicit expiry. "
                    "null = never expire (paid plans)."
                ),
            ),
        ),
        migrations.RunPython(seed_anon_file_lifetime, reverse_code=reverse_anon_file_lifetime),
    ]
