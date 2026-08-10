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

from django.db.models import Prefetch


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


def build_voting_places_reference(results_version):
    """Every voting place for one results version."""
    voting_places = ElectionVotingPlace.objects.filter(
        results_version=results_version).select_related('physical_electorate')
    return {'voting_places': ElectionVotingPlaceSerializer(
        voting_places, many=True).data}


def build_version_entry(results_version, paths):
    """One results version as it appears in the manifest.

    ``paths`` maps a payload name to its published path, and is supplied by the
    publisher because it depends on content hashes.
    """
    return {
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
        'paths': paths,
    }


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
    """Results versions worth publishing, newest election first."""
    return ElectionResultVersion.objects.select_related('election').order_by(
        '-election__polling_date', 'election__name', 'name')


def elections_for(versions):
    """Group results versions by their election, preserving order."""
    grouped = {}
    for version in versions:
        grouped.setdefault(version.election, []).append(version)
    return grouped
