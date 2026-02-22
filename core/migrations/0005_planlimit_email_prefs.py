from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_collection_collectionmembership'),
    ]

    operations = [
        # ── PlanLimit table ──────────────────────────────────────────────────
        migrations.CreateModel(
            name='PlanLimit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('plan',                        models.CharField(max_length=16, unique=True)),
                ('label',                       models.CharField(max_length=64)),
                ('price_monthly',               models.PositiveIntegerField(default=0)),
                ('max_file_mb',                 models.PositiveIntegerField(blank=True, null=True)),
                ('max_text_kb',                 models.PositiveIntegerField(blank=True, null=True)),
                ('max_expiry_days',             models.PositiveIntegerField(blank=True, null=True)),
                ('clipboard_idle_hours',        models.PositiveIntegerField(blank=True, null=True)),
                ('clipboard_max_lifetime_days', models.PositiveIntegerField(blank=True, null=True)),
                ('storage_gb',                  models.PositiveIntegerField(blank=True, null=True)),
                ('renewals',                    models.PositiveIntegerField(blank=True, null=True,
                                                    help_text='null = unlimited, 0 = none')),
                ('password_protection',         models.BooleanField(default=False)),
                ('max_collections',             models.PositiveIntegerField(blank=True, null=True,
                                                    help_text='null = unlimited, 0 = none')),
            ],
            options={'ordering': ['price_monthly']},
        ),

        # ── Email pref fields on UserProfile ─────────────────────────────────
        migrations.AddField(
            model_name='userprofile',
            name='notify_product_updates',
            field=models.BooleanField(default=True,
                                      help_text='Changelog, new features, and product announcements.'),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='notify_billing',
            field=models.BooleanField(default=True,
                                      help_text='Payment receipts, failed charges, and plan change confirmations.'),
        ),
    ]
