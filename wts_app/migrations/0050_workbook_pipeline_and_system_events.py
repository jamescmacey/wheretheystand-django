# Generated manually for workbook pipeline

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("wts_app", "0049_user_bio_user_github_username"),
    ]

    operations = [
        migrations.AddField(
            model_name="workbook",
            name="recipe_key",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="workbook",
            name="source",
            field=models.CharField(
                choices=[("manual", "Manual"), ("system_event", "System event")],
                default="manual",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="workbook",
            name="current_step_key",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.CreateModel(
            name="MonitoredSource",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("slug", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("handler", models.CharField(max_length=64)),
                ("config", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=True)),
                ("default_recipe_key", models.CharField(blank=True, max_length=64, null=True)),
                ("poll_interval_minutes", models.PositiveIntegerField(default=60)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="SystemEvent",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("external_id", models.CharField(max_length=255)),
                ("payload", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("processing", "Processing"),
                            ("workbook_created", "Workbook created"),
                            ("preprocessed", "Preprocessed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("error_message", models.TextField(blank=True, null=True)),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="wts_app.monitoredsource",
                    ),
                ),
                (
                    "workbook",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="system_events",
                        to="wts_app.workbook",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddField(
            model_name="workbook",
            name="system_event",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="workbooks",
                to="wts_app.systemevent",
            ),
        ),
        migrations.CreateModel(
            name="WorkbookStep",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("step_key", models.CharField(max_length=64)),
                ("sequence", models.PositiveSmallIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("draft", "Draft"),
                            ("awaiting_review", "Awaiting review"),
                            ("committed", "Committed"),
                            ("failed", "Failed"),
                            ("rejected", "Rejected"),
                            ("skipped", "Skipped"),
                        ],
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("committed_at", models.DateTimeField(blank=True, null=True)),
                ("production_object_id", models.CharField(blank=True, max_length=64, null=True)),
                (
                    "committed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="committed_workbook_steps",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "production_content_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "workbook",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="steps",
                        to="wts_app.workbook",
                    ),
                ),
                (
                    "workbook_file",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="steps",
                        to="wts_app.workbookfile",
                    ),
                ),
            ],
            options={
                "ordering": ["workbook_file_id", "sequence", "step_key"],
            },
        ),
        migrations.AddConstraint(
            model_name="systemevent",
            constraint=models.UniqueConstraint(
                fields=("source", "external_id"),
                name="wts_systemevent_source_external_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="workbookstep",
            constraint=models.UniqueConstraint(
                fields=("workbook", "step_key", "workbook_file"),
                name="wts_workbookstep_unique_per_file",
            ),
        ),
        migrations.AddIndex(
            model_name="workbookstep",
            index=models.Index(fields=["workbook", "status"], name="wts_wbstep_workbook_status_idx"),
        ),
        migrations.AddIndex(
            model_name="workbookstep",
            index=models.Index(fields=["workbook", "step_key"], name="wts_wbstep_workbook_key_idx"),
        ),
    ]
