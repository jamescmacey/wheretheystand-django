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
        total_stale = 0
        blocked = []

        for name in names:
            collection, model = COLLECTIONS[name]
            entities = {str(value) for value in model.objects.values_list('id', flat=True)}
            present = {document.id for document in db.collection(collection).stream()}

            migrated = entities & present
            unmigrated = entities - present
            stale = sorted(present - entities)

            # Report the collection size first. Without it there is no way to
            # tell a finished migration from one that never ran: "679 to delete"
            # means something quite different out of 1358 than out of 679.
            self.stdout.write(f'{collection}: {len(present)} document(s)')
            self.stdout.write(
                f'    {len(migrated)} at a current Django id, of {len(entities)} entities')
            self.stdout.write(f'    {len(stale)} to delete')
            for document_id in stale[:5]:
                self.stdout.write(f'        {document_id}')
            if len(stale) > 5:
                self.stdout.write(f'        ... and {len(stale) - 5} more')

            # The hazard this guards against: deleting an old document for an
            # entity that never got a new one removes it from Firestore
            # entirely. That is not recoverable from here.
            if unmigrated:
                blocked.append((collection, len(unmigrated)))
                self.stdout.write(self.style.ERROR(
                    f'    {len(unmigrated)} entities have NO document at their UUID '
                    f'-- run align_firebase_ids before pruning'))

            total_stale += len(stale)

        if blocked:
            raise CommandError(
                'Refusing to delete anything. These collections have entities with '
                'no document at their Django id, so the documents below are the only '
                'copy that exists: '
                + ', '.join(f'{name} ({count})' for name, count in blocked)
                + '. Run align_firebase_ids first.')

        if not apply:
            self.stdout.write(self.style.WARNING(
                f'\n{total_stale} document(s) would be deleted. Nothing was written. '
                'Re-run with --apply once the counts above look right.'))
            return

        for name in names:
            collection, model = COLLECTIONS[name]
            entities = {str(value) for value in model.objects.values_list('id', flat=True)}
            for document in db.collection(collection).stream():
                if document.id not in entities:
                    push._delete(db, collection, document.id, dry_run=False)
            self.stdout.write(self.style.SUCCESS(f'{collection}: pruned'))
