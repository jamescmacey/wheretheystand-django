"""Keep the ElectionVotingPlaces Algolia index in step with this database.

Registering ElectionVotingPlace in wts_app/index.py covers a single save, which
is what an admin correcting one address does. It does not cover how voting
places actually arrive: firebase_migrate_elections bulk_creates them a few
thousand at a time, and bulk_create sends no post_save signal. So every import
has to be followed by a sync, which is what this does.

    # One version, after importing its reference data.
    sync_voting_places.delay(results_version_id=str(version.id))

    # Every version, rebuilding the index from scratch.
    sync_voting_places.delay()
"""

import logging

from algoliasearch.http.exceptions import AlgoliaException
from algoliasearch_django import algolia_engine, get_adapter, reindex_all
from celery import shared_task

from wts_app.models.elections import ElectionVotingPlace

logger = logging.getLogger(__name__)

# Algolia caps a batch at 1000 records, and the client chunks to that anyway.
BATCH_SIZE = 1000


@shared_task(name="wts_app.voting_places.sync_voting_places")
def sync_voting_places(results_version_id=None, batch_size=BATCH_SIZE):
    """Push voting places to Algolia.

    With a results version, pushes that version's places and removes the ones
    the index still holds for it that are no longer in this database. Without
    one, rebuilds the whole index: that runs through a temporary index and is
    moved into place atomically, so a search during a rebuild sees the old
    records rather than a half-built index.

    Returns the counts, which the management command prints and Celery stores
    against the task.
    """
    if results_version_id is None:
        indexed = reindex_all(ElectionVotingPlace, batch_size=batch_size)
        logger.info("Reindexed %s voting places", indexed)
        return {'results_version': None, 'indexed': indexed or 0, 'deleted': 0}

    index = get_adapter(ElectionVotingPlace)
    client = algolia_engine.client

    # Filtering on results_version only works once the attribute is faceted, so
    # the settings have to be on the index before the browse below. Applying
    # them here also means a change to this index's settings takes effect on the
    # next sync, rather than waiting for someone to run algolia_applysettings.
    index.set_settings()

    places = index.get_queryset().filter(results_version_id=results_version_id)
    records = [index.get_raw_record(place) for place in places
               if index._should_index(place)]

    if records:
        client.save_objects(
            index_name=index.index_name,
            objects=records,
            wait_for_tasks=True,
            batch_size=batch_size,
        )

    # Deleted rows, and rows whose version changed, leave records behind. The
    # objectID is the row's UUID, so whatever the index holds for this version
    # and this database does not is stale.
    stale = _indexed_object_ids(client, index.index_name, results_version_id)
    stale -= {record['objectID'] for record in records}

    if stale:
        client.delete_objects(
            index_name=index.index_name,
            object_ids=sorted(stale),
            wait_for_tasks=True,
            batch_size=batch_size,
        )

    logger.info("Synced %s voting places for version %s, removed %s",
                len(records), results_version_id, len(stale))
    return {
        'results_version': str(results_version_id),
        'indexed': len(records),
        'deleted': len(stale),
    }


def _indexed_object_ids(client, index_name, results_version_id):
    """The objectIDs the index currently holds for one results version.

    Empty where the index does not exist yet, which is the first sync into a
    fresh Algolia application: there is nothing stale in an index that is not
    there.
    """
    object_ids = set()

    def collect(response):
        object_ids.update(hit.object_id for hit in response.hits)

    try:
        client.browse_objects(
            index_name=index_name,
            aggregator=collect,
            browse_params={
                'filters': f'results_version:"{results_version_id}"',
                'attributesToRetrieve': ['objectID'],
                'hitsPerPage': BATCH_SIZE,
            },
        )
    except AlgoliaException as exc:
        logger.warning("Could not browse %s for stale records: %s", index_name, exc)
        return set()

    return object_ids
