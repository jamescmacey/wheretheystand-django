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
from colorfield.fields import ColorField

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

    MODES = [("api", "API"),("firebase", "Firebase")]
    access_mode = models.CharField(max_length=20, choices=MODES, default="api")
    firebase_id = models.CharField(max_length=255, blank=True, null=True, unique=True)

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
    results_version = models.ForeignKey(ElectionResultVersion, on_delete=models.CASCADE, db_index=True)
    firebase_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    electorate = models.ForeignKey(Electorate, on_delete=models.SET_NULL, blank=True, null=True)
    number = models.IntegerField(validators=[MinValueValidator(1)])
    name = models.TextField()
    
    # A candidate election in an electorate may be cancelled if a candidate dies or becomes incapacitated.
    accepting_candidate_votes = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=['results_version']),
        ]
    
    def __str__(self):
        return f"{self.name} - {self.results_version.name} - {self.results_version.election.name}"

class PersistentParty(BaseModel):
    party = models.OneToOneField(Party, on_delete=models.SET_NULL, blank=True, null=True)
    firebase_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    abbreviation = models.TextField(blank=True, null=True)
    colour = ColorField(blank=True, null=True)
    display_name = models.TextField(blank=True, null=True)
    short_name = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.display_name} - {self.abbreviation} - {self.colour}"
    

class ElectionParty(BaseModel):
    firebase_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    results_version = models.ForeignKey(ElectionResultVersion, on_delete=models.CASCADE, db_index=True)
    persistent_party = models.ForeignKey(PersistentParty, on_delete=models.SET_NULL, blank=True, null=True)
    number = models.IntegerField(validators=[MinValueValidator(1)])
    name = models.TextField()
    short_name = models.TextField(blank=True, null=True)
    abbreviation = models.TextField(blank=True, null=True)
    registered = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['results_version']),
        ]

    def __str__(self):
        return f"{self.name} - {self.results_version.name} - {self.results_version.election.name}"

class PersistentCandidate(BaseModel):
    person = models.OneToOneField('Person', on_delete=models.SET_NULL, blank=True, null=True)
    display_name = models.TextField()
    firebase_id = models.TextField(blank=True, null=True)

class ElectionCandidate(BaseModel):
    results_version = models.ForeignKey(ElectionResultVersion, on_delete=models.CASCADE, db_index=True)
    firebase_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    persistent_candidate = models.ForeignKey(PersistentCandidate, on_delete=models.SET_NULL, blank=True, null=True)
    name = models.TextField()
    number = models.IntegerField(validators=[MinValueValidator(1)])
    electorate = models.ForeignKey(ElectionElectorate, on_delete=models.SET_NULL, blank=True, null=True)
    party = models.ForeignKey(ElectionParty, on_delete=models.SET_NULL, blank=True, null=True)
    list_pos = models.IntegerField(validators=[MinValueValidator(1)], blank=True, null=True)
    is_dead = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Check electorate's results_version
        if self.electorate and self.electorate.results_version_id != self.results_version_id:
            raise ValueError(
                f"ElectionCandidate.electorate (id={self.electorate_id}) belongs to results_version "
                f"{self.electorate.results_version_id}, but this candidate is for results_version {self.results_version_id}"
            )
        # Check party's results_version
        if self.party and self.party.results_version_id != self.results_version_id:
            raise ValueError(
                f"ElectionCandidate.party (id={self.party_id}) belongs to results_version "
                f"{self.party.results_version_id}, but this candidate is for results_version {self.results_version_id}"
            )
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=['results_version']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['results_version', 'number'], name='unique_results_version_candidate_number')
        ]

    def __str__(self):
        return f"{self.name} - {self.results_version.name} - {self.results_version.election.name}"

class PersistentVotingPlace(BaseModel):
    firebase_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    address = models.TextField()

    def __str__(self):
        return f"{self.address} ({self.latitude}, {self.longitude})"

