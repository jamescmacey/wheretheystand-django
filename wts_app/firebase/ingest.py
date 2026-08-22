"""Pull results from Firestore into Django.

Clients no longer depend on this during a count: they read tallies from
Firestore directly, and reference data from wherever the event document points
them. Nothing here has to run for the dashboard to work on the night.

It still matters twice. Running it once after the worker builds reference data
puts that data on R2 and sets `refdata_url`, which takes several hundred
document reads per visitor off the Firestore bill. Running it before the count
is ended -- and again afterwards -- is how results reach this database for the
permanent archive, and how the published snapshot becomes current enough to be
worth falling back to.
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
    """Republish this version's payloads and the manifest that names them.

    Every payload is content addressed, so publishing one produces a path that
    nothing can reach until the manifest names it. Recording those paths and
    rewriting the manifest is therefore part of publishing, not an optional
    extra -- omitting it leaves the object orphaned in the bucket and the
    manifest pointing at the previous one.

    The manifest is written last, and is rebuilt from the paths each version
    was last published at, so no other version's payloads are regenerated.
    """
    from ..snapshots import publisher

    writer = publisher.StorageWriter()
    paths = dict(version.snapshot_paths or {})

    if include_reference:
        paths['persistent'] = publisher.publish_persistent(writer)
        paths['reference'] = publisher.publish_reference(writer, version)

    paths['results'] = publisher.publish_results(writer, version)

    ElectionResultVersion.objects.filter(id=version.id).update(
        snapshot_paths=paths,
        last_snapshot_published_at=timezone.now())
    version.snapshot_paths = paths

    publisher.publish_manifest_only(writer)

    return {
        'objects': len(writer.written),
        'persistent': paths.get('persistent'),
        'reference': paths.get('reference') if include_reference else None,
    }


def publish_refdata_url(version, reference_path):
    """Point the event document at reference data just published to R2.

    A cost saving rather than a requirement: a client that finds no
    `refdata_url` reads reference data out of Firestore instead and renders
    exactly the same dashboard. So a Firestore write being refused here is
    logged and stepped over rather than failing the sync that produced a
    perfectly good snapshot.
    """
    from django.conf import settings

    from . import push

    if not version.firebase_id or not reference_path:
        return None

    url = (f"https://{settings.ELECTIONS_SNAPSHOT_DOMAIN}/"
           f"{reference_path.lstrip('/')}")
    try:
        push.push_refdata_url(version, url)
    except push.FirebasePushDisabled:
        logger.warning(
            "Firestore writes are disabled; %s will read reference data from "
            "Firestore rather than %s", version.firebase_id, url)
        return None

    return url


def sync_live_version(version):
    """One pass for one version: import what is new, then publish it."""
    sync_event_metadata(version)

    result = {'event_id': version.firebase_id, 'reference_imported': False}

    # Only once the worker says reference data exists, and only if this database
    # does not already hold it.
    if version.refdata_built and not has_reference_data(version):
        sync_reference_data(version)
        result['reference_imported'] = True

    sync_results(version)

    # Republishing reference data only matters on the pass that imported it;
    # after that it is unchanged and its snapshot path would be identical.
    result.update(refresh_snapshots(
        version, include_reference=result['reference_imported']))

    if result['reference_imported']:
        result['refdata_url'] = publish_refdata_url(version, result['reference'])

    return result
