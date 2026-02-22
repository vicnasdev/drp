import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_userprofile_notify_bug_fix'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Collection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=60)),
                ('name', models.CharField(max_length=120)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('owner', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='collections',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('owner', 'slug')},
            },
        ),
        migrations.CreateModel(
            name='CollectionMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ns', models.CharField(choices=[('c', 'Clipboard'), ('f', 'File')], max_length=1)),
                ('key', models.CharField(max_length=120)),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('collection', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='memberships',
                    to='core.collection',
                )),
            ],
            options={
                'ordering': ['-added_at'],
                'unique_together': {('collection', 'ns', 'key')},
            },
        ),
    ]
