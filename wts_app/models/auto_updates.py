from .base import BaseModel
from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

class AutoUpdate(BaseModel):
    """
    A auto update.
    """
    STATUSES = [
        ("successful", "Successful"),
        ("failed", "Failed"),
        ("started", "Started"),
    ]

    payload = models.JSONField(blank=True,null=True)
    status = models.CharField(max_length=20, choices=STATUSES, default="pending")
    error_message = models.TextField(blank=True,null=True)

    updated_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auto_updates_by_object",
    )
    updated_object_id = models.CharField(max_length=64, blank=True, null=True)
    
    updated_object = GenericForeignKey(
        "updated_content_type",
        "updated_object_id",
    )