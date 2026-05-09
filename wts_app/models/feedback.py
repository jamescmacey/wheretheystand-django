"""User-submitted feedback and corrections."""

from django.db import models

from .base import BaseModel


class Feedback(BaseModel):
    class Category(models.TextChoices):
        GENERAL = "general", "General"
        FEEDBACK = "feedback", "Feedback"
        CORRECTION = "correction", "Correction"

    category = models.CharField(
        max_length=20,
        choices=Category.choices,
    )
    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=254)
    message = models.TextField()

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "feedback"

    def __str__(self):
        return f"{self.get_category_display()} from {self.name} ({self.created_at:%Y-%m-%d})"
