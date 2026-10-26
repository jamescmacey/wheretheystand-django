"""Make every persistent entity's Firestore id its Django UUID.

Firestore document ids for the persistent collections were Mongo ObjectIds
inherited from an earlier implementation, and electorates were keyed on
`legacy_id` instead. That left two identity spaces to translate between: the
client carried a whole index whose only job was mapping a Firestore id back to
the Django UUID the contract actually uses.

This collapses them. Afterwards a persistent entity has one id everywhere, and
`persistent_*_id` on the worker's `election_*` documents is directly the UUID.

It is safe to run more than once. Rows already aligned are left alone, and the
push steps are merges.

    python manage.py align_firebase_ids --dry-run

Electorates take a slightly different path, and it is worth knowing which.
They have no `firebase_id` column -- they were keyed on `legacy_id`, which is
already on the row -- so nothing in this database changes for them. Their
Firestore documents still move to the UUID, and the `election_*` references
still get re-pointed, exactly like the rest.

Order matters, and this command does the first three steps itself:

  1. Point each Django row's `firebase_id` at its own UUID, where it has one.
  2. Push the persistent collections, creating documents at the new ids. The
     old ones are left in place -- nothing is deleted here.
  3. Push every results version's links, so `persistent_*_id` on the
     `election_*` documents names the new id.

Then publish, because the persistent payload on R2 carries these ids too::

    python manage.py publish_election_snapshots

Once you have confirmed the dashboard still resolves candidates to people,
clear the documents nothing refers to any more::

    python manage.py prune_persistent_documents --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from wts_app.firebase import push
from wts_app.models.elections import (
    ElectionResultVersion,
    PersistentCandidate,
    PersistentParty,
    PersistentVotingPlace,
)
from wts_app.models.electorates import Electorate

# Electorates are absent on purpose: they have no `firebase_id` column to
# re-key. They are still reported and still pushed -- see handle().
MODELS = {
    'parties': PersistentParty,
    'candidates': PersistentCandidate,
    'voting-places': PersistentVotingPlace,
}


class Command(BaseCommand):
    help = "Set every persistent entity's firebase_id to its Django UUID."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change. Writes nothing.')
        parser.add_argument('--no-push', action='store_true',
                            help='Update this database only; push nothing to Firestore.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        total = 0
        for label, model in sorted(MODELS.items()):
            rows = [row for row in model.objects.all() if row.firebase_id != str(row.id)]
            total += len(rows)
            self.stdout.write(f'{label}: {len(rows)} of {model.objects.count()} '
                              f'to re-key')
            for row in rows[:3]:
                self.stdout.write(f'    {row.firebase_id or "(none)"} -> {row.id}')
            if len(rows) > 3:
                self.stdout.write(f'    ... and {len(rows) - 3} more')

            if not dry_run and rows:
                with transaction.atomic():
                    for row in rows:
                        model.objects.filter(id=row.id).update(firebase_id=str(row.id))

        # Reported even though nothing here changes, because a silent omission
        # in the report someone reads to decide whether to proceed looks exactly
        # like electorates having been forgotten.
        self.stdout.write(
            f'electorates: {Electorate.objects.count()} to move from legacy_id '
            f'to UUID in Firestore (nothing to re-key in this database)')

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'\nDry run. {total} row(s) would be re-keyed here, every persistent '
                'collection would be rewritten at its UUID, and nothing was written '
                'to Firestore.'))
            return

        self.stdout.write(self.style.SUCCESS(f'\nRe-keyed {total} row(s).'))

        if options['no_push']:
            self.stdout.write(self.style.WARNING(
                'Nothing pushed. Firestore still refers to the old ids; run this '
                'again without --no-push, or push by hand.'))
            return

        try:
            written = push.push_all_persistent()
        except push.FirebasePushDisabled as exc:
            raise CommandError(str(exc))

        for collection, count in sorted(written.items()):
            self.stdout.write(f'  {collection}: wrote {count} document(s)')

        versions = ElectionResultVersion.objects.select_related('election').exclude(
            firebase_id__isnull=True).exclude(firebase_id='')
        for version in versions:
            links = push.push_election_links(version)
            self.stdout.write(
                f'  {version.election.slug}/{version.slug}: '
                + ', '.join(f'{name} {count}' for name, count in sorted(links.items())))

        self.stdout.write(self.style.SUCCESS(
            '\nDone. Now run publish_election_snapshots, then check the dashboard '
            'resolves candidates to people before pruning the old documents.'))
