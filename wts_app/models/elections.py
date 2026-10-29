"""
Election models.

Election model.
"""

from django.db import models
from django.core.files.storage import storages
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

def card_image_upload_to(instance, filename):
    return f"elections/cards/{instance.id}/{filename}"


def card_image_storage():
    """Public media, served unsigned.

    A social card URL is fetched by crawlers long after it was published, so a
    signed URL from the default storage would stop resolving.
    """
    return storages["documents"]


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

    # How the worker numbers voting places for this event, where it differs.
    vp_numbering_scheme = models.JSONField(blank=True, null=True)

    # Ordered lists of UUIDs, resolved to Firestore ids when pushed. Ordering is
    # the point of these, and a many-to-many would lose it without a through
    # model carrying a position -- more machinery than a handful of curated
    # entries per event justifies. Validated in clean() instead.
    comparison_version_ids = models.JSONField(default=list, blank=True)

    # The two political blocs, as ordered PersistentParty UUIDs, so that parties
    # likely to govern together are drawn together rather than by size. One rule
    # decides the whole seating plan: [*left, *cross-bench, *right] reads from
    # the far left of the chamber to the far right. So the left list is written
    # far-left first and the right list centre first, and a party in neither
    # list is cross-bench and sits in the middle. "Bloc" rather than
    # "coalition": before an election there is no agreement, only an alignment.
    bloc_order_left = models.JSONField(default=list, blank=True)
    bloc_order_right = models.JSONField(default=list, blank=True)

    archived_url = models.URLField(blank=True, null=True)
    card_url = models.URLField(blank=True, null=True)

    # Social card image for this version, published in the manifest as
    # `card_image_url`. Uploaded here rather than named by URL so there is one
    # place to put it, and because the client only ever reads the manifest.
    card_image = models.ImageField(
        upload_to=card_image_upload_to, storage=card_image_storage,
        blank=True, null=True)
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

        for field in ('bloc_order_left', 'bloc_order_right'):
            missing = self._missing_ids(PersistentParty, getattr(self, field))
            if missing:
                errors[field] = f"Unknown persistent parties: {missing}"

        # A party in both blocs would be seated twice, and the ordering rule
        # could not say where.
        both = ({str(value) for value in self.bloc_order_left or []}
                & {str(value) for value in self.bloc_order_right or []})
        if both:
            errors['bloc_order_right'] = (
                f"Already in the left bloc: {sorted(both)}")

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

    @property
    def card_image_url(self):
        """The public URL of the card image, or None where none is set."""
        if not self.card_image:
            return None
        return self.card_image.url

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

class ElectorateIncumbent(BaseModel):
    """Who held an electorate going into one results version.

    The dashboard can say who won a seat; without this it cannot say whether
    that is a change. Three cases have to be told apart -- the same member
    standing again, the incumbent party standing somebody else, and a sitting
    member standing for another party or as an independent -- and only the last
    of those needs curating here. The other two are derived on the client by
    matching these persistent records against the version's own candidate list,
    which is authoritative and cannot drift out of step with itself.

    `persistent_party` is the party the seat was *won* for, which is what a flip
    is measured against. Where the member has since left it, `has_left_party`
    says so and `current_persistent_party` says where they sit now -- null
    there means they sit as an independent. That pair is curated because a
    member who crossed the floor and is not standing again leaves nothing in the
    candidate list to derive it from.
    """

    results_version = models.ForeignKey(
        ElectionResultVersion, on_delete=models.CASCADE, db_index=True,
        related_name='electorate_incumbents')

    # The persistent electorate. Named for the model it points at, matching
    # ElectionElectorate.electorate: there is no PersistentElectorate, because
    # an electorate already survives across elections.
    electorate = models.ForeignKey(Electorate, on_delete=models.CASCADE)

    # Null where the seat was vacant going into the election.
    persistent_candidate = models.ForeignKey(
        PersistentCandidate, on_delete=models.SET_NULL, blank=True, null=True)
    persistent_party = models.ForeignKey(
        PersistentParty, on_delete=models.SET_NULL, blank=True, null=True)

    has_left_party = models.BooleanField(default=False)
    current_persistent_party = models.ForeignKey(
        PersistentParty, on_delete=models.SET_NULL, blank=True, null=True,
        related_name='+')

    notes = models.TextField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['results_version']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['results_version', 'electorate'],
                name='unique_results_version_electorate_incumbent'),
        ]

    @property
    def sitting_persistent_party_id(self):
        """The party the member sits for now, which is what seat counts use.

        Null where they sit as an independent or the seat is vacant.
        """
        if not self.has_left_party:
            return self.persistent_party_id
        return self.current_persistent_party_id

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if (self.current_persistent_party_id
                and self.current_persistent_party_id == self.persistent_party_id):
            errors['current_persistent_party'] = (
                "This is the party the seat was won for, so it is not a defection. "
                "Leave it empty.")
        if self.current_persistent_party_id and not self.has_left_party:
            errors['has_left_party'] = (
                "Tick this where the member now sits for another party.")
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.electorate.name} - {self.results_version.name}"


