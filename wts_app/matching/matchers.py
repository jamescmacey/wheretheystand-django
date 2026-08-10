"""Per-type matching of election entities to persistent records.

Each matcher answers the same three questions -- which rows are unmatched, what
should happen to a given row, and how to create a persistent record for it --
but the signals differ completely. Candidates are matched on names, voting
places on distance, parties on their abbreviation.

Every matcher classifies a row into one of four outcomes:

    exact       an unambiguous match          linked by --apply
    structural  differs only by middle names  linked by --apply
    review      something similar exists      never linked automatically
    create      nothing plausible             created by --create-missing

The separation matters. Similarity scores decide only whether a row reaches
`review`; they can neither cause nor prevent a link, because a false pair can
outscore a true one.
"""

from dataclasses import dataclass, field

from ..models.elections import (
    ElectionCandidate,
    ElectionElectorate,
    ElectionParty,
    ElectionVotingPlace,
    PersistentCandidate,
    PersistentParty,
    PersistentVotingPlace,
)
from ..models.electorates import Electorate
from . import geo, names

EXACT = 'exact'
STRUCTURAL = 'structural'
REVIEW = 'review'
CREATE = 'create'


@dataclass
class Suggestion:
    persistent: object
    score: float = 0.0
    detail: str = ''


@dataclass
class Outcome:
    entity: object
    kind: str
    suggestion: Suggestion | None = None
    notes: list = field(default_factory=list)

    @property
    def links_automatically(self):
        return self.kind in (EXACT, STRUCTURAL)


class Matcher:
    """Base class. Subclasses supply the signals and the creation rule."""

    key = ''
    label = ''
    verbose_name = ''
    #: Whether --create-missing may create persistent records for this type.
    can_create = True

    def __init__(self, version, min_score=0.80, threshold_metres=None):
        self.version = version
        self.min_score = min_score
        self.threshold_metres = threshold_metres or geo.DEFAULT_THRESHOLD_METRES
        self._prepare()

    def _prepare(self):
        """Build whatever indexes classification needs."""

    def all_entities(self):
        raise NotImplementedError

    def unmatched(self):
        raise NotImplementedError

    def classify(self, entity):
        raise NotImplementedError

    def create_persistent(self, entity):
        raise NotImplementedError

    def link(self, entity, persistent):
        raise NotImplementedError

    def describe(self, entity):
        return str(entity)

    def describe_persistent(self, persistent):
        return str(persistent)

    def context(self, entity):
        """Extra facts a person needs to judge a suggestion."""
        return ''


class CandidateMatcher(Matcher):
    key = 'candidates'
    label = 'candidates'
    verbose_name = 'candidate'

    def _prepare(self):
        self.by_name = {}
        self.by_surname = {}
        self.pool = {}
        for candidate in PersistentCandidate.objects.all():
            self.by_name.setdefault(names.normalise(candidate.display_name), []).append(candidate)
            surname, _ = names.split_name(candidate.display_name)
            self.by_surname.setdefault(surname, []).append(candidate)
            self.pool[candidate.display_name] = candidate

    def all_entities(self):
        return ElectionCandidate.objects.filter(
            results_version=self.version).select_related('party', 'electorate')

    def unmatched(self):
        return self.all_entities().filter(persistent_candidate__isnull=True).order_by('name')

    def classify(self, entity):
        exact = self.by_name.get(names.normalise(entity.name), [])
        if len(exact) == 1:
            return Outcome(entity, EXACT, Suggestion(exact[0], 1.0, 'identical name'))
        if len(exact) > 1:
            return Outcome(entity, REVIEW, Suggestion(exact[0], 1.0, 'identical name'),
                           notes=[f'{len(exact)} persistent candidates share this name'])

        # The structural rule runs over every record sharing a surname, and is
        # deliberately independent of any similarity score -- otherwise raising
        # --min-score would silently stop genuine matches being linked.
        surname, _ = names.split_name(entity.name)
        structural = [c for c in self.by_surname.get(surname, [])
                      if names.is_structural_match(entity.name, c.display_name)]
        if len(structural) == 1:
            return Outcome(entity, STRUCTURAL,
                           Suggestion(structural[0], names.similarity(
                               entity.name, structural[0].display_name),
                               'same surname, given names are a prefix'))
        if len(structural) > 1:
            return Outcome(entity, REVIEW, Suggestion(structural[0]),
                           notes=[f'{len(structural)} records differ only by middle names'])

        similar, score = names.best_similar(entity.name, self.pool, self.min_score)
        if similar is not None:
            return Outcome(entity, REVIEW, Suggestion(similar, score, 'similar name'))

        return Outcome(entity, CREATE)

    def create_persistent(self, entity):
        return PersistentCandidate.objects.create(display_name=entity.name)

    def link(self, entity, persistent):
        ElectionCandidate.objects.filter(pk=entity.pk).update(persistent_candidate=persistent)

    def describe(self, entity):
        return entity.name

    def describe_persistent(self, persistent):
        return persistent.display_name

    def context(self, entity):
        bits = [entity.party.name if entity.party else 'Independent']
        if entity.electorate:
            bits.append(entity.electorate.name)
        if entity.list_pos:
            bits.append(f'list {entity.list_pos}')
        return ', '.join(bits)


