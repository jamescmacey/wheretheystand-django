"""
Election models.

Election model.
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from .base import BaseModel
from django.utils.text import slugify
from .electorates import ElectorateBoundarySet, Electorate
from .gazette import GazetteNotice
from .parties import Party

class Election(BaseModel):
    polling_date = models.DateField()
    polls_close = models.DateTimeField()
    TYPES = [("general", "General"),("by-election", "By-election")]
    election_type = models.CharField(max_length=20,choices=TYPES,default="general")
    name = models.TextField()
    slug = models.SlugField(unique=True,blank=True,null=True)
    boundary_set = models.ForeignKey(ElectorateBoundarySet, on_delete=models.SET_NULL, blank=True, null=True)
    gazette_notices = models.ManyToManyField(GazetteNotice, blank=True)
    legacy_id = models.IntegerField(unique=True, validators=[MinValueValidator(1)], blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.id or not self.slug:
            self.slug = slugify(self.name)
        super(Election, self).save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} ({self.polling_date})'

class ElectionResultVersion(BaseModel):
    election = models.ForeignKey(Election, on_delete=models.CASCADE)
    is_primary = models.BooleanField(default=False)
    name = models.TextField()
    description = models.TextField(blank=True, null=True)
    slug = models.SlugField(blank=True,null=True)

    class Meta:
        unique_together = ('election', 'slug')

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)

        # If marking this as primary, clear others for same election
        if self.is_primary:
            ElectionResultVersion.objects.filter(
                election=self.election, is_primary=True
            ).exclude(pk=self.pk).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} ({self.election.name})'

class ElectionElectorate(BaseModel):
    results_version = models.ForeignKey(ElectionResultVersion, on_delete=models.CASCADE)
    electorate = models.ForeignKey(Electorate, on_delete=models.SET_NULL, blank=True, null=True)
    number = models.IntegerField(validators=[MinValueValidator(1)])
    name = models.TextField()

    # A candidate election in an electorate may be cancelled if a candidate dies or becomes incapacitated.
    accepting_candidate_votes = models.BooleanField(default=True)

class ElectionParty(BaseModel):
    results_version = models.ForeignKey(ElectionResultVersion, on_delete=models.CASCADE)
    party = models.ForeignKey(Party, on_delete=models.SET_NULL, blank=True, null=True)
    number = models.IntegerField(validators=[MinValueValidator(1)])
    name: str
    short_name: str
    abbreviation: str
    registered: bool

class PersistentCandidate:
    person = models.ForeignKey('Person', on_delete=models.SET_NULL, blank=True, null=True)
    display_name = models.TextField()

class ElectionCandidate(BaseModel):
    results_version = models.ForeignKey(ElectionResultVersion, on_delete=models.CASCADE)
    name: models.TextField()
    number: models.IntegerField(validators=[models.Min(1)])
    electorate: models.ForeignKey(ElectionElectorate, on_delete=models.SET_NULL, blank=True, null=True)
    party: models.ForeignKey(ElectionParty, on_delete=models.SET_NULL, blank=True, null=True)
    list_pos: models.IntegerField(validators=[MinValueValidator(1)], blank=True, null=True)
    is_dead: models.BooleanField(default=False)

class ElectionVotingPlace(BaseModel):
    results_version = models.ForeignKey(ElectionResultVersion, on_delete=models.CASCADE)
    number = models.IntegerField(validators=[MinValueValidator(1)])
    physical_electorate = models.ForeignKey(ElectionElectorate, on_delete=models.CASCADE)
    address = models.TextField()
    latitude = models.FloatField()
    longitude = models.FloatField()

class PersistentVotingPlace(BaseModel):
    latitude = models.FloatField()
    longitude = models.FloatField()
    address = models.TextField()

class ResultsSet(BaseModel):
    results_version = models.ForeignKey(ElectionResultVersion, on_delete=models.CASCADE)
    
    RESULTS_LEVEL_CHOICES = [
        ('national', 'National'),
        ('electorate', 'Electorate'),
        ('voting_place', 'Voting place'),
    ]
    results_level = models.CharField(max_length=20, choices=RESULTS_LEVEL_CHOICES)

    results_category = models.CharField(
        max_length=20,
        choices=[
            ('party_votes', 'Party votes'),
            ('candidate_votes', 'Candidate votes')
        ]
    )

    informals = models.IntegerField()
    unknowns = models.IntegerField()
    refused = models.IntegerField()
    sample_size = models.IntegerField()
    updated = models.DateTimeField()
    parsed = models.DateTimeField()
    electorate = models.ForeignKey(ElectionElectorate, on_delete=models.CASCADE, blank=True, null=True)
    voting_place = models.ForeignKey(ElectionVotingPlace, on_delete=models.CASCADE, blank=True, null=True)
    voting_place_number = models.IntegerField(validators=[MinValueValidator(1)], blank=True, null=True)
    statistics = models.JSONField(null=True, blank=True)
    is_final = models.BooleanField(default=False)
    received = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.results_version.name} - {self.results_level} - {self.results_category}"

class Result(BaseModel):
    results_set = models.ForeignKey(ResultsSet, on_delete=models.CASCADE)
    count = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    per_cent = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    candidate = models.ForeignKey(ElectionCandidate, on_delete=models.SET_NULL, blank=True, null=True)
    party = models.ForeignKey(ElectionParty, on_delete=models.SET_NULL, blank=True, null=True)
    list_seats = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    electorate_seats = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    total_seats = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])

    def __str__(self):
        return f"{self.results_set.results_version.name} - {self.results_set.results_level} - {self.results_set.results_category} - {self.candidate.name if self.candidate else self.party.name}"

