from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wts_app", "0050_workbook_pipeline_and_system_events"),
    ]

    operations = [
        migrations.AddField(
            model_name="workbook",
            name="batch_defaults",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Shared ingestion values (dates, copyright) applied across files in batch workbooks.",
            ),
        ),
    ]
