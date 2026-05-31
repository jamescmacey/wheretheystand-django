"""
Monitored sources and system events that bootstrap workbook pipelines.
"""

from django.db import models

from .base import BaseModel
from .workbooks import Workbook


class MonitoredSource(BaseModel):
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    handler = models.CharField(max_length=64)
    config = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    default_recipe_key = models.CharField(max_length=64, blank=True, null=True)
    poll_interval_minutes = models.PositiveIntegerField(default=60)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SystemEvent(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        WORKBOOK_CREATED = "workbook_created", "Workbook created"
        PREPROCESSED = "preprocessed", "Preprocessed"
        FAILED = "failed", "Failed"
        SUCCESS = "success", "Success"

    source = models.ForeignKey(
        MonitoredSource,
        on_delete=models.CASCADE,
        related_name="events",
    )
    external_id = models.CharField(max_length=255)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    workbook = models.ForeignKey(
        Workbook,
        on_delete=models.SET_NULL,
        related_name="system_events",
        null=True,
        blank=True,
    )
    error_message = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                name="wts_systemevent_source_external_unique",
            ),
        ]

    def __str__(self):
        return f"{self.source.slug}:{self.external_id}"
