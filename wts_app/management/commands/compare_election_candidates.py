"""Export two elections' candidates side by side, paired by persistent candidate.

A persistent candidate is what lets the site follow one person from election to
election. Checking those links by eye is easiest with both fields of candidates
in one table: each row is one persistent candidate, with what they were in the
left election next to what they were in the right one. A wrong link shows up as
two different people on one row; a missed link as the same person on two rows,
one half empty.

Rows come in three groups, in this order:

* linked, and standing in both elections;
* linked, but standing in only one of them;
* not linked to a persistent candidate at all.

Usage::

    python manage.py compare_election_candidates \\
        --left 2023-general-election --right 2026-general-election \\
        --output candidates-2023-2026.csv

Each election uses its primary results version unless ``--left-version`` or
``--right-version`` names another. Without ``--output`` the CSV goes to stdout.
"""

import csv
import sys
from collections import defaultdict
from itertools import zip_longest

from django.core.management.base import BaseCommand, CommandError

from wts_app.models.elections import ElectionCandidate, ElectionResultVersion

BOTH = 'both'
LEFT_ONLY = 'left only'
RIGHT_ONLY = 'right only'
UNLINKED = 'unlinked'


class Command(BaseCommand):
    help = ('Export a CSV of two elections\' candidates side by side, paired by '
            'persistent candidate, for checking the links by eye.')

    def add_arguments(self, parser):
        parser.add_argument('--left', required=True,
                            help='Slug of the election for the left-hand columns.')
        parser.add_argument('--right', required=True,
                            help='Slug of the election for the right-hand columns.')
        parser.add_argument('--left-version',
                            help='Results version of the left election. '
                                 'Defaults to its primary version.')
        parser.add_argument('--right-version',
                            help='Results version of the right election. '
                                 'Defaults to its primary version.')
        parser.add_argument('--output', '-o',
                            help='File to write. Defaults to stdout.')

    def handle(self, *args, **options):
        left = self.select_version(options['left'], options['left_version'], '--left')
        right = self.select_version(options['right'], options['right_version'], '--right')
        if left.pk == right.pk:
            raise CommandError('--left and --right are the same results version.')

        left_label, right_label = self.labels(left, right)
        rows = self.pair(self.candidates(left), self.candidates(right))

        header = ['PERSISTENT CANDIDATE', 'PERSISTENT ID', 'STATUS']
        for label in (left_label, right_label):
            header += [f'{label} CANDIDATE', f'{label} ELECTORATE',
                       f'{label} PARTY', f'{label} LIST POSITION']

        if options['output']:
            with open(options['output'], 'w', newline='', encoding='utf-8') as handle:
                self.write(handle, header, rows)
        else:
            self.write(sys.stdout, header, rows)

        counts = defaultdict(int)
        for row in rows:
            counts[row[2]] += 1
        summary = ', '.join(f'{counts[kind]} {kind}'
                            for kind in (BOTH, LEFT_ONLY, RIGHT_ONLY, UNLINKED))
        # Report on stderr so the summary never ends up inside a piped CSV.
        self.stderr.write(
            f'{left.election.slug} / {left.slug}  vs  '
            f'{right.election.slug} / {right.slug}: {len(rows)} rows ({summary})')
        if options['output']:
            self.stderr.write(self.style.SUCCESS(f'Wrote {options["output"]}'))

    # -- selection -------------------------------------------------------

    def select_version(self, election_slug, version_slug, flag):
        versions = (ElectionResultVersion.objects
                    .select_related('election')
                    .filter(election__slug=election_slug))
        if not versions.exists():
            raise CommandError(f'{flag}: no election has the slug {election_slug!r}, '
                               f'or it has no results versions.')

        if version_slug:
            versions = versions.filter(slug=version_slug)
            if not versions.exists():
                raise CommandError(f'{flag}: {election_slug} has no results version '
                                   f'with the slug {version_slug!r}.')
        else:
            found = list(versions)
            if len(found) == 1:
                return found[0]
            versions = versions.filter(is_primary=True)
            if not versions.exists():
                listed = '\n'.join(f'    {v.slug}' for v in found)
                raise CommandError(
                    f'{flag}: {election_slug} has {len(found)} results versions and '
                    f'none is primary. Choose one with {flag}-version:\n{listed}')

        return versions.first()

    def labels(self, left, right):
        """Column prefixes: the polling year where that tells them apart, as in
        "2023 CANDIDATE", otherwise the election slug."""
        left_year = str(left.election.polling_date.year)
        right_year = str(right.election.polling_date.year)
        if left_year != right_year:
            return left_year, right_year
        return left.election.slug.upper(), right.election.slug.upper()

    # -- pairing ---------------------------------------------------------

    def candidates(self, version):
        return list(ElectionCandidate.objects
                    .filter(results_version=version)
                    .select_related('persistent_candidate', 'electorate', 'party')
                    .order_by('name', 'number'))

    def pair(self, left, right):
        left_linked, left_unlinked = self.group(left)
        right_linked, right_unlinked = self.group(right)

        persistent = {}
        for candidate in left + right:
            if candidate.persistent_candidate_id:
                persistent[candidate.persistent_candidate_id] = candidate.persistent_candidate

        both, one_side = [], []
        for pk, record in sorted(persistent.items(),
                                 key=lambda item: item[1].display_name.lower()):
            lefts, rights = left_linked.get(pk, []), right_linked.get(pk, [])
            status = BOTH if lefts and rights else LEFT_ONLY if lefts else RIGHT_ONLY
            target = both if status == BOTH else one_side
            # One person should stand once per election; if a persistent record
            # is shared by two candidates in one election, each gets a row so
            # the duplicate is visible.
            for l, r in zip_longest(lefts, rights):
                target.append([record.display_name, pk, status,
                               *self.cells(l), *self.cells(r)])

        unlinked = (
            [['', '', UNLINKED, *self.cells(c), *self.cells(None)] for c in left_unlinked]
            + [['', '', UNLINKED, *self.cells(None), *self.cells(c)] for c in right_unlinked]
        )
        return both + one_side + unlinked

    def group(self, candidates):
        linked, unlinked = defaultdict(list), []
        for candidate in candidates:
            if candidate.persistent_candidate_id:
                linked[candidate.persistent_candidate_id].append(candidate)
            else:
                unlinked.append(candidate)
        return linked, unlinked

    def cells(self, candidate):
        if candidate is None:
            return ['', '', '', '']
        party = candidate.party
        return [
            candidate.name,
            candidate.electorate.name if candidate.electorate else '',
            (party.name or party.abbreviation or '') if party else '',
            candidate.list_pos or '',
        ]

    def write(self, handle, header, rows):
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
