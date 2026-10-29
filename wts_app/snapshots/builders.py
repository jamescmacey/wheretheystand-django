"""Build the snapshot payloads.

Each function returns plain data in the canonical contract. Uploading is left to
:mod:`wts_app.snapshots.publisher`, so that payloads can be inspected, diffed
and written to disk without touching R2.
"""

from django.conf import settings

from ..models.elections import (
    Election,
    ElectionResultVersion,
    ElectionCandidate,
    ElectionElectorate,
    ElectionParty,
    ElectionVotingPlace,
    ElectorateIncumbent,
    PartyIncumbent,
    PersistentCandidate,
    PersistentParty,
    PersistentVotingPlace,
    Result,
    ResultsSet,
)
from ..models.electorates import Electorate
from ..views.election_results import (
    ElectionCandidateSerializer,
    ElectionElectorateSerializer,
    ElectionPartySerializer,
    ElectionVotingPlaceSerializer,
    PersistentCandidateSerializer,
    PersistentElectorateSerializer,
    PersistentPartySerializer,
    PersistentVotingPlaceSerializer,
    ResultsSetSerializer,
)

from django.db.models import F, Prefetch


def _results_queryset(results_version):
    """Results sets with everything the serializer will ask for.

    Without this, rendering a full voting place snapshot issues a query per
    tally line to resolve the candidate and party numbers.
    """
    return ResultsSet.objects.filter(
        results_version=results_version
    ).select_related(
        'electorate', 'voting_place', 'voting_place__physical_electorate'
    ).prefetch_related(
        Prefetch('result_set',
                 queryset=Result.objects.select_related('candidate', 'party'))
    )


def build_persistent():
    """Entities that persist across elections.

    Party colours and the links from candidates to people live here. They are
    what let the results pages join back into the rest of the site, and they are
    curated in Django rather than derived from the Electoral Commission feed.
    """
    return {
        'persistent_electorates': PersistentElectorateSerializer(
            Electorate.objects.all(), many=True).data,
        'persistent_parties': PersistentPartySerializer(
            PersistentParty.objects.all(), many=True).data,
        'persistent_candidates': PersistentCandidateSerializer(
            PersistentCandidate.objects.all(), many=True).data,
        'persistent_voting_places': PersistentVotingPlaceSerializer(
            PersistentVotingPlace.objects.all(), many=True).data,
    }


def build_reference(results_version):
    """Candidates, parties and electorates for one results version.

    Voting places are excluded: there are several thousand per general election
    and they are only needed once somebody opens the voting place views. They
    are published separately, per electorate.
    """
    candidates = ElectionCandidate.objects.filter(
        results_version=results_version).select_related('electorate', 'party')
    return {
        'electorates': ElectionElectorateSerializer(
            ElectionElectorate.objects.filter(results_version=results_version),
            many=True).data,
        'parties': ElectionPartySerializer(
            ElectionParty.objects.filter(results_version=results_version),
            many=True).data,
        'candidates': ElectionCandidateSerializer(candidates, many=True).data,
        'voting_places': [],
    }


def build_results(results_version):
    """National and electorate level results -- what the dashboard renders."""
    queryset = _results_queryset(results_version).filter(
        results_level__in=['national', 'electorate'])
    return {'results_sets': ResultsSetSerializer(queryset, many=True).data}


def build_voting_places_for_electorate(results_version, electorate):
    """Voting place results within one electorate."""
    queryset = _results_queryset(results_version).filter(
        results_level='voting_place', electorate=electorate)
    return {'results_sets': ResultsSetSerializer(queryset, many=True).data}


def build_voting_place_results(results_version):
    """Voting place results grouped by the place the votes were cast at.

    The by-electorate shards answer "what did this electorate's places do".
    This answers the opposite question, and the two are not interchangeable: a
    place issues ballots for every electorate it serves, so its own tallies are
    spread across those electorates' shards and a page about one place would
    have to fetch all of them to be complete.

    Grouped in one pass rather than one queryset per place. A general election
    has several thousand.
    """
    queryset = _results_queryset(results_version).filter(
        results_level='voting_place').order_by('updated', 'firebase_id')

    grouped = {}
    for results_set in queryset:
        if results_set.voting_place_id is None:
            continue
        grouped.setdefault(results_set.voting_place.number, []).append(results_set)

    return {
        number: {'results_sets': ResultsSetSerializer(sets, many=True).data}
        for number, sets in grouped.items()
    }


def find_colliding_voting_place_sets(results_version):
    """Voting place sets that share a canonical key, which the client cannot keep.

    The client holds one entry per key and keeps whichever tally has the later
    timestamp, so a collision is a tally silently dropped rather than an error
    anyone sees. Returns a mapping of key to the sets holding it, empty in the
    normal case.
    """
    by_key = {}
    for results_set in _results_queryset(results_version).filter(
            results_level='voting_place'):
        by_key.setdefault(results_set.canonical_key, []).append(results_set)

    return {key: sets for key, sets in by_key.items() if len(sets) > 1}


def build_voting_places_reference(results_version):
    """Every voting place for one results version."""
    voting_places = ElectionVotingPlace.objects.filter(
        results_version=results_version).select_related('physical_electorate')
    return {'voting_places': ElectionVotingPlaceSerializer(
        voting_places, many=True).data}


