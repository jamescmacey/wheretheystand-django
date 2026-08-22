"""Import results from Firestore into Django, and publish what was imported.

This is no longer a loop, and nothing about a live count depends on it. Clients
read tallies from Firestore themselves and reference data from wherever the
event document points them, so an evening where this never runs still shows a
working dashboard.

Run it twice, deliberately:

    # Once, after the worker sets refdata_built. Puts reference data on R2 and
    # sets refdata_url, taking several hundred document reads per visitor off
    # the Firestore bill.
    python manage.py sync_live_elections

    # Again immediately BEFORE turning is_live off, so the published snapshot
    # is current at the moment it becomes what open pages fall back to.
    python manage.py sync_live_elections

Then afterwards, to catch the final count once the switch is off::

    python manage.py sync_live_elections --include-not-live --version-slug final

Check what it would do first, which reads Firestore but writes nothing::

    python manage.py sync_live_elections --dry-run
"""

from django.core.management.base import BaseCommand, CommandError

from wts_app.firebase import ingest
from wts_app.models.elections import ElectionResultVersion


class Command(BaseCommand):
    help = ('Import election results from Firestore and publish them to R2. '
            'Run once when reference data is built, and again before ending '
            'a count.')

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
            '--dry-run',
            action='store_true',
            help='Report what each version would do. Reads Firestore; writes nothing.',
        )

    def handle(self, *args, **options):
        # Exits non-zero on any failure, so a wrapper script or an operator
        # watching the output can tell a partial run from a clean one.
        failures = self.run_once(options)
        if failures:
            raise CommandError(f'{failures} version(s) failed. See output above.')

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
                if result.get('refdata_url'):
                    self.stdout.write(
                        f'  refdata_url -> {result["refdata_url"]}')
                elif result['reference_imported']:
                    self.stdout.write(self.style.WARNING(
                        '  refdata_url NOT set; clients will read reference '
                        'data from Firestore instead'))

            except Exception as exc:
                # One misbehaving event must not stop the others.
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
                '  would import reference data, publish it, and set refdata_url'))
        self.stdout.write('  would import results, publish them, '
                          'and rewrite the manifest')
