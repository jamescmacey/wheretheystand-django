"""
Banner models.

Banner model for displaying messages on the client.
"""

from django.db import models
from django.core.exceptions import ValidationError
from .base import BaseModel


class Banner(BaseModel):
    """
    A banner that displays on the client.
    """
    is_persistent = models.BooleanField(
        default=False,
        help_text="Whether the banner can be dismissed by the user"
    )
    display_start = models.DateTimeField(
        help_text="Start of the period for which the banner is shown"
    )
    display_end = models.DateTimeField(
        blank=True,
        null=True,
        help_text="End of the period for which the banner is shown (null means indefinite)"
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    
    URL_TYPE_CHOICES = [
        ("internal", "Internal"),
        ("external", "External"),
    ]
    url_type = models.CharField(
        max_length=20,
        choices=URL_TYPE_CHOICES,
        blank=True,
        null=True,
        help_text="Type of URL (internal or external)"
    )
    
    URL_BEHAVIOUR_CHOICES = [
        ("new", "New window"),
        ("same", "Same window"),
    ]
    url_behaviour = models.CharField(
        max_length=20,
        choices=URL_BEHAVIOUR_CHOICES,
        blank=True,
        null=True,
        help_text="How the URL should open (new window or same window)"
    )
    
    url = models.TextField(
        blank=True,
        null=True,
        help_text="URL (may be a relative path, no domain or protocol required)"
    )
    
    class Meta:
        ordering = ['-display_start']
    
    def __str__(self):
        return self.title
    
    def clean(self):
        """Validate that if URL is set, url_type and url_behaviour are also set."""
        super().clean()
        if self.url and self.url.strip():
            if not self.url_type:
                raise ValidationError({
                    'url_type': 'URL type is required when URL is set.'
                })
            if not self.url_behaviour:
                raise ValidationError({
                    'url_behaviour': 'URL behaviour is required when URL is set.'
                })
    
    def save(self, *args, **kwargs):
        """Ensure validation is run on save."""
        self.full_clean()
        super().save(*args, **kwargs)

