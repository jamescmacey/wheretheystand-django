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
            help='Also publish voting place reference data, per-electorate '
                 'results and one file per voting place. Several thousand '
                 'objects; slow.',
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

        if options['voting_places']:
            self._report_colliding_sets(versions)

        published = publisher.publish_all(
            writer,
            versions=versions,
            include_voting_places=options['voting_places'],
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

    def _report_colliding_sets(self, versions):
        """Warn about voting place sets the client would silently drop.

        Two sets for the same place, electorate and category are identified
        only by the last component of the canonical key. Where that matches as
        well, the client holds one entry for both and keeps whichever carries
        the later timestamp: the place reads low by the dropped set, with
        nothing on screen to say so. Worth knowing before an event rather than
        inferring it afterwards from a total that looks slightly off.
        """
        for version in versions:
            collisions = builders.find_colliding_voting_place_sets(version)
            if not collisions:
                continue

            self.stdout.write(self.style.WARNING(
                f'  {version.election.slug}/{version.slug}: '
                f'{len(collisions)} voting place key collision(s). '
                f'Each drops a tally in the client.'))
            for key, sets in sorted(collisions.items())[:10]:
                self.stdout.write(f'    {key} - {len(sets)} sets')
