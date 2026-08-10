"""Import live results from Firestore and republish the snapshots clients read.

During an event the results worker writes to Firestore and clients read tallies
from there directly. Everything else they read -- the names those tallies refer
to, and the server-rendered first paint -- comes from snapshots generated here.
This command closes that loop.

It does the same work as the ``refresh_live_snapshots`` Celery task, so an event
can be run without a broker. Any one of these is enough:

    # Once, from cron every two minutes
    */2 * * * * python manage.py sync_live_elections

    # Or in a terminal for the evening, cycling on its own
    python manage.py sync_live_elections --interval 120

    # Or via Celery beat, scheduling wts_app.firebase.refresh_live_snapshots

Check what it would do first, which reads Firestore but writes nothing::

    python manage.py sync_live_elections --dry-run
"""

import time

from django.core.management.base import BaseCommand, CommandError

from wts_app.firebase import ingest
from wts_app.models.elections import ElectionResultVersion


class Command(BaseCommand):
    help = ('Import live election results from Firestore and republish the '
            'R2 snapshots.')

    def add_arguments(self, parser):
        parser.add_argument('--version-slug', help='Only this results version.')
        parser.add_argument('--election-slug', help='Only this election.')
        parser.add_argument(
            '--include-not-live',
            action='store_true',
            help='Also process versions not marked live. Useful for catching up '
                 'after an event, once is_live has been turned off.',
        )
        parser.add_argument(
            '--no-publish',
            action='store_true',
            help='Import from Firestore but do not republish snapshots.',
        )
        parser.add_argument(
            '--interval',
            type=int,
            help='Repeat every N seconds instead of running once. Ctrl-C to stop.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what each version would do. Reads Firestore; writes nothing.',
        )

    def handle(self, *args, **options):
        interval = options['interval']
        if interval is not None and interval < 30:
            # The worker polls the Electoral Commission every ten seconds or so,
            # but each cycle here re-imports every results document. Running it
            # faster than it completes just stacks up work.
            raise CommandError('--interval must be at least 30 seconds.')

        if interval is None:
            failures = self.run_once(options)
            if failures:
                raise CommandError(f'{failures} version(s) failed. See output above.')
            return

        self.stdout.write(f'Cycling every {interval}s. Press Ctrl-C to stop.')
        try:
            while True:
                self.run_once(options)
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write('\nStopped.')

    def select_versions(self, options):
        versions = ElectionResultVersion.objects.select_related('election')

        if options['include_not_live']:
            versions = versions.exclude(firebase_id__isnull=True)
        else:
            versions = ingest.live_versions()

        if options['election_slug']:
            versions = versions.filter(election__slug=options['election_slug'])
        if options['version_slug']:
            versions = versions.filter(slug=options['version_slug'])

        return list(versions)

    def run_once(self, options):
        versions = self.select_versions(options)

        if not versions:
            self.stdout.write(self.style.WARNING(
                'No live results versions. Set is_live on one, or pass '
                '--include-not-live to process an event that has finished.'))
            return 0

        failures = 0
        for version in versions:
            label = f'{version.election.slug}/{version.slug} ({version.firebase_id})'
            try:
                if options['dry_run']:
                    self.report(version, label)
                    continue

                if options['no_publish']:
                    ingest.sync_event_metadata(version)
                    if version.refdata_built and not ingest.has_reference_data(version):
                        ingest.sync_reference_data(version)
                    ingest.sync_results(version)
                    self.stdout.write(self.style.SUCCESS(f'{label}: imported'))
                    continue

                result = ingest.sync_live_version(version)
                detail = 'imported reference data, ' if result['reference_imported'] else ''
                self.stdout.write(self.style.SUCCESS(
                    f'{label}: {detail}results imported, '
                    f'{result.get("objects", 0)} snapshot object(s) published'))

            except Exception as exc:
                # One misbehaving event must not stop the others. On the night
                # this command may be the only thing keeping snapshots current.
                failures += 1
                self.stderr.write(self.style.ERROR(f'{label}: {type(exc).__name__}: {exc}'))

        return failures

    def report(self, version, label):
        """Say what a cycle would do, without changing anything."""
        try:
            # Read the event document rather than the local copy: that is only
            # as current as the last sync, so reporting from it would describe
            # the wrong decision.
            metadata = ingest.read_event_metadata(version)
            count = ingest.firestore_results_count(version)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(
                f'{label}: could not reach Firestore: {type(exc).__name__}: {exc}'))
            return

        if not metadata:
            self.stderr.write(self.style.ERROR(
                f'{label}: no events document in Firestore. Push one with '
                'push_event_to_firebase before the event.'))
            return

        has_reference = ingest.has_reference_data(version)
        self.stdout.write(f'{label}')
        self.stdout.write(f'  Firestore results documents: {count}')
        self.stdout.write('  ' + ', '.join(f'{k}={v}' for k, v in metadata.items())
                          + '  (from Firestore)')
        self.stdout.write(f'  reference data already in this database: {has_reference}')

        if not metadata['refdata_built']:
            self.stdout.write(self.style.WARNING(
                '  would NOT import reference data: the worker has not built it yet'))
        elif not has_reference:
            self.stdout.write(self.style.SUCCESS(
                '  would import reference data, then republish reference and persistent'))
        self.stdout.write('  would import results and republish results-latest.json')
