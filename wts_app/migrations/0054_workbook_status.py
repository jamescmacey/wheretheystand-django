from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wts_app", "0053_gemini_batchjob_processed_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="workbook",
            name="status",
            field=models.CharField(
                choices=[("open", "Open"), ("closed", "Closed")],
                default="open",
                max_length=16,
            ),
        ),
    ]
