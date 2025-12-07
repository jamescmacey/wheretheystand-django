"""
Base models, abstract models, and mixins.

Use this file for:
- Abstract base models that other models inherit from
- Reusable mixins (e.g., TimestampMixin, SlugMixin)
- Common model fields/behaviors
"""

from django.db import models
import uuid


class TimestampMixin(models.Model):
    """Abstract mixin that adds created_at and updated_at fields."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True

class UUIDPrimaryKeyMixin(models.Model):
    """
    Abstract mixin that sets a UUID field as the primary key.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BaseModel(TimestampMixin, UUIDPrimaryKeyMixin):
    """Base model that all other models can inherit from."""
    
    class Meta:
        abstract = True

