from django.db import migrations

from ._user_model import create_user_model


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        (
            "wts_app",
            "0040_rename_elected_date_desc_idx_parl_aff_elected_date_desc_idx_and_more",
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[create_user_model()],
        ),
    ]
