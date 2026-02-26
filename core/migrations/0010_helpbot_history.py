from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0009_planlimit_remote_upload'),
    ]

    operations = [
        migrations.CreateModel(
            name='HelpBotHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('messages', models.JSONField(default=list, help_text='List of {q, a} dicts')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='helpbot_history', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name_plural': 'help bot histories',
            },
        ),
    ]
