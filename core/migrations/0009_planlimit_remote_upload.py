from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_add_drop_like'),
    ]

    operations = [
        migrations.AddField(
            model_name='planlimit',
            name='remote_upload',
            field=models.BooleanField(
                default=False,
                help_text='Allow server-side URL upload (drp up --remote).',
            ),
        ),
    ]
