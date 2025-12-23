"""
Bill model
"""

from django.db import models
from .base import BaseModel
from django.core.validators import MinValueValidator, MaxValueValidator
from .bills import Bill
from .people import Person
from .parties import Party

class Vote(BaseModel):
    """
    A vote.
    """
    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)
    parliament_document_id = models.TextField(blank=True,null=True)
    retrieved_at = models.DateTimeField(blank=True, null=True)

    bill = models.ForeignKey(Bill, on_delete=models.CASCADE)
    date = models.DateField()
    reading = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(3)])
    ayes = models.IntegerField(validators=[MinValueValidator(0)])
    noes = models.IntegerField(validators=[MinValueValidator(0)])
    abstentions = models.IntegerField(validators=[MinValueValidator(0)])
    absentees = models.IntegerField(validators=[MinValueValidator(0)])

    IMPORT_METHODS = [("parse", "Hansard parser"), ("api", "Parliament API"), ("manual", "Manual"), ("ai", "AI assisted")]
    import_method = models.CharField(max_length=10, choices=IMPORT_METHODS, default="parse")

    motion_agreed = models.BooleanField(default=False)
    outcome_text = models.TextField(blank=True,null=True)
    reason_text = models.TextField(blank=True,null=True)
    hansard_status = models.TextField(blank=True,null=True)

    TYPES = [("party", "Party vote"), ("personal", "Personal vote"), ("voice", "Voice vote")]
    vote_type = models.CharField(max_length=8, choices=TYPES, blank=True, null=True)
    contains_split_party_votes = models.BooleanField(default=False)


    class Meta:
        verbose_name_plural = "Votes"
        ordering = ['-date']
        unique_together = ['bill', 'reading']

    def __str__(self):
        # Format the reading number as an ordinal (1st, 2nd, 3rd, etc.)
        suffix = "th" if 11 <= (self.reading % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(self.reading % 10, "th") if self.reading else ""
        reading_ordinal = f"{self.reading}{suffix}" if self.reading else "Unknown reading"
        return f"{self.bill.name} - {self.date} - {reading_ordinal}"

class VoteRecord(BaseModel):
    """
    A vote record.
    """
    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)
    vote = models.ForeignKey(Vote, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.PROTECT,blank=True, null=True)
    party = models.ForeignKey(Party, on_delete=models.PROTECT,blank=True, null=True)

    is_proxy_vote = models.BooleanField(default=False)
    is_split_party_vote = models.BooleanField(default=False)

    POSITION_CHOICES = [("aye", "Aye"), ("no", "No"), ("abstention", "Abstention"), ("absent", "Absent")]
    position = models.CharField(max_length=10, choices=POSITION_CHOICES)

    contribution = models.IntegerField(blank=True,null=True,validators=[MinValueValidator(0)])

    class Meta:
        verbose_name_plural = "Vote records"
        ordering = ['-vote__date']
        unique_together = ['vote', 'person']
    
    def __str__(self):
        return f"{self.vote.bill.name} - {self.vote.date} - {self.person.display_name} - {self.position}"