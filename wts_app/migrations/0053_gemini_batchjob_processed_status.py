from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wts_app", "0052_gemini_celery_beat"),
    ]

    operations = [
        migrations.AlterField(
            model_name="geminibatchjob",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("submitted", "Submitted"),
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("succeeded", "Succeeded"),
                    ("partial", "Partially succeeded"),
                    ("processed", "Processed"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                    ("cancelling", "Cancelling"),
                    ("paused", "Paused"),
                    ("expired", "Expired"),
                    ("unknown", "Unknown"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]