class PartyMatcher(Matcher):
    key = 'parties'
    label = 'parties'
    verbose_name = 'party'

    def _prepare(self):
        self.by_abbreviation = {}
        self.by_name = {}
        self.pool = {}
        for party in PersistentParty.objects.all():
            if party.abbreviation:
                self.by_abbreviation.setdefault(
                    names.normalise(party.abbreviation), []).append(party)
            for value in (party.display_name, party.short_name):
                if value:
                    self.by_name.setdefault(names.normalise(value), []).append(party)
            if party.display_name:
                self.pool[party.display_name] = party

    def all_entities(self):
        return ElectionParty.objects.filter(results_version=self.version)

    def unmatched(self):
        return self.all_entities().filter(persistent_party__isnull=True).order_by('name')

    def classify(self, entity):
        # An abbreviation is registered and near-unique, so it is the strongest
        # signal a party carries.
        for value, detail in ((entity.abbreviation, 'identical abbreviation'),
                              (entity.name, 'identical name'),
                              (entity.short_name, 'identical short name')):
            if not value:
                continue
            index = self.by_abbreviation if detail.endswith('abbreviation') else self.by_name
            found = index.get(names.normalise(value), [])
            if len(found) == 1:
                return Outcome(entity, EXACT, Suggestion(found[0], 1.0, detail))
            if len(found) > 1:
                return Outcome(entity, REVIEW, Suggestion(found[0], 1.0, detail),
                               notes=[f'{len(found)} persistent parties share this {detail}'])

        similar, score = names.best_similar(entity.name, self.pool, self.min_score)
        if similar is not None:
            return Outcome(entity, REVIEW, Suggestion(similar, score, 'similar name'))

        return Outcome(entity, CREATE)

    def create_persistent(self, entity):
        return PersistentParty.objects.create(
            display_name=entity.name,
            short_name=entity.short_name,
            abbreviation=entity.abbreviation)

    def link(self, entity, persistent):
        ElectionParty.objects.filter(pk=entity.pk).update(persistent_party=persistent)

    def describe(self, entity):
        return entity.name

    def describe_persistent(self, persistent):
        return persistent.display_name or persistent.abbreviation or str(persistent.id)

    def context(self, entity):
        bits = [entity.abbreviation or '—']
        bits.append('registered' if entity.registered else 'unregistered')
        return ', '.join(bits)


class VotingPlaceMatcher(Matcher):
    key = 'voting-places'
    label = 'voting places'
    verbose_name = 'voting place'

    def _prepare(self):
        self.persistent = list(PersistentVotingPlace.objects.all())

    def all_entities(self):
        return ElectionVotingPlace.objects.filter(results_version=self.version)

    def unmatched(self):
        return self.all_entities().filter(
            persistent_voting_place__isnull=True).order_by('number')

    def classify(self, entity):
        # Matched on proximity, not address text: the Commission republishes
        # coordinates for the same hall and they drift by a few metres.
        place, metres = geo.nearest(
            (entity.latitude, entity.longitude), self.persistent, self.threshold_metres)

        if place is None:
            return Outcome(entity, CREATE)

        detail = f'{metres:.0f} m away'
        # Close enough to be certain; further out, let a person look.
        if metres <= self.threshold_metres / 2:
            return Outcome(entity, EXACT, Suggestion(place, 1.0, detail))
        return Outcome(entity, REVIEW, Suggestion(place, 1.0, detail))

    def create_persistent(self, entity):
        return PersistentVotingPlace.objects.create(
            address=entity.address, latitude=entity.latitude, longitude=entity.longitude)

    def link(self, entity, persistent):
        ElectionVotingPlace.objects.filter(pk=entity.pk).update(
            persistent_voting_place=persistent)

    def describe(self, entity):
        return f'{entity.number}  {entity.address}'

    def describe_persistent(self, persistent):
        return persistent.address

    def context(self, entity):
        return f'{entity.latitude:.5f}, {entity.longitude:.5f}'


class ElectorateMatcher(Matcher):
    key = 'electorates'
    label = 'electorates'
    verbose_name = 'electorate'
    # Electorates are curated site entities with boundaries, regions and slugs,
    # and saving one triggers site search indexing. Creating them from a results
    # feed would produce records that look right and are not.
    can_create = False

    def _prepare(self):
        self.by_name = {}
        self.pool = {}
        for electorate in Electorate.objects.all():
            self.by_name.setdefault(names.normalise(electorate.name), []).append(electorate)
            self.pool[electorate.name] = electorate

    def all_entities(self):
        return ElectionElectorate.objects.filter(results_version=self.version)

    def unmatched(self):
        return self.all_entities().filter(electorate__isnull=True).order_by('number')

    def classify(self, entity):
        found = self.by_name.get(names.normalise(entity.name), [])
        if len(found) == 1:
            return Outcome(entity, EXACT, Suggestion(found[0], 1.0, 'identical name'))
        if len(found) > 1:
            return Outcome(entity, REVIEW, Suggestion(found[0], 1.0, 'identical name'),
                           notes=[f'{len(found)} electorates share this name'])

        similar, score = names.best_similar(entity.name, self.pool, self.min_score)
        if similar is not None:
            return Outcome(entity, REVIEW, Suggestion(similar, score, 'similar name'))

        return Outcome(entity, CREATE)

    def create_persistent(self, entity):
        raise NotImplementedError(
            'Electorates are created in the admin, where their boundaries, '
            'region and validity dates can be set properly.')

    def link(self, entity, persistent):
        ElectionElectorate.objects.filter(pk=entity.pk).update(electorate=persistent)

    def describe(self, entity):
        return f'{entity.number}  {entity.name}'

    def describe_persistent(self, persistent):
        return f'{persistent.name} ({persistent.get_status_display()})'


MATCHERS = {
    matcher.key: matcher
    for matcher in (CandidateMatcher, PartyMatcher, VotingPlaceMatcher, ElectorateMatcher)
}
