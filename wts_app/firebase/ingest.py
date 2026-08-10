"""Pull results from Firestore into Django during a live event.

This is the loop that holds the architecture together. The worker writes
results to Firestore; clients read them live from there. But clients read
*everything else* -- reference data, party colours, the results a
server-rendered page shows before its live connection opens -- from published
snapshots, and those are generated from this database.

So Django has to keep up during an event. Without this, results would arrive
with no candidate or party names attached, server-rendered pages would be
empty, and taking the event off live would fall back to nothing.
"""

import logging

from django.core.management import call_command
from django.utils import timezone

from .client import event_filter, get_firestore_client
from ..models.elections import ElectionResultVersion

logger = logging.getLogger(__name__)


def live_versions():
    """Results versions currently being counted."""
    return ElectionResultVersion.objects.select_related('election').filter(
        is_live=True).exclude(firebase_id__isnull=True)


def firestore_results_count(version):
    """How many results documents Firestore holds for a version.

    Uses an aggregation query rather than streaming the documents. Counting by
    iterating would bill a read per document -- thousands of them once voting
    places are reported -- to produce a single number.
    """
    db = get_firestore_client()
    query = event_filter(db.collection('results'), version.firebase_id)
    result = query.count().get()
    # [[AggregationResult]] for a single aggregation over a single query.
    return int(result[0][0].value)


def read_event_metadata(version):
    """The fields the worker owns on the events document, read but not stored.

    ``refdata_built`` is the worker telling us reference data exists to import.
    Django never writes it, so it has to be pulled in before it can be acted on
    -- and anything reporting on it must read Firestore rather than trusting the
    local copy, which is only as current as the last sync.
    """
    db = get_firestore_client()
    document = db.collection('events').document(version.firebase_id).get()
    if not document.exists:
        logger.warning("No Firestore event document for %s", version.firebase_id)
        return {}

    data = document.to_dict() or {}
    return {
        'refdata_built': bool(data.get('refdata_built', False)),
        'archived': bool(data.get('archived', False)),
    }


def sync_event_metadata(version):
    """Read those fields and store them against the version."""
    updates = read_event_metadata(version)
    if not updates:
        return {}

    ElectionResultVersion.objects.filter(id=version.id).update(**updates)
    for field, value in updates.items():
        setattr(version, field, value)
    return updates


def has_reference_data(version):
    """Whether this version's reference data has already been imported."""
    return version.electionelectorate_set.exists()


def sync_reference_data(version):
    """Import the worker's reference data for a version.

    Built once, at the start of an event, so this runs until it lands and then
    stops: re-importing several hundred rows every couple of minutes would be a
    lot of work for no change.
    """
    logger.info("Syncing reference data for %s", version.firebase_id)
    call_command('firebase_migrate_elections', migrate=True,
                 event_id=version.firebase_id, verbosity=0)
    return version.firebase_id


def sync_results(version):
    """Import the worker's results for a version."""
    logger.info("Syncing results for %s", version.firebase_id)
    call_command('firebase_migrate_results', migrate=True,
                 event_id=version.firebase_id, verbosity=0)
    ElectionResultVersion.objects.filter(id=version.id).update(
        last_firebase_push_at=timezone.now())
    return version.firebase_id


def refresh_snapshots(version, *, include_reference=False):
    """Republish the snapshots clients read.

    Only the rolling results file is rewritten each cycle. It has a fixed path,
    so the manifest -- the one mutable pointer clients depend on -- stays still
    while results churn.
    """
    from ..snapshots import publisher

    writer = publisher.StorageWriter()
    persistent_path = None

    if include_reference:
        persistent_path = publisher.publish_persistent(writer)
        publisher.publish_reference(writer, version)

    publisher.publish_rolling_results(writer, version)

    ElectionResultVersion.objects.filter(id=version.id).update(
        last_snapshot_published_at=timezone.now())

    return {'objects': len(writer.written), 'persistent': persistent_path}


def sync_live_version(version):
    """One cycle for one live version: import, then republish."""
    sync_event_metadata(version)

    result = {'event_id': version.firebase_id, 'reference_imported': False}

    # Only once the worker says reference data exists, and only if this database
    # does not already hold it.
    if version.refdata_built and not has_reference_data(version):
        sync_reference_data(version)
        result['reference_imported'] = True

    sync_results(version)

    # Republishing reference data only matters on the cycle that imported it;
    # after that it is unchanged and its snapshot path would be identical.
    result.update(refresh_snapshots(
        version, include_reference=result['reference_imported']))
    return result
