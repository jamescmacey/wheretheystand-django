"""Match an election's candidates, parties, electorates and voting places to
the persistent records that outlive them.

Persistent records are what let the site follow the same person or party across
elections. The Electoral Commission does not supply them, and the results worker
only matches what it can recognise, so the rest is curated here.

Nothing changes unless you ask. The usual sequence::

    # 1. Look
    python manage.py match_persistent_entities --election-slug 2023-general-election

    # 2. Link what is unambiguous
    python manage.py match_persistent_entities --election-slug ... --apply

    # 3. Decide the handful that are not
    python manage.py match_persistent_entities --election-slug ... --interactive

    # 4. Create records for everyone genuinely new
    python manage.py match_persistent_entities --election-slug ... --create-missing

Afterwards the persistent and reference payloads have changed, so republish::

    python manage.py push_persistent_to_firebase
    python manage.py publish_election_snapshots --election-slug ...
"""

import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from wts_app.matching import geo
from wts_app.matching.matchers import CREATE, EXACT, MATCHERS, REVIEW, STRUCTURAL
from wts_app.models.elections import ElectionResultVersion


class Command(BaseCommand):
    help = ('Match election entities to persistent records, and create the '
            'persistent records that do not exist yet.')

    def add_arguments(self, parser):
        parser.add_argument('--election-slug', help='Election to work on.')
        parser.add_argument('--version-slug', help='Results version to work on.')
        parser.add_argument(
            '--only',
            help='Comma separated subset of: ' + ', '.join(sorted(MATCHERS)),
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Link unambiguous matches. Never touches the review queue.',
        )
        parser.add_argument(
            '--create-missing', action='store_true',
            help='Create persistent records for rows with no plausible match.',
        )
        parser.add_argument(
            '--interactive', action='store_true',
            help='Work through the review queue one row at a time.',
        )
        parser.add_argument(
            '--review', action='store_true',
            help='Print only the review queue.',
        )
        parser.add_argument(
            '--min-score', type=float, default=0.80,
            help='How similar a name must be to reach the review queue. Moves '
                 'only the boundary between "needs a decision" and "no match"; '
                 'it can neither cause nor prevent a link. Default 0.80.',
        )
        parser.add_argument(
            '--distance-metres', type=int, default=geo.DEFAULT_THRESHOLD_METRES,
            help=f'How close a voting place must be to count as the same place. '
                 f'Default {geo.DEFAULT_THRESHOLD_METRES}, matching the results worker.',
        )

    def handle(self, *args, **options):
        if options['interactive'] and not sys.stdin.isatty():
            raise CommandError(
                '--interactive needs a terminal. Drop it to get a report instead.')

        version = self.select_version(options)
        matchers = self.select_matchers(options, version)

        self.stdout.write(
            f'{version.election.slug} / {version.slug}  ({version.firebase_id or "no event id"})\n')

        for matcher in matchers:
            outcomes = [matcher.classify(entity) for entity in matcher.unmatched()]
            matched = matcher.all_entities().count() - len(outcomes)

            if options['review'] or options['interactive']:
                queue = [o for o in outcomes if o.kind == REVIEW]
                if options['interactive']:
                    self.work_queue(matcher, queue)
                else:
                    self.print_queue(matcher, queue)
                continue

            self.report(matcher, outcomes, matched)

            if options['apply']:
                self.apply_links(matcher, outcomes)
            if options['create_missing']:
                self.create_missing(matcher, outcomes)

        if not any((options['apply'], options['create_missing'],
                    options['interactive'], options['review'])):
            self.stdout.write(self.style.WARNING(
                '\nNothing was changed. Re-run with --apply, then --interactive, '
                'then --create-missing.'))

    # -- selection -------------------------------------------------------

    def select_version(self, options):
        versions = ElectionResultVersion.objects.select_related('election')
        if options['election_slug']:
            versions = versions.filter(election__slug=options['election_slug'])
        if options['version_slug']:
            versions = versions.filter(slug=options['version_slug'])

        found = list(versions)
        if not found:
            raise CommandError('No results version matched.')
        if len(found) > 1:
            listed = '\n'.join(f'    {v.election.slug} / {v.slug}' for v in found)
            raise CommandError(
                f'{len(found)} results versions matched. Narrow with '
                f'--election-slug or --version-slug:\n{listed}')
        return found[0]

    def select_matchers(self, options, version):
        keys = sorted(MATCHERS)
        if options['only']:
            keys = [k.strip() for k in options['only'].split(',') if k.strip()]
            unknown = [k for k in keys if k not in MATCHERS]
            if unknown:
                raise CommandError(
                    f'Unknown type(s): {", ".join(unknown)}. '
                    f'Choose from: {", ".join(sorted(MATCHERS))}')

        return [MATCHERS[key](version,
                              min_score=options['min_score'],
                              threshold_metres=options['distance_metres'])
                for key in keys]

    # -- reporting -------------------------------------------------------

    def report(self, matcher, outcomes, matched):
        counts = {kind: [o for o in outcomes if o.kind == kind]
                  for kind in (EXACT, STRUCTURAL, REVIEW, CREATE)}
        total = matched + len(outcomes)

        self.stdout.write(f'\n{matcher.label}  {total} total')
        self.stdout.write(f'  {matched:>6}  already matched')

        if counts[EXACT]:
            self.stdout.write(self.style.SUCCESS(
                f'  {len(counts[EXACT]):>6}  exact match            --apply would link'))
        if counts[STRUCTURAL]:
            self.stdout.write(self.style.SUCCESS(
                f'  {len(counts[STRUCTURAL]):>6}  differs by middle names  --apply would link'))
            for outcome in counts[STRUCTURAL][:5]:
                self.stdout.write(
                    f'            {matcher.describe(outcome.entity)}'
                    f'  ->  {matcher.describe_persistent(outcome.suggestion.persistent)}')
        if counts[REVIEW]:
            self.stdout.write(self.style.WARNING(
                f'  {len(counts[REVIEW]):>6}  needs a decision       never linked automatically'))
        if counts[CREATE]:
            verb = ('--create-missing would create these' if matcher.can_create
                    else 'must be created in the admin')
            self.stdout.write(f'  {len(counts[CREATE]):>6}  no plausible match     {verb}')

    def print_queue(self, matcher, queue):
        if not queue:
            self.stdout.write(f'\n{matcher.label}: nothing needs a decision.')
            return

        self.stdout.write(f'\n{matcher.label}: {len(queue)} need a decision\n')
        for outcome in queue:
            self.print_row(matcher, outcome)

    def print_row(self, matcher, outcome):
        context = matcher.context(outcome.entity)
        self.stdout.write(f'  {matcher.describe(outcome.entity)}'
                          + (f'   {context}' if context else ''))
        if outcome.suggestion:
            suggestion = outcome.suggestion
            score = f'{suggestion.score:.3f}  ' if suggestion.score else ''
            self.stdout.write(
                f'      {score}{matcher.describe_persistent(suggestion.persistent)}'
                f'   ({suggestion.detail})')
        for note in outcome.notes:
            self.stdout.write(self.style.WARNING(f'      {note}'))
        self.stdout.write('')

    # -- changes ---------------------------------------------------------

    def apply_links(self, matcher, outcomes):
        linkable = [o for o in outcomes if o.links_automatically]
        if not linkable:
            return

        with transaction.atomic():
            for outcome in linkable:
                matcher.link(outcome.entity, outcome.suggestion.persistent)

        self.stdout.write(self.style.SUCCESS(
            f'          linked {len(linkable)} {matcher.label}'))

    def create_missing(self, matcher, outcomes):
        missing = [o for o in outcomes if o.kind == CREATE]
        if not missing:
            return

        if not matcher.can_create:
            self.stdout.write(self.style.WARNING(
                f'          {len(missing)} {matcher.label} need persistent records, '
                f'but these must be created in the admin'))
            return

        with transaction.atomic():
            for outcome in missing:
                persistent = matcher.create_persistent(outcome.entity)
                matcher.link(outcome.entity, persistent)

        self.stdout.write(self.style.SUCCESS(
            f'          created and linked {len(missing)} {matcher.label}'))

    # -- interactive -----------------------------------------------------

    def work_queue(self, matcher, queue):
        if not queue:
            self.stdout.write(f'\n{matcher.label}: nothing needs a decision.')
            return

        self.stdout.write(f'\n{matcher.label}: {len(queue)} need a decision')
        self.stdout.write('  [l] link to the suggestion   [c] create a new record')
        self.stdout.write('  [s] skip                     [o] show the admin link')
        self.stdout.write('  [q] stop here\n')

        linked = created = skipped = 0

        for position, outcome in enumerate(queue, start=1):
            self.stdout.write(f'{position} of {len(queue)}')
            self.print_row(matcher, outcome)

            while True:
                choice = input('  [l/c/s/o/q] ').strip().lower()

                if choice == 'o':
                    meta = outcome.entity._meta
                    self.stdout.write(
                        f'      /admin/{meta.app_label}/{meta.model_name}/'
                        f'{outcome.entity.pk}/change/\n')
                    continue

                if choice == 'l':
                    if not outcome.suggestion:
                        self.stdout.write(self.style.WARNING('      no suggestion to link to'))
                        continue
                    matcher.link(outcome.entity, outcome.suggestion.persistent)
                    linked += 1
                    self.stdout.write(self.style.SUCCESS('      linked\n'))
                    break

                if choice == 'c':
                    if not matcher.can_create:
                        self.stdout.write(self.style.WARNING(
                            f'      {matcher.label} must be created in the admin'))
                        continue
                    persistent = matcher.create_persistent(outcome.entity)
                    matcher.link(outcome.entity, persistent)
                    created += 1
                    self.stdout.write(self.style.SUCCESS('      created and linked\n'))
                    break

                if choice == 's':
                    skipped += 1
                    self.stdout.write('      skipped\n')
                    break

                if choice == 'q':
                    self.summarise(matcher, linked, created,
                                   skipped + len(queue) - position + 1)
                    return

        self.summarise(matcher, linked, created, skipped)

    def summarise(self, matcher, linked, created, remaining):
        self.stdout.write(self.style.SUCCESS(
            f'  {matcher.label}: {linked} linked, {created} created, '
            f'{remaining} left'))
