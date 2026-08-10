"""Propagate election metadata whenever it changes in Django.

Two things travel automatically, and both are small and singular:

- The **Firestore events document**, which is what the results worker and the
  client read for the event's dates, embargo and coalition ordering. One row per
  results version, and getting it wrong during an event is the expensive failure.
- The **published manifest**, which carries `is_live`, `is_final` and the
  version's name. The client never reads this database -- it reads the manifest
  -- so changing `is_live` in the admin has no effect on anyone until the
  manifest is rewritten. Leaving that manual would make the kill switch inert.

Deliberately *not* automatic:

- **Snapshot payloads.** Reference, results and persistent data run to over a
  megabyte and change when the data changes, not when a description is edited.
  Republishing them on every save would be waste. They stay on the admin action
  and the management command.
- **Persistent entities in Firestore.** Re-importing a few thousand candidates
  would enqueue a few thousand tasks.
"""

import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .client import is_firebase_push_enabled
from ..models.elections import Election, ElectionResultVersion

logger = logging.getLogger(__name__)


def _queue_after_commit(task, *args, description):
    """Queue background work once the transaction lands.

    on_commit matters: without it the worker can pick the task up before the row
    commits and act on the previous values. A broker that is down must never
    take an admin save down with it, so failures are logged and swallowed.
    """
    def run():
        try:
            task.delay(*args)
        except Exception:
            logger.exception("Could not queue %s", description)

    transaction.on_commit(run)


@receiver(post_save, sender=ElectionResultVersion,
          dispatch_uid="wts_app.firebase.push_event_on_save")
def push_event_on_save(sender, instance, **kwargs):
    """Queue a push of the Firestore events document."""
    if not is_firebase_push_enabled():
        return
    if instance.access_mode != 'firebase':
        return

    from ..tasks.firebase import push_event
    _queue_after_commit(push_event, str(instance.pk),
                        description=f"Firestore push for {instance.pk}")


@receiver(post_save, sender=ElectionResultVersion,
          dispatch_uid="wts_app.firebase.publish_manifest_on_version_save")
@receiver(post_save, sender=Election,
          dispatch_uid="wts_app.firebase.publish_manifest_on_election_save")
def publish_manifest_on_save(sender, instance, **kwargs):
    """Rewrite the published manifest after an election or version changes.

    Only the manifest: it is a few kilobytes, rebuilt from the paths each version
    was last published at, so nothing is regenerated. This is what makes the
    `is_live` kill switch actually reach anyone -- within the manifest's
    thirty-second cache lifetime.

    A version that has never been published has no recorded paths and stays out
    of the manifest until it is published properly for the first time.
    """
    from django.conf import settings
    if not getattr(settings, 'ELECTIONS_PUBLISH_ENABLED', False):
        # Not an error: development and staging simply do not publish.
        return

    from ..tasks.firebase import publish_manifest
    _queue_after_commit(publish_manifest,
                        description=f"manifest publish after saving {instance.pk}")
