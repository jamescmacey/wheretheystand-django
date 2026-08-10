"""Shared Firebase Admin SDK client.

The election results project uses a dedicated Firebase project
(``wheretheystand-elections``) which is separate from the Google Cloud project
used for private file storage. Credentials come from the ``FIREBASE_CONFIG``
environment variable, which holds the whole service account JSON.

Use :func:`get_firestore_client` everywhere rather than initialising the SDK
directly, so that a single named app is shared across management commands,
Celery workers and the request/response cycle.
"""

import firebase_admin
from firebase_admin import credentials, firestore

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

# A named app, rather than the SDK default, so that initialising is idempotent
# and cannot collide with any other Firebase app in the process.
_APP_NAME = "wts"


def get_firebase_app():
    """Return the shared Firebase app, initialising it on first use.

    Safe to call repeatedly, and safe under Celery prefork and the runserver
    autoreloader, both of which import modules more than once.
    """
    try:
        return firebase_admin.get_app(_APP_NAME)
    except ValueError:
        if not settings.FIREBASE_CONFIG:
            raise ImproperlyConfigured(
                "FIREBASE_CONFIG is not set. Firestore access requires the "
                "service account JSON for the wheretheystand-elections project."
            )
        return firebase_admin.initialize_app(
            credentials.Certificate(settings.FIREBASE_CONFIG), name=_APP_NAME
        )


def get_firestore_client():
    """Return a Firestore client bound to the shared Firebase app."""
    return firestore.client(app=get_firebase_app())


def is_firebase_push_enabled():
    """Whether this environment may write to Firestore.

    Development and staging share the production ``FIREBASE_CONFIG`` but must
    never write to it, so every outbound path checks this first. Reading is not
    gated: it is harmless and useful outside production.
    """
    return bool(settings.FIREBASE_CONFIG) and settings.FIREBASE_PUSH_ENABLED


def event_filter(collection_ref, event_id):
    """Return ``collection_ref`` filtered to a single event.

    Firestore stores election documents in flat top-level collections scoped by
    an ``event_id`` field rather than in subcollections. Filtering server side
    matters: the ``results`` collection holds every document for every event, so
    streaming it in full and filtering in Python reads (and bills for) hundreds
    of thousands of documents to find a few hundred.
    """
    # Imported lazily so that importing this module does not require the
    # google-cloud-firestore internals to be present.
    from google.cloud.firestore_v1.base_query import FieldFilter

    return collection_ref.where(filter=FieldFilter("event_id", "==", event_id))
