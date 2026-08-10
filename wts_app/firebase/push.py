"""Push curated election data from Django into Firestore.

Django owns two things the results worker does not: the event's own description
(names, dates, embargo, coalition ordering, incumbents) and the persistent
entities that survive across elections (party colours, and the links from
candidates to people on the site). Both flow outward from here.

Everything else in Firestore -- reference data and the results themselves --
belongs to the worker. Django reads those and never writes them.
"""

import logging

from django.utils import timezone

from .client import get_firestore_client, is_firebase_push_enabled
from ..models.elections import (
    ElectionResultVersion,
    PersistentCandidate,
    PersistentParty,
    PersistentVotingPlace,
)
from ..models.electorates import Electorate

logger = logging.getLogger(__name__)

EVENTS = 'events'
PERSISTENT_PARTIES = 'persistent_parties'
PERSISTENT_CANDIDATES = 'persistent_candidates'
PERSISTENT_ELECTORATES = 'persistent_electorates'
PERSISTENT_VOTING_PLACES = 'persistent_voting_places'

# Django spells this with a hyphen; the Firestore documents use an underscore.
ELECTION_TYPES = {'by-election': 'by_election', 'general': 'general'}


class FirebasePushDisabled(RuntimeError):
    """Raised when a push is attempted in an environment that may not write."""


def _require_enabled():
    if not is_firebase_push_enabled():
        raise FirebasePushDisabled(
            "Firestore writes are disabled here. Set FIREBASE_PUSH_ENABLED=true "
            "only in production: other environments share the same service "
            "account and would overwrite live event data."
        )


def _isoformat(value):
    return value.isoformat() if value else None


def event_document_id(version):
    """A stable Firestore id for a results version.

    Derived from slugs when the version has no id yet, so that repeated pushes
    land on the same document instead of creating duplicates.
    """
    if version.firebase_id:
        return version.firebase_id
    return f"{version.election.slug}_{version.slug}"


def _persistent_party_firebase_ids(ids):
    """Resolve an ordered list of party UUIDs to their Firestore ids."""
    if not ids:
        return []
    by_id = {
        str(party.id): party.firebase_id
        for party in PersistentParty.objects.filter(id__in=ids)
    }
    resolved = []
    for value in ids:
        firebase_id = by_id.get(str(value))
        if firebase_id:
            resolved.append(firebase_id)
        else:
            logger.warning(
                "Persistent party %s has no Firestore id; dropped from coalition order",
                value)
    return resolved


def _comparison_event_ids(ids):
    if not ids:
        return []
    return list(
        ElectionResultVersion.objects
        .filter(id__in=ids)
        .exclude(firebase_id__isnull=True)
        .values_list('firebase_id', flat=True)
    )


def build_event_document(version):
    """The events document for one results version.

    Deliberately omits refdata_built: the worker owns that field, and this
    payload is always merged rather than replaced so as not to clobber it.
    """
    election = version.election
    return {
        'name': version.name,
        'slug': version.slug,
        'description': version.description,
        'date': election.polling_date.isoformat() if election.polling_date else None,
        'election_type': ELECTION_TYPES.get(election.election_type, election.election_type),
        'polls_close': _isoformat(election.polls_close),
        'voting_period_start': (election.voting_period_start.isoformat()
                                if election.voting_period_start else None),
        'voting_period_end': (election.voting_period_end.isoformat()
                              if election.voting_period_end else None),
        'embargo_start': _isoformat(version.embargo_start),
        'embargo_end': _isoformat(version.embargo_end),
        'is_live': version.is_live,
        'is_final': version.is_final,
        'archived': version.archived,
        'archived_url': version.archived_url,
        'card_url': version.card_url,
        'vp_finder_url': version.vp_finder_url,
        'vp_numbering_scheme': version.vp_numbering_scheme,
        'result_targets': version.result_targets or [],
        'incumbents': version.incumbents or [],
        'comparison_events': _comparison_event_ids(version.comparison_version_ids),
        'coalition_order_left': _persistent_party_firebase_ids(version.coalition_order_left),
        'coalition_order_right': _persistent_party_firebase_ids(version.coalition_order_right),
        'wts_id': str(version.id),
    }


def build_persistent_party_document(party):
    return {
        'display_name': party.display_name,
        'short_name': party.short_name,
        'abbreviation': party.abbreviation,
        'colour': party.colour,
        'wts_id': str(party.id),
    }


def build_persistent_candidate_document(candidate):
    return {
        'display_name': candidate.display_name,
        'wts_id': str(candidate.id),
        # The site's own person record, so results can link to a profile.
        'wts_person_id': str(candidate.person_id) if candidate.person_id else None,
    }


