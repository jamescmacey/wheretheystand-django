from datetime import date

from django.db import migrations, models


def backfill_boundary_set_valid_from(apps, schema_editor):
    ElectorateBoundarySet = apps.get_model("wts_app", "ElectorateBoundarySet")

    for boundary_set in ElectorateBoundarySet.objects.all():
        electorate_dates = list(
            boundary_set.electorateboundary_set.all()
            .select_related("electorate")
            .values_list("electorate__valid_from", flat=True)
        )
        electorate_dates = [d for d in electorate_dates if d is not None]
        boundary_set.valid_from = min(electorate_dates) if electorate_dates else date.today()
        boundary_set.save(update_fields=["valid_from"])


class Migration(migrations.Migration):

    dependencies = [
        ("wts_app", "0035_alter_parliamentaryaffiliation_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="electorateboundaryset",
            name="valid_from",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_boundary_set_valid_from, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="electorateboundaryset",
            name="valid_from",
            field=models.DateField(),
        ),
    ]
