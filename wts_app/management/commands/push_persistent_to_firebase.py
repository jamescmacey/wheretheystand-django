"""Push the persistent entities to Firestore.

These are the records that survive across elections: party colours, and the
links from candidates to people on the site. The results worker cannot supply
them, because they are curated here.

    python manage.py push_persistent_to_firebase --only parties --dry-run
"""

from django.core.management.base import BaseCommand, CommandError

from wts_app.firebase import push

COLLECTIONS = {
    'parties': ('persistent_parties', push.push_persistent_parties),
    'candidates': ('persistent_candidates', push.push_persistent_candidates),
    'electorates': ('persistent_electorates', push.push_persistent_electorates),
    'voting-places': ('persistent_voting_places', push.push_persistent_voting_places),
}


class Command(BaseCommand):
    help = 'Push persistent election entities to Firestore.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--only',
            help='Comma separated subset of: ' + ', '.join(sorted(COLLECTIONS)),
        )
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would be written without writing.')

    def handle(self, *args, **options):
        if options['only']:
            names = [name.strip() for name in options['only'].split(',') if name.strip()]
            unknown = [name for name in names if name not in COLLECTIONS]
            if unknown:
                raise CommandError(
                    f'Unknown collection(s): {", ".join(unknown)}. '
                    f'Choose from: {", ".join(sorted(COLLECTIONS))}')
        else:
            names = sorted(COLLECTIONS)

        for name in names:
            collection, handler = COLLECTIONS[name]
            try:
                count = handler(dry_run=options['dry_run'])
            except push.FirebasePushDisabled as exc:
                raise CommandError(str(exc))
            verb = 'would write' if options['dry_run'] else 'wrote'
            self.stdout.write(f'{collection}: {verb} {count} document(s)')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('\nDry run. Nothing was written.'))