class PartyIncumbent(BaseModel):
    """How many seats a party held going into one results version.

    The baseline for "+3" or "-2" beside a party on the night. These are the
    seats held **at dissolution**, counting where each member sits now rather
    than the party they were elected for -- a member who crossed the floor
    stopped counting towards their old party's total the day they did it. That
    is the figure a reader compares an election result against, and it is the
    one thing about these numbers that is easy to get wrong.

    List seats cannot be derived from anything this database holds, which is why
    both counts are curated rather than computed. `copy_incumbents` reports
    where `electorate_seats` disagrees with the ElectorateIncumbent rows.
    """

    results_version = models.ForeignKey(
        ElectionResultVersion, on_delete=models.CASCADE, db_index=True,
        related_name='party_incumbents')
    persistent_party = models.ForeignKey(PersistentParty, on_delete=models.CASCADE)
    electorate_seats = models.PositiveSmallIntegerField(default=0)
    list_seats = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=['results_version']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['results_version', 'persistent_party'],
                name='unique_results_version_party_incumbent'),
        ]

    @property
    def total_seats(self):
        return self.electorate_seats + self.list_seats

    def __str__(self):
        return (f"{self.persistent_party} - {self.total_seats} seat(s)"
                f" - {self.results_version.name}")


class PersistentVotingPlace(BaseModel):
    firebase_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
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
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)

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

    # Attributes read by ElectionVotingPlaceIndex in wts_app/index.py. Algolia
    # records are flat, so anything reached through a relation has to be spelled
    # out here, and UUIDs have to be strings: the client serialises records to
    # JSON and a UUID instance is not JSON.

    @property
    def id_as_str(self):
        return str(self.id)

    @property
    def results_version_id_as_str(self):
        return str(self.results_version_id)

    @property
    def election_id_as_str(self):
        return str(self.results_version.election_id)

    @property
    def event_id(self):
        """The Firestore events document id for this voting place's version.

        Null until the version has been pushed. Faceted so a client that came in
        holding an event id can filter on it without first resolving it to a
        results version.
        """
        return self.results_version.firebase_id

    @property
    def election_name(self):
        return self.results_version.election.name

    @property
    def results_version_name(self):
        return self.results_version.name

    @property
    def electorate_name(self):
        return self.physical_electorate.name

    @property
    def electorate_number(self):
        return self.physical_electorate.number

    @property
    def persistent_voting_place_id_as_str(self):
        if not self.persistent_voting_place_id:
            return None
        return str(self.persistent_voting_place_id)

    @property
    def geoloc(self):
        """Coordinates in Algolia's `_geoloc` shape, for radius search.

        None where the place has not been geocoded, which leaves `_geoloc` off
        the record entirely rather than indexing it at (0, 0) in the Gulf of
        Guinea. Such a record is still found by an address query.
        """
        if self.latitude is None or self.longitude is None:
            return None
        return {"lat": self.latitude, "lng": self.longitude}

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

        The last component separates sets that are otherwise identical. The
        Commission has published advance votes and polling-day votes as
        separate sets for the same voting place before, and may again, so at
        voting place level, level, category, electorate and place together do
        not identify a tally. ``result_number`` is the field meant to say which
        one it is; nothing populates it, because nothing in the feed has been
        confirmed to carry the ordinal. Until something does, the Firestore
        document id stands in: it is the one discriminator both transports
        hold, since ``firebase_id`` *is* that id. Without it, two such sets
        collapse onto one key and the client keeps whichever arrived with the
        later timestamp -- the place reads low by exactly the set that was
        dropped, and nothing says so.

        The document id is used at voting place level only. National and
        electorate tallies are unique per level, category and electorate
        already, and a set of theirs that predates Firestore has no
        ``firebase_id``; keying on one would make a published tally and its
        live twin two separate entries rather than one replacing the other.
        """
        if self.result_number is not None:
            discriminator = self.result_number
        elif self.results_level == 'voting_place':
            discriminator = self.firebase_id or '-'
        else:
            discriminator = '-'

        return ':'.join(str(part) for part in (
            self.results_level,
            self.results_category,
            self.electorate.number if self.electorate_id else '-',
            self.voting_place.number if self.voting_place_id else '-',
            discriminator,
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