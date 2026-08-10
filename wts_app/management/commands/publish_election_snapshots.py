"""Publish election results snapshots to R2, or to a local directory.

Examples::

    # Everything, to R2
    python manage.py publish_election_snapshots

    # One results version, showing what would be written
    python manage.py publish_election_snapshots --version-slug e9 --dry-run

    # A local tree the Nuxt client can be pointed at during development
    python manage.py publish_election_snapshots --local ./snapshots
"""

from django.core.management.base import BaseCommand, CommandError

from wts_app.snapshots import builders, publisher


class Command(BaseCommand):
    help = 'Publish election results snapshots to R2 or a local directory.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--version-slug',
            help='Publish only this results version slug (all elections).',
        )
        parser.add_argument(
            '--election-slug',
            help='Publish only results versions of this election.',
        )
        parser.add_argument(
            '--local',
            help='Write the snapshot tree to this directory instead of R2.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be written without writing anything.',
        )
        parser.add_argument(
            '--voting-places',
            action='store_true',
            help='Also publish voting place reference data and per-electorate '
                 'results. Several thousand objects; slow.',
        )
        parser.add_argument(
            '--rolling',
            action='store_true',
            help='Publish results to the short-lived results-latest.json used '
                 'during a live event, rather than an immutable file.',
        )

    def handle(self, *args, **options):
        versions = builders.publishable_versions()
        if options['election_slug']:
            versions = versions.filter(election__slug=options['election_slug'])
        if options['version_slug']:
            versions = versions.filter(slug=options['version_slug'])

        versions = list(versions)
        if not versions:
            raise CommandError('No results versions matched.')

        if options['dry_run']:
            writer = publisher.DryRunWriter()
            destination = 'dry run'
        elif options['local']:
            writer = publisher.LocalWriter(options['local'])
            destination = options['local']
        else:
            try:
                writer = publisher.StorageWriter()
            except publisher.PublishDisabled as exc:
                raise CommandError(str(exc))
            destination = 'R2'

        self.stdout.write(
            f'Publishing {len(versions)} results version(s) to {destination}')
        for version in versions:
            self.stdout.write(
                f'  {version.election.slug}/{version.slug} - {version.name}')

        published = publisher.publish_all(
            writer,
            versions=versions,
            include_voting_places=options['voting_places'],
            rolling_results=options['rolling'],
            # A local tree is not what clients read, so do not record its paths
            # as this version's published location.
            record=not options['local'],
        )

        self.stdout.write('')
        if options['dry_run']:
            total = 0
            for path in writer.written:
                size = writer.sizes[path]
                total += size
                self.stdout.write(f'  {size / 1024:9.1f} KB  {path}')
            self.stdout.write(self.style.WARNING(
                f'\nWould write {len(writer.written)} object(s), '
                f'{total / 1024 / 1024:.2f} MB total. Nothing was uploaded.'))
            return

        self.stdout.write(self.style.SUCCESS(
            f'Wrote {len(writer.written)} object(s).'))
        self.stdout.write(f'Manifest: {published["manifest"]}')
