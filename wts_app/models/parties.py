"""
Party models.

Party and PartyBrandHistory models.
"""

from django.db import models
from django.utils import timezone
from colorfield.fields import ColorField
from .base import BaseModel
from django.core.validators import MinValueValidator


class Party(BaseModel):
    """
    A political party.
    Current name fields stored here for fast queries.
    """
    legal_name = models.CharField(max_length=200, unique=True)
    display_name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=20, unique=True)
    color = ColorField(blank=True, null=True)
    slug = models.SlugField(unique=True,blank=True,null=True)
    twitter_user = models.ForeignKey('TwitterUser', on_delete=models.SET_NULL, blank=True, null=True)

    party_leader_role = models.TextField(default="Leader")
    party_leader_role_plural = models.TextField(default="Leaders")

    registered_date = models.DateField(blank=True, null=True)
    deregistered_date = models.DateField(blank=True, null=True)
    is_registered = models.BooleanField(default=False)
    registration_dates_precise = models.BooleanField(default=False)

    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)

    class Meta:
        verbose_name_plural = "Parties"

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        if not self.id or not self.slug:
            self.slug = slugify(self.display_name)
        super(Party, self).save(*args, **kwargs)

    def change_name(self, legal_name=None, display_name=None, short_name=None, 
                   abbreviation=None, color=None, effective_date=None):
        """
        Helper method to change name(s) and record history.
        Only provided fields will be updated.
        """
        if effective_date is None:
            effective_date = timezone.now().date()
        
        # Get current values before updating
        old_legal_name = self.legal_name
        old_display_name = self.display_name
        old_short_name = self.short_name
        old_abbreviation = self.abbreviation
        old_color = self.color

        # Check if any name is actually changing
        name_changed = (
            (legal_name is not None and legal_name != old_legal_name) or
            (display_name is not None and display_name != old_display_name) or
            (short_name is not None and short_name != old_short_name) or
            (abbreviation is not None and abbreviation != old_abbreviation) or
            (color is not None and color != old_color)
        )
        
        if name_changed:
            # Record old name in history
            PartyBrandHistory.objects.create(
                party=self,
                legal_name=old_legal_name,
                display_name=old_display_name,
                short_name=old_short_name,
                abbreviation=old_abbreviation,
                color=old_color,
                effective_until=effective_date
            )
            
            # Update current name fields
            if legal_name is not None:
                self.legal_name = legal_name
            if display_name is not None:
                self.display_name = display_name
            if short_name is not None:
                self.short_name = short_name
            if abbreviation is not None:
                self.abbreviation = abbreviation
            if color is not None:
                self.color = color
            self.save()


class PartyBrandHistory(BaseModel):
    """
    Historical record of party brand changes.
    """
    party = models.ForeignKey(
        Party, 
        on_delete=models.CASCADE, 
        related_name='name_history',
        db_index=True
    )
    legal_name = models.CharField(max_length=200)
    display_name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=100, blank=True)
    abbreviation = models.CharField(max_length=20, blank=True)
    colour = ColorField(blank=True, null=True)
    effective_from = models.DateField()  # When this name started
    effective_until = models.DateField()  # When it ended (when name changed)
    
    class Meta:
        verbose_name_plural = "Party Name History"
        ordering = ['-effective_until']  # Most recent changes first
        indexes = [
            models.Index(fields=['party', '-effective_until']),
        ]

    def __str__(self):
        return f"{self.party} - {self.display_name} ({self.effective_from} to {self.effective_until})"

