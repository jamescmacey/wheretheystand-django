"""
Bill model
"""

from django.db import models
from .base import BaseModel
from django.core.validators import MinValueValidator, MaxValueValidator

class Bill(BaseModel):
    """
    A bill.
    """
    name = models.TextField()
    description = models.TextField(blank=True,null=True)
    retrieved_at = models.DateTimeField(blank=True, null=True)
    last_activity_date = models.DateField(blank=True, null=True)

    parliament_document_id = models.TextField(blank=True,null=True)
    parliament_api_id = models.TextField(blank=True,null=True)
    parliament_api_status = models.TextField(blank=True,null=True)
    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)
    ref = models.TextField(blank=True,null=True)

    people_responsible = models.ManyToManyField('Person', related_name='bills')
    parliaments = models.ManyToManyField('Parliament', related_name='bills')

    TYPES = [("members", "Member's bill"), ("government", "Government bill"), ("private", "Private bill"), ("local", "Local bill")]
    bill_type = models.CharField(max_length=10, choices=TYPES, blank=True, null=True)

    VOTING_METHODS = [("personal","Personal votes only"), ("party","Party votes only"), ("mixed","Mixed voting"), ("unknown","Unknown")]
    voting_methods = models.CharField(max_length=8, choices=VOTING_METHODS, default="unknown")

    STATUSES = [("unknown","Unknown"),("in_progress","In progress"),("defeated","Defeated"),("withdrawn","Withdrawn"),("passed","Passed"),("enacted","Enacted"),("divided","Divided"),("lapsed","Lapsed"),("unknown_not_current","Unknown / Not Current"),("discharged","Discharged")]
    status = models.CharField(max_length=19, choices=STATUSES, default="unknown")

    select_committee_name = models.TextField(blank=True,null=True)
    select_committee_status = models.TextField(blank=True,null=True)

    introduction_date = models.DateField(blank=True,null=True)
    first_reading_date = models.DateField(blank=True, null=True)
    submissions_due_date = models.DateField(blank=True, null=True)
    report_back_date = models.DateField(blank=True, null=True)
    second_reading_date = models.DateField(blank=True, null=True)
    whole_house_date = models.DateField(blank=True, null=True)
    third_reading_date = models.DateField(blank=True, null=True)
    royal_assent_date = models.DateField(blank=True, null=True)
    withdrawn_date = models.DateField(blank=True, null=True)
    defeated_date = models.DateField(blank=True, null=True)
    defeated_reading = models.IntegerField(blank=True, null=True,validators=[MinValueValidator(1), MaxValueValidator(3)])
    lapsed_date = models.DateField(blank=True, null=True)
    
    child_bills = models.ManyToManyField('self', blank=True, symmetrical=False, related_name='parent_bills')

    act_name = models.TextField(blank=True,null=True)
    act_number = models.IntegerField(blank=True,null=True,validators=[MinValueValidator(1)])
    act_year = models.IntegerField(blank=True,null=True,validators=[MinValueValidator(1840)])
    legislation_url = models.URLField(blank=True,null=True, max_length=1000)

    original_api_response = models.JSONField(blank=True,null=True)

    is_divided = models.BooleanField(default=False)
    extended_sittings_used = models.BooleanField(default=False)
    urgency_used = models.BooleanField(default=False)
    flag_scraped_under_v2 = models.BooleanField(default=False)
    flag_enacted_but_missing_assent_number = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.name} (introduced {self.introduction_date})'

    class Meta:
        verbose_name_plural = "Bills"
        ordering = ['-introduction_date']