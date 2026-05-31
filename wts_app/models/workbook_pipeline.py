"""
Generic workbook pipeline steps (JSON payloads, no kind-specific tables).
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .base import BaseModel
from .workbooks import Workbook, WorkbookFile


class WorkbookStep(BaseModel):
    """One step instance in a workbook recipe run (per file for batch recipes)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DRAFT = "draft", "Draft"
        AWAITING_REVIEW = "awaiting_review", "Awaiting review"
        COMMITTED = "committed", "Committed"
        FAILED = "failed", "Failed"
        REJECTED = "rejected", "Rejected"
        SKIPPED = "skipped", "Skipped"

    workbook = models.ForeignKey(
        Workbook,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    workbook_file = models.ForeignKey(
        WorkbookFile,
        on_delete=models.CASCADE,
        related_name="steps",
        null=True,
        blank=True,
    )
    step_key = models.CharField(max_length=64)
    sequence = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, null=True)
    committed_at = models.DateTimeField(blank=True, null=True)
    committed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="committed_workbook_steps",
        null=True,
        blank=True,
    )
    production_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    production_object_id = models.CharField(max_length=64, blank=True, null=True)
    production_object = GenericForeignKey(
        "production_content_type",
        "production_object_id",
    )

    class Meta:
        ordering = ["workbook_file_id", "sequence", "step_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["workbook", "step_key", "workbook_file"],
                name="wts_workbookstep_unique_per_file",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workbook", "status"],
                name="wts_wbstep_workbook_status_idx",
            ),
            models.Index(
                fields=["workbook", "step_key"],
                name="wts_wbstep_workbook_key_idx",
            ),
        ]

    def __str__(self):
        file_part = f" file={self.workbook_file_id}" if self.workbook_file_id else ""
        return f"{self.workbook_id}:{self.step_key}{file_part} ({self.status})"
