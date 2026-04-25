from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("wts_app", "0036_electorateboundaryset_valid_from"),
    ]

    operations = [
        migrations.AddField(
            model_name="electorateboundary",
            name="simplified_shape",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="electorate_boundaries_simplified",
                to="wts_app.file",
            ),
        ),
    ]
