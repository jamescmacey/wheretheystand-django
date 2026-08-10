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

    # Advance voting opens before polling day and runs until the day before it.
    voting_period_start = models.DateField(blank=True, null=True)
    voting_period_end = models.DateField(blank=True, null=True)

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

    # Whether clients should open a live connection to Firestore for this
    # version. access_mode alone cannot decide: archived events imported from
    # Firestore also carry access_mode="firebase". This is also the switch to
    # flip if the live feed misbehaves during an event -- clients fall back to
    # the published snapshots within about thirty seconds.
    is_live = models.BooleanField(default=False)

    # Set once counting is complete and the figures will not change again.
    is_final = models.BooleanField(default=False)

    # Written by the results worker once it has built reference data for the
    # event. Django reads this back and never writes it.
    refdata_built = models.BooleanField(default=False)
    archived = models.BooleanField(default=False)

    # Results are embargoed until polls close. The worker must not write to
    # Firestore before embargo_end, because security rules cannot express this
    # without a document read on every evaluation.
    embargo_start = models.DateTimeField(blank=True, null=True)
    embargo_end = models.DateTimeField(blank=True, null=True)

    # Points at which a given proportion of the vote is expected to be counted,
    # as [{"proportion": 0.5, "target_time": "..."}].
    result_targets = models.JSONField(blank=True, null=True)

    # Members holding each electorate going into the election, as
    # [{"persistent_candidate_id": ..., "persistent_party_id": ...,
    #   "persistent_electorate_id": ...}]. Derivable from parliamentary
    # affiliations at dissolution, but populated separately for now.
    incumbents = models.JSONField(blank=True, null=True)

    # How the worker numbers voting places for this event, where it differs.
    vp_numbering_scheme = models.JSONField(blank=True, null=True)

    # Ordered lists of UUIDs, resolved to Firestore ids when pushed. Ordering is
    # the point of these, and a many-to-many would lose it without a through
    # model carrying a position -- more machinery than a handful of curated
    # entries per event justifies. Validated in clean() instead.
    comparison_version_ids = models.JSONField(default=list, blank=True)
    coalition_order_left = models.JSONField(default=list, blank=True)
    coalition_order_right = models.JSONField(default=list, blank=True)

    archived_url = models.URLField(blank=True, null=True)
    card_url = models.URLField(blank=True, null=True)
    vp_finder_url = models.URLField(blank=True, null=True)

    last_firebase_push_at = models.DateTimeField(blank=True, null=True)
    last_snapshot_published_at = models.DateTimeField(blank=True, null=True)

    # Where this version's payloads were last published. Kept so the manifest
    # can be rebuilt in full without republishing every election -- publishing
    # one version must not drop the others from the manifest.
    snapshot_paths = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ('election', 'slug')

    def clean(self):
        """Check the UUID lists point at rows that exist.

        These fields trade referential integrity for ordering, so the check the
        database would otherwise do happens here.
        """
        from django.core.exceptions import ValidationError

        errors = {}

        missing = self._missing_ids(
            ElectionResultVersion, self.comparison_version_ids)
        if missing:
            errors['comparison_version_ids'] = f"Unknown results versions: {missing}"

        for field in ('coalition_order_left', 'coalition_order_right'):
            missing = self._missing_ids(PersistentParty, getattr(self, field))
            if missing:
                errors[field] = f"Unknown persistent parties: {missing}"

        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _missing_ids(model, ids):
        if not ids:
            return []
        found = set(
            str(pk) for pk in model.objects.filter(id__in=ids).values_list('id', flat=True))
        return [str(value) for value in ids if str(value) not in found]

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

    def __str__(self):
        return f"{self.display_name}"

    class Meta:
        ordering = ['display_name']

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

    # The statistics the Electoral Commission publishes alongside a results set.
    # Stored as flat columns for querying, but exposed to clients as a nested
    # object so that the shape matches the Firestore document.
    STATISTICS_FIELDS = (
        'total_voting_places_counted',
        'percent_voting_places_counted',
        'total_votes_cast',
        'percent_votes_cast',
        'total_electorates_final',
        'percent_electorates_final',
        'total_minimal_votes',
        'total_special_votes',
        'total_registered_parties',
        'total_voting_places',
        'total_party_informals',
        'total_candidate_informals',
        'total_candidates',
        'total_issued_ballot_papers',
    )

    @property
    def canonical_key(self):
        """Identify this results set independently of where it came from.

        The same tally arrives from Firestore during an event and from this
        database afterwards, with different primary keys each time. Clients key
        results on this instead, so an incoming update replaces the right row
        whichever transport delivered it. Kept in step with resultsSetKey() in
        the client's utils/elections/keys.ts.
        """
        return ':'.join(str(part) for part in (
            self.results_level,
            self.results_category,
            self.electorate.number if self.electorate_id else '-',
            self.voting_place.number if self.voting_place_id else '-',
            self.result_number if self.result_number is not None else '-',
        ))

    def statistics_payload(self):
        """The statistics as a nested dict, with every key always present.

        Prefers the flat columns, which the Firestore importer populates, and
        falls back to the raw ``statistics`` blob for anything missing.
        """
        raw = self.statistics or {}
        payload = {}
        for name in self.STATISTICS_FIELDS:
            value = getattr(self, name, None)
            payload[name] = raw.get(name) if value is None else value
        return payload

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