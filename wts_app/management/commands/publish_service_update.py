"""Post a service announcement to an event's feed.

The feed beside the election dashboard is written by `election-feed-worker`,
which turns changes in the results into entries. A service announcement is the
one type that comes from a person: a note that a count has paused, that a
figure is being checked, that the site itself is having trouble.

Django holds no copy. This writes the document and forgets it, the same way
typing it into the Firebase console would, and nothing here is archived with
the election::

    python manage.py publish_service_update --event ge2026 \\
        --title "Counting has paused" \\
        --body "The Electoral Commission has paused the count until 10.30 pm." \\
        --dry-run

The event is the Firestore event id, which is what the documents carry -- not
an election or version slug.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from wts_app.firebase import push
from wts_app.firebase.client import get_firestore_client


class Command(BaseCommand):
    help = "Post a service announcement to an event's feed in Firestore."

    def add_arguments(self, parser):
        parser.add_argument('--event', required=True,
                            help='Firestore event id, as the documents carry it.')
        parser.add_argument('--title', required=True,
                            help='The headline. Keep it to a few words.')
        parser.add_argument('--body', default='',
                            help='A sentence or two. Optional.')
        parser.add_argument('--url', help='Somewhere to send a reader. Optional.')
        parser.add_argument('--url-behaviour', default='internal',
                            choices=sorted(push.URL_BEHAVIOURS),
                            help='Whether the URL navigates within the site '
                                 '(internal) or opens a new tab (external).')
        parser.add_argument('--id',
                            help='Overwrite an existing announcement, to correct one '
                                 'rather than contradict it with a second entry.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print the document without writing to Firestore.')

    def handle(self, *args, **options):
        event_id = options['event']
        title = options['title'].strip()
        if not title:
            raise CommandError('--title cannot be empty.')

        url = options['url']
        if options['url_behaviour'] != 'internal' and not url:
            raise CommandError('--url-behaviour has no meaning without --url.')

        # Reading is not gated, so this check runs in every environment. An
        # announcement on the wrong event is worse than no announcement, and
        # the event id is the one thing here that cannot be proof-read.
        self._require_event(event_id, options['dry_run'])

        payload = push.build_service_update(
            event_id, title, options['body'], url, options['url_behaviour'])

        if options['dry_run']:
            self.stdout.write(f'feed/{options["id"] or "<new id>"}')
            self.stdout.write(json.dumps(payload, indent=2, default=str))
            return

        try:
            document_id = push.push_service_update(
                event_id, title, options['body'], url, options['url_behaviour'],
                document_id=options['id'])
        except push.FirebasePushDisabled as exc:
            raise CommandError(str(exc))

        self.stdout.write(self.style.SUCCESS(f'Posted feed/{document_id}'))
        self.stdout.write(
            'Readers with the dashboard open will see it on their next snapshot. '
            'It is not archived: turning the count off takes it with the feed.')

    def _require_event(self, event_id, dry_run):
        """Fail on an event id that does not exist, and say which ones do."""
        try:
            db = get_firestore_client()
            document = db.collection(push.EVENTS).document(event_id).get()
        except Exception as exc:  # noqa: BLE001 -- any failure here is the same answer
            # Without credentials there is nothing to check against. A dry run
            # should still print its payload; a real write will fail on the
            # push gate a moment later and say so properly.
            self.stderr.write(self.style.WARNING(
                f'Could not check the event id ({exc}). Continuing.'))
            return

        if document.exists:
            return

        live = [
            snapshot.id for snapshot in
            db.collection(push.EVENTS).where('is_live', '==', True).stream()
        ]
        known = f' Live events: {", ".join(live)}.' if live else ' No events are live.'
        message = f'No events/{event_id} document in Firestore.{known}'

        if dry_run:
            self.stderr.write(self.style.WARNING(message))
            return
        raise CommandError(message)
