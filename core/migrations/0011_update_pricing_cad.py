"""Update plan pricing: Starter $3 → CA$5, Pro $8 → CA$10."""

from django.db import migrations


def update_prices(apps, schema_editor):
    PlanLimit = apps.get_model("core", "PlanLimit")
    PlanLimit.objects.filter(plan="starter").update(price_monthly=5)
    PlanLimit.objects.filter(plan="pro").update(price_monthly=10)


def revert_prices(apps, schema_editor):
    PlanLimit = apps.get_model("core", "PlanLimit")
    PlanLimit.objects.filter(plan="starter").update(price_monthly=3)
    PlanLimit.objects.filter(plan="pro").update(price_monthly=8)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_helpbot_history"),
    ]

    operations = [
        migrations.RunPython(update_prices, revert_prices),
    ]
