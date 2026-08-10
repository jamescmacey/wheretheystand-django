"""Push a results version's events document to Firestore.

The events document is what tells the results worker and the client what this
event is: its name, dates, embargo, coalition ordering and incumbents. Getting
it wrong on the night is expensive, so inspect the payload first::

    python manage.py push_event_to_firebase --version-slug election-night --dry-run
"""

import json

from django.core.management.base import BaseCommand, CommandError

from wts_app.firebase import push
from wts_app.models.elections import ElectionResultVersion


class Command(BaseCommand):
    help = "Push a results version's events document to Firestore."

    def add_arguments(self, parser):
        parser.add_argument('--version-slug', help='Results version slug to push.')
        parser.add_argument('--election-slug', help='Narrow to one election.')
        parser.add_argument('--all-live', action='store_true',
                            help='Push every version marked live.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Print the payload without writing to Firestore.')

    def handle(self, *args, **options):
        versions = ElectionResultVersion.objects.select_related('election')
        if options['election_slug']:
            versions = versions.filter(election__slug=options['election_slug'])
        if options['version_slug']:
            versions = versions.filter(slug=options['version_slug'])
        if options['all_live']:
            versions = versions.filter(is_live=True)

        versions = list(versions)
        if not versions:
            raise CommandError('No results versions matched.')
        if len(versions) > 1 and not (options['all_live'] or options['election_slug']):
            raise CommandError(
                f'{len(versions)} versions matched. Narrow with --version-slug or '
                '--election-slug, or use --all-live.')

        for version in versions:
            document_id = push.event_document_id(version)
            self.stdout.write(
                f'{version.election.slug}/{version.slug} -> events/{document_id}')

            if options['dry_run']:
                payload = push.build_event_document(version)
                self.stdout.write(json.dumps(payload, indent=2, default=str))
                continue

            try:
                push.push_event(version.id)
            except push.FirebasePushDisabled as exc:
                raise CommandError(str(exc))
            self.stdout.write(self.style.SUCCESS('  pushed'))

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('\nDry run. Nothing was written.'))
