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

    # ...or for every candidate still without one, including any you skipped
    python manage.py match_persistent_entities --election-slug ... --only candidates \
        --create-missing --include-review

To judge a suggested candidate against how they stood last time, name the
previous election (and its version, if it has more than one)::

    python manage.py match_persistent_entities --election-slug 2026-general-election \
        --interactive --previous-election-slug 2023-general-election \
        --previous-version-slug official

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
            '--include-review', action='store_true',
            help='With --create-missing, also create records for rows in the '
                 'review queue -- every row --apply would not link. Run '
                 '--interactive first, or this will duplicate people.',
        )
        parser.add_argument(
            '--previous-election-slug',
            help='An earlier election. Suggestions then show how that record '
                 'stood in it (party, electorate, list position).',
        )
        parser.add_argument(
            '--previous-version-slug',
            help='Results version of --previous-election-slug. Needed only '
                 'when it has more than one and none is primary.',
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

        if options['include_review'] and not options['create_missing']:
            raise CommandError('--include-review only makes sense with --create-missing.')
        if options['previous_version_slug'] and not options['previous_election_slug']:
            raise CommandError('--previous-version-slug needs --previous-election-slug.')

        version = self.select_version(options)
        self.previous_version = self.select_previous_version(options, version)
        matchers = self.select_matchers(options, version)

        self.stdout.write(
            f'{version.election.slug} / {version.slug}  ({version.firebase_id or "no event id"})')
        if self.previous_version:
            self.stdout.write(
                f'  compared with {self.previous_version.election.slug} / '
                f'{self.previous_version.slug}')
        self.stdout.write('')

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
                self.create_missing(matcher, outcomes, options['include_review'])

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

    def select_previous_version(self, options, version):
        slug = options['previous_election_slug']
        if not slug:
            return None

        versions = ElectionResultVersion.objects.select_related('election').filter(
            election__slug=slug)
        if options['previous_version_slug']:
            versions = versions.filter(slug=options['previous_version_slug'])

        found = list(versions)
        if len(found) > 1:
            primary = [v for v in found if v.is_primary]
            if len(primary) == 1:
                found = primary
        if not found:
            raise CommandError(f'No results version matched for {slug}.')
        if len(found) > 1:
            listed = '\n'.join(f'    {v.slug}' for v in found)
            raise CommandError(
                f'{len(found)} results versions matched for {slug}. Narrow with '
                f'--previous-version-slug:\n{listed}')
        if found[0].pk == version.pk:
            raise CommandError('The previous version is the one being matched.')
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
                              threshold_metres=options['distance_metres'],
                              previous_version=self.previous_version)
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
            options = suggestion.options
            for number, persistent in enumerate(options, start=1):
                marker = f'[{number}] ' if len(options) > 1 else ''
                detail = (f'   {score}({suggestion.detail})'
                          if number == 1 and (score or suggestion.detail) else '')
                self.stdout.write(
                    f'      {marker}{matcher.describe_persistent(persistent)}{detail}')
                self.print_history(matcher, persistent)
        for note in outcome.notes:
            self.stdout.write(self.style.WARNING(f'      {note}'))
        self.stdout.write('')

    def print_history(self, matcher, persistent):
        history = matcher.history(persistent)
        if history is None:
            return
        label = self.previous_version.election.slug
        if not history:
            self.stdout.write(f'          {label}: not standing')
        for line in history:
            self.stdout.write(f'          {label}: {line}')

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

    def create_missing(self, matcher, outcomes, include_review=False):
        kinds = (CREATE, REVIEW) if include_review else (CREATE,)
        missing = [o for o in outcomes if o.kind in kinds]
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
        self.stdout.write('  [l2] link to suggestion 2, where several are listed')
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

                if choice.startswith('l'):
                    if not outcome.suggestion:
                        self.stdout.write(self.style.WARNING('      no suggestion to link to'))
                        continue
                    options = outcome.suggestion.options
                    picked = choice[1:].strip() or '1'
                    if not picked.isdigit() or not 1 <= int(picked) <= len(options):
                        self.stdout.write(self.style.WARNING(
                            f'      choose l1 to l{len(options)}'))
                        continue
                    matcher.link(outcome.entity, options[int(picked) - 1])
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