class ElectionVotingPlace(BaseModel):
    results_version = models.ForeignKey(ElectionResultVersion, on_delete=models.CASCADE, db_index=True)
    firebase_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    number = models.IntegerField(validators=[MinValueValidator(1)])
    physical_electorate = models.ForeignKey(ElectionElectorate, on_delete=models.CASCADE)
    persistent_voting_place = models.ForeignKey(PersistentVotingPlace, on_delete=models.SET_NULL, blank=True, null=True)
    address = models.TextField()
    latitude = models.FloatField()
    longitude = models.FloatField()

    def save(self, *args, **kwargs):
        # Check that the physical_electorate belongs to the same results_version
        if self.physical_electorate and self.physical_electorate.results_version_id != self.results_version_id:
            raise ValueError(
                f"ElectionVotingPlace.physical_electorate (id={self.physical_electorate_id}) belongs to results_version "
                f"{self.physical_electorate.results_version_id}, but this voting place is for results_version {self.results_version_id}"
            )
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=['results_version']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['results_version', 'number'], name='unique_results_version_voting_place_number')
        ]

    def __str__(self):
        return f"{self.number} - {self.physical_electorate.name} - {self.results_version.name} - {self.results_version.election.name}"


class ResultsSet(BaseModel):
    results_version = models.ForeignKey(ElectionResultVersion, on_delete=models.CASCADE, db_index=True)
    firebase_id = models.CharField(max_length=255, blank=True, null=True, unique=True)

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

    informals = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    unknowns = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    refused = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    sample_size = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    updated = models.DateTimeField()
    parsed = models.DateTimeField(null=True, blank=True)
    electorate = models.ForeignKey(ElectionElectorate, on_delete=models.CASCADE, blank=True, null=True)
    voting_place = models.ForeignKey(ElectionVotingPlace, on_delete=models.CASCADE, blank=True, null=True)
    result_number = models.IntegerField(validators=[MinValueValidator(1)], blank=True, null=True)
    statistics = models.JSONField(null=True, blank=True)
    is_final = models.BooleanField(default=False)
    received = models.DateTimeField(null=True, blank=True)

    total_voting_places_counted = models.IntegerField(null=True, blank=True, default=0)
    percent_voting_places_counted = models.FloatField(null=True, blank=True, default=0)
    total_votes_cast = models.IntegerField(null=True, blank=True, default=0)
    percent_votes_cast = models.FloatField(null=True, blank=True, default=0)
    total_electorates_final = models.IntegerField(null=True, blank=True, default=0)
    percent_electorates_final = models.FloatField(null=True, blank=True, default=0)
    total_minimal_votes = models.IntegerField(null=True, blank=True)
    total_special_votes = models.IntegerField(null=True, blank=True)
    total_registered_parties = models.IntegerField(null=True, blank=True, default=0)
    total_voting_places = models.IntegerField(null=True, blank=True)
    total_party_informals = models.IntegerField(null=True, blank=True)
    total_candidate_informals = models.IntegerField(null=True, blank=True)
    total_candidates = models.IntegerField(null=True, blank=True)
    total_issued_ballot_papers = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.results_version.name} - {self.results_level} - {self.results_category}"

    class Meta:
        indexes = [
            models.Index(fields=['results_version']),
        ]

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

    def save(self, *args, **kwargs):
        # Check that the candidate belongs to the same results_version
        if self.candidate and self.candidate.results_version_id != self.results_set.results_version_id:
            raise ValueError(
                f"Result.candidate (id={self.candidate}) belongs to results_version "
                f"{self.candidate.results_version_id}, but this result is for results_version {self.results_set.results_version_id}"
            )

        # Check that the party belongs to the same results_version
        if self.party and self.party.results_version_id != self.results_set.results_version_id:
            raise ValueError(
                f"Result.party (id={self.party}) belongs to results_version "
                f"{self.party.results_version_id}, but this result is for results_version {self.results_set.results_version_id}"
            )

        super().save(*args, **kwargs)