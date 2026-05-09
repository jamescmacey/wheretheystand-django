import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("wts_app", "0037_electorateboundary_simplified_shape"),
    ]

    operations = [
        migrations.CreateModel(
            name="Feedback",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("general", "General"),
                            ("feedback", "Feedback"),
                            ("correction", "Correction"),
                        ],
                        max_length=20,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("email", models.EmailField(max_length=254)),
                ("message", models.TextField()),
            ],
            options={
                "ordering": ["-created_at"],
                "verbose_name_plural": "feedback",
            },
        ),
    ]
