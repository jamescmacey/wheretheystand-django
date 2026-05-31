from __future__ import annotations

import json

from django.db import migrations


def create_gemini_beat_task(apps, schema_editor) -> None:
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    interval, _ = IntervalSchedule.objects.get_or_create(
        # Use the period field value string instead of `IntervalSchedule.SECONDS`.
        # When using historical models via `apps.get_model`, those constants
        # may not exist.
        every=120, period="seconds"
    )

    # Store as JSON text because django-celery-beat's PeriodicTask.args is a
    # JSONField stored as text in v2.x.
    PeriodicTask.objects.update_or_create(
        name="Gemini: process completed batches",
        defaults={
            "task": "wts_app.gemini.process_completed_gemini_batches",
            "interval": interval,
            "enabled": True,
            "args": json.dumps([100]),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("wts_app", "0051_workbook_batch_defaults"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.RunPython(create_gemini_beat_task, migrations.RunPython.noop),
    ]