def build_persistent_electorate_document(electorate):
    return {
        'name': electorate.name,
        'electorate_type': electorate.electorate_type,
        'status': electorate.status,
        'wts_id': str(electorate.id),
        'wts_slug': electorate.slug,
    }


def build_persistent_voting_place_document(place):
    return {
        'address': place.address,
        'latitude': place.latitude,
        'longitude': place.longitude,
        'wts_id': str(place.id),
    }


def _write(db, collection, document_id, payload, dry_run):
    """Merge a document into Firestore.

    Always a merging write against a known id. A replacing write would drop
    fields the worker owns on the same document, and an add() would create a
    duplicate every time this ran.
    """
    if dry_run:
        logger.info("[dry run] %s/%s <- %s", collection, document_id, payload)
        return document_id
    db.collection(collection).document(str(document_id)).set(payload, merge=True)
    return document_id


def push_event(version_id, *, dry_run=False):
    """Push one results version's events document."""
    if not dry_run:
        _require_enabled()

    version = ElectionResultVersion.objects.select_related('election').get(id=version_id)
    document_id = event_document_id(version)
    db = None if dry_run else get_firestore_client()

    _write(db, EVENTS, document_id, build_event_document(version), dry_run)

    if not dry_run:
        # Record the id we settled on, so the next push targets the same
        # document even if the slugs change.
        ElectionResultVersion.objects.filter(id=version.id).update(
            firebase_id=document_id, last_firebase_push_at=timezone.now())

    return document_id


def _push_persistent(model, collection, builder, ids=None, *, dry_run=False,
                     id_field='firebase_id'):
    """Push a persistent collection, keying documents stably.

    Rows without a Firestore id are given one -- their Django UUID -- which is
    written back so the mapping holds for later pushes.
    """
    if not dry_run:
        _require_enabled()

    queryset = model.objects.all()
    if ids is not None:
        queryset = queryset.filter(id__in=ids)

    db = None if dry_run else get_firestore_client()
    count = 0

    for obj in queryset:
        document_id = getattr(obj, id_field, None) or str(obj.id)
        _write(db, collection, document_id, builder(obj), dry_run)
        if not dry_run and getattr(obj, id_field, None) != document_id:
            model.objects.filter(id=obj.id).update(**{id_field: document_id})
        count += 1

    return count


def push_persistent_parties(ids=None, *, dry_run=False):
    return _push_persistent(PersistentParty, PERSISTENT_PARTIES,
                            build_persistent_party_document, ids, dry_run=dry_run)


def push_persistent_candidates(ids=None, *, dry_run=False):
    return _push_persistent(PersistentCandidate, PERSISTENT_CANDIDATES,
                            build_persistent_candidate_document, ids, dry_run=dry_run)


def push_persistent_voting_places(ids=None, *, dry_run=False):
    return _push_persistent(PersistentVotingPlace, PERSISTENT_VOTING_PLACES,
                            build_persistent_voting_place_document, ids, dry_run=dry_run)


def push_persistent_electorates(ids=None, *, dry_run=False):
    """Push persistent electorates.

    Keyed on legacy_id, because that integer is what Firestore documents use to
    refer to an electorate across elections. An electorate without one is
    skipped rather than given an invented key, which would not match anything.
    """
    if not dry_run:
        _require_enabled()

    queryset = Electorate.objects.exclude(legacy_id__isnull=True)
    if ids is not None:
        queryset = queryset.filter(id__in=ids)

    skipped = Electorate.objects.filter(legacy_id__isnull=True)
    if ids is not None:
        skipped = skipped.filter(id__in=ids)
    for electorate in skipped:
        logger.warning(
            "Electorate %s (%s) has no legacy_id and was not pushed",
            electorate.name, electorate.id)

    db = None if dry_run else get_firestore_client()
    count = 0
    for electorate in queryset:
        _write(db, PERSISTENT_ELECTORATES, electorate.legacy_id,
               build_persistent_electorate_document(electorate), dry_run)
        count += 1

    return count


def push_all_persistent(*, dry_run=False):
    """Push every persistent collection. Returns a count per collection."""
    return {
        'persistent_parties': push_persistent_parties(dry_run=dry_run),
        'persistent_candidates': push_persistent_candidates(dry_run=dry_run),
        'persistent_electorates': push_persistent_electorates(dry_run=dry_run),
        'persistent_voting_places': push_persistent_voting_places(dry_run=dry_run),
    }
