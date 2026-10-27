"""Push election voting places to their Algolia index.

Voting places arrive by bulk_create, which sends no post_save signal, so the
index does not follow an import on its own. Run this after one.

    # One version, by election and version slug.
    python manage.py sync_voting_places --election-slug 2023-general --version-slug final

    # Every version with voting places, one sync each.
    python manage.py sync_voting_places --all

    # Rebuild the index from scratch, through a temporary index that is moved
    # into place atomically. Use this after changing the index definition.
    python manage.py sync_voting_places --reindex

Nothing here is specific to an election night: the index is reference data, not
results, and a sync is safe to run at any point in a count.
"""

from django.core.management.base import BaseCommand, CommandError

from wts_app.models.elections import ElectionResultVersion, ElectionVotingPlace
from wts_app.tasks.voting_places import sync_voting_places


class Command(BaseCommand):
    help = 'Sync election voting places to their Algolia index.'

    def add_arguments(self, parser):
        parser.add_argument('--election-slug', help='Only versions of this election.')
        parser.add_argument('--version-slug', help='Only versions with this slug.')
        parser.add_argument(
            '--all',
            action='store_true',
            help='Every results version that has voting places.',
        )
        parser.add_argument(
            '--reindex',
            action='store_true',
            help='Rebuild the whole index in one pass instead of syncing version '
                 'by version. Removes records for versions that no longer exist.',
        )
        parser.add_argument(
            '--queue',
            action='store_true',
            help='Hand the work to Celery and return, rather than doing it here.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be synced. Touches neither Algolia nor the queue.',
        )

    def handle(self, *args, **options):
        if options['reindex']:
            if options['election_slug'] or options['version_slug'] or options['all']:
                raise CommandError(
                    '--reindex rebuilds the index from every voting place, so it '
                    'cannot be narrowed to an election or a version.')
            self.run_one(None, 'every version', options)
            return

        versions = self.select_versions(options)
        if not versions:
            raise CommandError(
                'No results version matched. Pass --all, or name one with '
                '--election-slug and --version-slug.')

        for version in versions:
            label = f'{version.election.slug}/{version.slug}'
            self.run_one(version.id, label, options)

    def select_versions(self, options):
        versions = ElectionResultVersion.objects.select_related('election')

        if options['election_slug']:
            versions = versions.filter(election__slug=options['election_slug'])
        if options['version_slug']:
            versions = versions.filter(slug=options['version_slug'])

        if not (options['election_slug'] or options['version_slug']):
            if not options['all']:
                return []
            # Without a narrowing flag, skip the versions that would each cost a
            # browse and a no-op batch to tell us they have nothing.
            versions = versions.filter(electionvotingplace__isnull=False).distinct()

        return list(versions.order_by('election__polling_date', 'slug'))

    def run_one(self, results_version_id, label, options):
        if options['dry_run']:
            places = ElectionVotingPlace.objects.all()
            if results_version_id is not None:
                places = places.filter(results_version_id=results_version_id)
            self.stdout.write(
                f'{label}: would sync {places.count()} voting place(s). '
                'Records the index holds and this database does not would be '
                'removed; this run does not read Algolia to count them.')
            return

        if options['queue']:
            task = sync_voting_places.delay(
                results_version_id=(str(results_version_id)
                                    if results_version_id is not None else None))
            self.stdout.write(f'{label}: queued as {task.id}')
            return

        result = sync_voting_places(
            results_version_id=(str(results_version_id)
                                if results_version_id is not None else None))
        self.stdout.write(self.style.SUCCESS(
            f'{label}: indexed {result["indexed"]}, removed {result["deleted"]}'))