def build_bloc_order(results_version):
    """The two political blocs, as ordered persistent party ids.

    Returns None where neither bloc has been curated, so that the key is left
    out of the manifest altogether. That matters more here than anywhere else:
    the manifest is the one object every visitor fetches, and an election nobody
    has aligned should cost them nothing.

    The order is the whole point. ``[*left, *cross-bench, *right]`` reads from
    the far left of the chamber to the far right, so the left list is curated
    far-left first and the right list centre first.
    """
    left = [str(value) for value in results_version.bloc_order_left or []]
    right = [str(value) for value in results_version.bloc_order_right or []]
    if not left and not right:
        return None
    return {'left': left, 'right': right}


def build_electorate_incumbent(incumbent):
    """One sitting member, as persistent ids and nothing else.

    The client already holds every persistent object, so naming them is enough.
    Null and false members are left out rather than written, for the same reason
    the whole key is optional: the client reads an absent ``candidate`` as a
    seat with no sitting member.
    """
    entry = {'electorate': str(incumbent.electorate_id)}
    if incumbent.persistent_candidate_id:
        entry['candidate'] = str(incumbent.persistent_candidate_id)
    if incumbent.persistent_party_id:
        entry['party'] = str(incumbent.persistent_party_id)
    if incumbent.has_left_party:
        entry['left_party'] = True
        if incumbent.current_persistent_party_id:
            entry['current_party'] = str(incumbent.current_persistent_party_id)
    return entry


def build_incumbency(results_version):
    """Who held what going into one results version.

    Enough for the client to say whether a result is a change rather than only
    what it is: which party held each electorate, which member held it, and how
    many seats each party is defending. Which of the three standing cases
    applies is derived there from the version's own candidate list, so it cannot
    drift out of step with it.

    Returns None where nothing has been curated, so the key is omitted.
    """
    electorates = [build_electorate_incumbent(incumbent)
                   for incumbent in results_version.electorate_incumbents.all()]
    parties = [
        {
            'party': str(incumbent.persistent_party_id),
            'electorate_seats': incumbent.electorate_seats,
            'list_seats': incumbent.list_seats,
        }
        for incumbent in results_version.party_incumbents.all()
    ]
    if not electorates and not parties:
        return None
    return {'electorates': electorates, 'parties': parties}


def build_version_entry(results_version, paths):
    """One results version as it appears in the manifest.

    ``paths`` maps a payload name to its published path, and is supplied by the
    publisher because it depends on content hashes.
    """
    entry = {
        'id': str(results_version.id),
        'slug': results_version.slug,
        'name': results_version.name,
        'description': results_version.description,
        'is_primary': results_version.is_primary,
        'access_mode': results_version.access_mode,
        'firebase_id': results_version.firebase_id,
        # is_live is what decides whether the client opens Firestore listeners.
        # access_mode alone is not enough: archived events imported from
        # Firestore also carry access_mode='firebase'.
        'is_live': getattr(results_version, 'is_live', False),
        'is_final': getattr(results_version, 'is_final', False),
        'refdata_built': getattr(results_version, 'refdata_built', False),
        # Social card image, or None where none has been uploaded. The manifest
        # is the only place the client reads it from, so it carries the resolved
        # public URL rather than the stored path.
        'card_image_url': results_version.card_image_url,
        'paths': paths,
    }

    # Both are curated descriptions of the event rather than payloads, so they
    # ride in the manifest and reach clients on a save, with nothing to publish.
    # Omitted where there is nothing to say -- see the two builders.
    blocs = build_bloc_order(results_version)
    if blocs is not None:
        entry['blocs'] = blocs

    incumbency = build_incumbency(results_version)
    if incumbency is not None:
        entry['incumbency'] = incumbency

    return entry


def build_manifest(entries_by_election):
    """The one document the client fetches before anything else.

    It resolves a slug to the Firestore event id and to the published payload
    paths, so that no request has to reach Django to bootstrap a page.

    ``entries_by_election`` maps an Election to its list of version entries.
    """
    elections = []
    for election, versions in entries_by_election.items():
        if not versions:
            continue
        elections.append({
            'id': str(election.id),
            'slug': election.slug,
            'name': election.name,
            'election_type': election.election_type,
            'polling_date': election.polling_date.isoformat() if election.polling_date else None,
            'polls_close': election.polls_close.isoformat() if election.polls_close else None,
            'results_versions': versions,
        })

    elections.sort(key=lambda item: item['polling_date'] or '', reverse=True)
    return {
        'version': 1,
        'snapshot_base': f"https://{settings.ELECTIONS_SNAPSHOT_DOMAIN}/",
        'elections': elections,
    }


def publishable_versions():
    """Results versions worth publishing, newest election first.

    The incumbency prefetch is not an optimisation. Every save of an election or
    a results version queues a full manifest rewrite, and without it that
    rewrite issues two queries per version for data most of them do not have.

    Both are ordered here rather than in the builder, so that the prefetched
    rows arrive in the order the manifest wants them and no second query is
    issued to sort them. Electorates read alphabetically; parties lead with the
    ones defending the most seats in total, which is the comparison a reader
    makes -- not the most electorate seats, which would put a party of eleven
    above one of fifteen.
    """
    return ElectionResultVersion.objects.select_related('election').prefetch_related(
        Prefetch('electorate_incumbents',
                 queryset=ElectorateIncumbent.objects.order_by('electorate__name')),
        Prefetch('party_incumbents',
                 queryset=PartyIncumbent.objects.annotate(
                     seats_held=F('electorate_seats') + F('list_seats')
                 ).order_by('-seats_held', 'persistent_party_id')),
    ).order_by('-election__polling_date', 'election__name', 'name')


def elections_for(versions):
    """Group results versions by their election, preserving order."""
    grouped = {}
    for version in versions:
        grouped.setdefault(version.election, []).append(version)
    return grouped
