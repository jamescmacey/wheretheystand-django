"""Remove persistent documents whose ids nothing refers to any more.

`align_firebase_ids` re-keys the persistent collections by Django UUID and
leaves the old ObjectId-keyed documents in place, so that nothing is destroyed
before the new ids have been shown to work. This clears them afterwards.

It only ever deletes a document whose id is **not** a current Django id for that
collection, so a document that is still the canonical one for an entity can
never be removed by it. Run the dry run first and read the list:

    python manage.py prune_persistent_documents --dry-run

Deleting is not reversible without a Firestore backup, so `--apply` is required
to write anything.
"""

from django.core.management.base import BaseCommand, CommandError

from wts_app.firebase import push
from wts_app.firebase.client import get_firestore_client
from wts_app.models.elections import (
    PersistentCandidate,
    PersistentParty,
    PersistentVotingPlace,
)
from wts_app.models.electorates import Electorate

COLLECTIONS = {
    'parties': (push.PERSISTENT_PARTIES, PersistentParty),
    'candidates': (push.PERSISTENT_CANDIDATES, PersistentCandidate),
    'electorates': (push.PERSISTENT_ELECTORATES, Electorate),
    'voting-places': (push.PERSISTENT_VOTING_PLACES, PersistentVotingPlace),
}


class Command(BaseCommand):
    help = ('Delete persistent Firestore documents left behind by the move to '
            'Django UUIDs.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--only',
            help='Comma separated subset of: ' + ', '.join(sorted(COLLECTIONS)),
        )
        parser.add_argument('--dry-run', action='store_true',
                            help='List what would be deleted. The default.')
        parser.add_argument('--apply', action='store_true',
                            help='Actually delete. Not reversible.')

    def handle(self, *args, **options):
        if options['only']:
            names = [n.strip() for n in options['only'].split(',') if n.strip()]
            unknown = [n for n in names if n not in COLLECTIONS]
            if unknown:
                raise CommandError(
                    f'Unknown collection(s): {", ".join(unknown)}. '
                    f'Choose from: {", ".join(sorted(COLLECTIONS))}')
        else:
            names = sorted(COLLECTIONS)

        apply = options['apply']
        if apply:
            push._require_enabled()

        db = get_firestore_client()
        total = 0

        for name in names:
            collection, model = COLLECTIONS[name]
            current = {str(value) for value in model.objects.values_list('id', flat=True)}

            stale = [document.id for document in db.collection(collection).stream()
                     if document.id not in current]

            self.stdout.write(f'{collection}: {len(stale)} document(s) not a current '
                              f'Django id, of {len(current)} entities')
            for document_id in stale[:5]:
                self.stdout.write(f'    {document_id}')
            if len(stale) > 5:
                self.stdout.write(f'    ... and {len(stale) - 5} more')

            if apply:
                for document_id in stale:
                    push._delete(db, collection, document_id, dry_run=False)
                self.stdout.write(self.style.SUCCESS(
                    f'  deleted {len(stale)} document(s)'))

            total += len(stale)

        if not apply:
            self.stdout.write(self.style.WARNING(
                f'\n{total} document(s) would be deleted. Nothing was written. '
                'Re-run with --apply once the list looks right.'))
