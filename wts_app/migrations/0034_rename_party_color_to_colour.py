from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("wts_app", "0033_merge_20260118_1333"),
    ]

    operations = [
        migrations.RenameField(
            model_name="party",
            old_name="color",
            new_name="colour",
        ),
    ]

