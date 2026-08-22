"""Background work for the Firestore link.

Pushing to Firestore and importing from it are both network round trips, so
neither belongs in a request or an admin save. The work itself lives in
wts_app.firebase; these are thin wrappers so it can also be run directly from a
management command when a broker is not available.
"""

from celery import shared_task

from ..firebase import ingest, push
from ..models.elections import ElectionResultVersion


@shared_task(name="wts_app.firebase.push_event")
def push_event(version_id):
    """Push one results version's events document to Firestore."""
    return push.push_event(version_id)


PERSISTENT_HANDLERS = {
    'persistent_parties': push.push_persistent_parties,
    'persistent_candidates': push.push_persistent_candidates,
    'persistent_electorates': push.push_persistent_electorates,
    'persistent_voting_places': push.push_persistent_voting_places,
}


@shared_task(name="wts_app.firebase.push_persistent")
def push_persistent(only=None, ids=None):
    """Push the persistent collections.

    ``only`` is an optional list of collection names, matching the keys returned
    by push_all_persistent. ``ids`` narrows to particular rows, and applies to
    every named collection -- pass one collection with it, which is what the
    admin does when someone selects specific rows.
    """
    if not only:
        return push.push_all_persistent()

    return {name: PERSISTENT_HANDLERS[name](ids=ids)
            for name in only if name in PERSISTENT_HANDLERS}


@shared_task(name="wts_app.firebase.publish_manifest")
def publish_manifest():
    """Rewrite the published manifest, leaving payloads alone.

    Queued whenever an election or results version is saved. Without it, the
    `is_live` switch and everything else the manifest carries would change in
    Django and nowhere a visitor can see.
    """
    from ..snapshots import publisher

    return publisher.publish_manifest_only(publisher.StorageWriter())


@shared_task(name="wts_app.firebase.sync_live_version")
def sync_live_version(version_id):
    """Import one version's results from Firestore and publish them.

    A one-shot, not a schedule. Nothing about a live count depends on this
    running -- clients read Firestore directly -- so there is no periodic
    variant of it any more.
    """
    version = ElectionResultVersion.objects.select_related('election').get(id=version_id)
    return ingest.sync_live_version(version)
