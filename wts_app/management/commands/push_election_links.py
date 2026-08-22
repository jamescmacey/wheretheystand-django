"""Push curated persistent links back into the worker's reference data.

`match_persistent_entities` decides which cross-election record each candidate,
party, electorate and voting place belongs to. Those decisions live only in this
database until they are pushed, and Firestore's own copy carries whatever the
worker managed to match on its own -- which on the 2023 data was well under half.

That gap is visible. A client reading reference data from Firestore, which is
what every client does until `refdata_url` is set, resolves persistent links
from these fields. Names and tallies are unaffected; what goes missing is the
link through to a candidate's profile on the site.

So after matching, all three of these:

    python manage.py push_persistent_to_firebase
    python manage.py push_election_links --election-slug 2023-general-election
    python manage.py publish_election_snapshots --election-slug 2023-general-election

Always dry run first::

    python manage.py push_election_links --version-slug final --dry-run
"""

from django.core.management.base import BaseCommand, CommandError

from wts_app.firebase import push
from wts_app.models.elections import ElectionResultVersion


class Command(BaseCommand):
    help = ('Push curated persistent links into the election_* collections in '
            'Firestore.')

    def add_arguments(self, parser):
        parser.add_argument('--version-slug', help='Only this results version.')
        parser.add_argument('--election-slug', help='Only this election.')
        parser.add_argument(
            '--only',
            help='Comma separated subset of: ' + ', '.join(sorted(push.LINK_SPECS)),
        )
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would be written without writing.')

    def handle(self, *args, **options):
        only = None
        if options['only']:
            only = [name.strip() for name in options['only'].split(',') if name.strip()]
            unknown = [name for name in only if name not in push.LINK_SPECS]
            if unknown:
                raise CommandError(
                    f'Unknown type(s): {", ".join(unknown)}. '
                    f'Choose from: {", ".join(sorted(push.LINK_SPECS))}')

        versions = ElectionResultVersion.objects.select_related('election').exclude(
            firebase_id__isnull=True).exclude(firebase_id='')
        if options['election_slug']:
            versions = versions.filter(election__slug=options['election_slug'])
        if options['version_slug']:
            versions = versions.filter(slug=options['version_slug'])

        versions = list(versions)
        if not versions:
            raise CommandError(
                'No results versions with a Firestore event id matched. Links '
                'can only be pushed for a version the worker has built.')

        for version in versions:
            label = f'{version.election.slug}/{version.slug} ({version.firebase_id})'
            try:
                written = push.push_election_links(
                    version, only=only, dry_run=options['dry_run'])
            except push.FirebasePushDisabled as exc:
                raise CommandError(str(exc))

            verb = 'would write' if options['dry_run'] else 'wrote'
            self.stdout.write(label)
            for collection, count in sorted(written.items()):
                self.stdout.write(f'  {collection}: {verb} {count} document(s)')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('\nDry run. Nothing was written.'))
