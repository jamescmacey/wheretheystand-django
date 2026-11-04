"""Replace the publish flag with a three-way publish status.

True becomes published and false becomes unpublished; unlisted is new.
"""

from django.db import migrations, models


def forwards(apps, schema_editor):
    ElectionResultVersion = apps.get_model('wts_app', 'ElectionResultVersion')
    ElectionResultVersion.objects.filter(publish=True).update(publish_status='published')
    ElectionResultVersion.objects.filter(publish=False).update(publish_status='unpublished')


def backwards(apps, schema_editor):
    # Unlisted versions are in the manifest, so they go back to published.
    ElectionResultVersion = apps.get_model('wts_app', 'ElectionResultVersion')
    ElectionResultVersion.objects.exclude(publish_status='unpublished').update(publish=True)
    ElectionResultVersion.objects.filter(publish_status='unpublished').update(publish=False)


class Migration(migrations.Migration):

    dependencies = [
        ('wts_app', '0070_results_version_comparison_and_publish'),
    ]

    operations = [
        migrations.AddField(
            model_name='electionresultversion',
            name='publish_status',
            field=models.CharField(
                choices=[('published', 'Published'), ('unlisted', 'Unlisted'),
                         ('unpublished', 'Unpublished')],
                default='published', max_length=20),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='electionresultversion',
            name='publish',
        ),
    ]
