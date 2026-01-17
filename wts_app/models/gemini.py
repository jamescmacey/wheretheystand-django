"""
Models for Gemini batch processing.
"""

from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from .base import BaseModel


class GeminiBatchJob(BaseModel):
    """Tracks a Gemini batch job for any processor."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUBMITTED = "submitted", "Submitted"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        PARTIAL = "partial", "Partially succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        CANCELLING = "cancelling", "Cancelling"
        PAUSED = "paused", "Paused"
        EXPIRED = "expired", "Expired"
        UNKNOWN = "unknown", "Unknown"

    processor = models.CharField(max_length=100)
    requested_model = models.CharField(max_length=255)
    resolved_model = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    batch_name = models.CharField(max_length=255, blank=True, null=True, unique=True)
    display_name = models.CharField(max_length=255, blank=True, null=True)
    input_file_name = models.CharField(max_length=255, blank=True, null=True)
    output_file_name = models.CharField(max_length=255, blank=True, null=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    last_checked_at = models.DateTimeField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    raw_request = models.JSONField(blank=True, null=True)
    raw_response = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"], name="gemini_job_status_idx"),
            models.Index(fields=["processor", "status"], name="gemini_job_proc_status_idx"),
        ]

    def __str__(self):
        return f"{self.processor} - {self.status}"


class GeminiBatchItem(BaseModel):
    """Tracks a single item within a Gemini batch job."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUBMITTED = "submitted", "Submitted"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    job = models.ForeignKey(
        GeminiBatchJob,
        on_delete=models.CASCADE,
        related_name="items",
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    output_index = models.PositiveIntegerField(blank=True, null=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    request_payload = models.JSONField(blank=True, null=True)
    response_payload = models.JSONField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id"], name="gemini_item_content_idx"),
            models.Index(fields=["job", "status"], name="gemini_item_job_status_idx"),
        ]

    def __str__(self):
        return f"{self.content_type} - {self.object_id} - {self.status}"
