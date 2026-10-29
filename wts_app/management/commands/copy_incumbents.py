"""Copy curated incumbency from one results version to another.

Incumbency is curated by hand: who held each electorate going into the
election, and how many seats each party is defending. A duplicate results
version arrives with none of it, and the answer has not changed -- the same
members held the same seats whichever version of the count you are looking at.
So move it across rather than entering seventy-two rows again.

Much simpler than `copy_persistent_links`, and for one reason: these rows point
only at persistent records, whose ids mean the same thing in both versions.
There is nothing to pair by Electoral Commission `number` and no identity to
verify, so a row either is not in the target yet, is already the same, or
disagrees.

Nothing changes unless you ask::

    # 1. Look
    python manage.py copy_incumbents --from final --to final-revised

    # 2. Copy
    python manage.py copy_incumbents --from final --to final-revised --apply

Both versions must belong to the same election. That is not a technical
limitation -- the ids would resolve perfectly well across elections -- but a
guard against a mistake that looks plausible: the 2026 election's incumbents
are the *winners* of 2023, not 2023's incumbents. Copying the wrong one would
produce a full set of rows that are quietly one election out of date.

Afterwards the version's description has changed, and the manifest carries it,
so a manifest rewrite is all that is needed::

    python manage.py publish_election_snapshots --election-slug <slug>
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from wts_app.management.versions import select_version
from wts_app.models.elections import ElectorateIncumbent, PartyIncumbent

COPY = 'copy'
CONFLICT = 'conflict'
SAME = 'same'


class Pairing:
    """One source row and whatever the target holds for the same key."""

    def __init__(self, source, target, kind):
        self.source = source
        self.target = target
        self.kind = kind


class Copier:
    """Base class. Subclasses name the key and the fields that travel."""

    key = ''
    label = ''
    model = None
    key_field = ''
    fields = ()
    order_by = ()

    def __init__(self, source_version, target_version):
        self.source_version = source_version
        self.target_version = target_version

    # -- rows ------------------------------------------------------------

    def rows(self, version):
        return self.model.objects.filter(
            results_version=version).order_by(*self.order_by)

    def key_for(self, row):
        return getattr(row, self.key_field)

    def values(self, row):
        return {field: getattr(row, field) for field in self.fields}

    # -- pairing ---------------------------------------------------------

    def pairings(self):
        """Classify every source row against the target's row for the same key."""
        by_key = {self.key_for(row): row for row in self.rows(self.target_version)}
        results = []

        for source in self.rows(self.source_version):
            target = by_key.get(self.key_for(source))
            if target is None:
                results.append(Pairing(source, None, COPY))
            elif self.values(target) == self.values(source):
                results.append(Pairing(source, target, SAME))
            else:
                results.append(Pairing(source, target, CONFLICT))

        return results

    # -- changes ---------------------------------------------------------

    def copy(self, pairings):
        """Create the missing rows and update the ones being replaced."""
        created = [
            self.model(results_version=self.target_version,
                       **{self.key_field: self.key_for(pairing.source)},
                       **self.values(pairing.source))
            for pairing in pairings if pairing.target is None
        ]
        updated = []
        for pairing in pairings:
            if pairing.target is None:
                continue
            for field, value in self.values(pairing.source).items():
                setattr(pairing.target, field, value)
            updated.append(pairing.target)

        if created:
            self.model.objects.bulk_create(created, batch_size=500)
        if updated:
            self.model.objects.bulk_update(updated, list(self.fields), batch_size=500)
        return len(created) + len(updated)

    # -- description -----------------------------------------------------

    def describe(self, row):
        raise NotImplementedError

    def describe_values(self, row):
        raise NotImplementedError


class ElectorateIncumbentCopier(Copier):
    key = 'electorates'
    label = 'electorate incumbents'
    model = ElectorateIncumbent
    key_field = 'electorate_id'
    fields = ('persistent_candidate_id', 'persistent_party_id',
              'has_left_party', 'current_persistent_party_id', 'notes')
    order_by = ('electorate__name',)

    def rows(self, version):
        return super().rows(version).select_related(
            'electorate', 'persistent_candidate', 'persistent_party',
            'current_persistent_party')

    def describe(self, row):
        return row.electorate.name

    def describe_values(self, row):
        candidate = (row.persistent_candidate.display_name
                     if row.persistent_candidate else 'vacant')
        party = (row.persistent_party.display_name
                 if row.persistent_party else 'no party')
        if not row.has_left_party:
            return f'{candidate} ({party})'
        now = (row.current_persistent_party.display_name
               if row.current_persistent_party else 'independent')
        return f'{candidate} ({party}, now {now})'


class PartyIncumbentCopier(Copier):
    key = 'parties'
    label = 'party incumbents'
    model = PartyIncumbent
    key_field = 'persistent_party_id'
    fields = ('electorate_seats', 'list_seats')
    # Most seats held first, the same order the manifest carries them in.
    order_by = ('-seats_held', 'persistent_party_id')

    def rows(self, version):
        return (self.model.objects
                .filter(results_version=version)
                .select_related('persistent_party')
                .annotate(seats_held=F('electorate_seats') + F('list_seats'))
                .order_by(*self.order_by))

    def describe(self, row):
        return (row.persistent_party.display_name
                or row.persistent_party.abbreviation
                or str(row.persistent_party_id))

    def describe_values(self, row):
        return (f'{row.total_seats} seats '
                f'({row.electorate_seats} electorate, {row.list_seats} list)')


COPIERS = {copier.key: copier for copier in
           (ElectorateIncumbentCopier, PartyIncumbentCopier)}


def seat_count_discrepancies(version):
    """Where a party's curated electorate seats disagree with its seats.

    Counted by where each member sits *now*, not the party the seat was won
    for, because that is what `PartyIncumbent.electorate_seats` means. Reported
    rather than enforced: a seat vacated mid-term is held by nobody and makes
    the two legitimately differ, so this is a prompt to look, not an error.

    Returns a list of (party, curated, counted), empty in the normal case.
    """
    counted = {}
    for incumbent in ElectorateIncumbent.objects.filter(
            results_version=version):
        party_id = incumbent.sitting_persistent_party_id
        if party_id:
            counted[party_id] = counted.get(party_id, 0) + 1

    rows = PartyIncumbent.objects.filter(
        results_version=version).select_related('persistent_party')
    return [
        (row.persistent_party, row.electorate_seats,
         counted.get(row.persistent_party_id, 0))
        for row in rows
        if row.electorate_seats != counted.get(row.persistent_party_id, 0)
    ]


class Command(BaseCommand):
    help = ('Copy curated incumbency from one results version to another '
            'version of the same election.')

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='source', required=True,
                            help='Slug of the results version to copy from.')
        parser.add_argument('--to', dest='target', required=True,
                            help='Slug of the results version to copy to.')
        parser.add_argument(
            '--election-slug',
            help='Election the two versions belong to. Only needed when the '
                 'version slugs are not unique across elections.',
        )
        parser.add_argument(
            '--only',
            help='Comma separated subset of: ' + ', '.join(sorted(COPIERS)),
        )
        parser.add_argument('--apply', action='store_true',
                            help='Write the rows. Without this, nothing changes.')
        parser.add_argument(
            '--overwrite', action='store_true',
            help='Also replace target rows that disagree with the source. Off '
                 'by default: the row already there may be the curated one.',
        )

    def handle(self, *args, **options):
        source = select_version(options['source'], options['election_slug'], '--from')
        target = select_version(options['target'], options['election_slug'], '--to')

        if source.pk == target.pk:
            raise CommandError('--from and --to are the same results version.')
        if source.election_id != target.election_id:
            raise CommandError(
                f'--from and --to belong to different elections '
                f'({source.election.slug} and {target.election.slug}). A '
                f'version\'s incumbents are the members elected at the '
                f'*previous* election, so copying across one would be a full '
                f'set of rows that are quietly an election out of date. '
                f'Curate the first version of a new election by hand.')

        copiers = self.select_copiers(options, source, target)

        self.stdout.write(f'{source.election.name}')
        self.stdout.write(f'  from  {source.slug}  ({source.name})')
        self.stdout.write(f'  to    {target.slug}  ({target.name})')

        totals = {COPY: 0, CONFLICT: 0, SAME: 0}
        written = 0

        for copier in copiers:
            pairings = copier.pairings()
            self.report(copier, pairings)

            for pairing in pairings:
                totals[pairing.kind] += 1

            if options['apply']:
                written += self.apply(copier, pairings, options)

        self.report_discrepancies(target)
        self.summarise(totals, written, options, source, target)

    # -- selection -------------------------------------------------------

    def select_copiers(self, options, source, target):
        keys = sorted(COPIERS)
        if options['only']:
            keys = [k.strip() for k in options['only'].split(',') if k.strip()]
            unknown = [k for k in keys if k not in COPIERS]
            if unknown:
                raise CommandError(
                    f'Unknown type(s): {", ".join(unknown)}. '
                    f'Choose from: {", ".join(sorted(COPIERS))}')

        return [COPIERS[key](source, target) for key in keys]

    # -- reporting -------------------------------------------------------

    def report(self, copier, pairings):
        counts = {kind: [p for p in pairings if p.kind == kind]
                  for kind in (COPY, CONFLICT, SAME)}
        total = copier.rows(copier.target_version).count()

        self.stdout.write(f'\n{copier.label}  {total} in target')

        if not pairings:
            self.stdout.write('       nothing curated in the source version')
            return

        if counts[COPY]:
            self.stdout.write(self.style.SUCCESS(
                f'  {len(counts[COPY]):>6}  to copy'))
            for pairing in counts[COPY][:5]:
                self.stdout.write(
                    f'            {copier.describe(pairing.source)}'
                    f'  ->  {copier.describe_values(pairing.source)}')
            if len(counts[COPY]) > 5:
                self.stdout.write(f'            ... and {len(counts[COPY]) - 5} more')
        if counts[SAME]:
            self.stdout.write(f'  {len(counts[SAME]):>6}  already the same')
        if counts[CONFLICT]:
            self.stdout.write(self.style.WARNING(
                f'  {len(counts[CONFLICT]):>6}  already curated differently   '
                f'--overwrite would replace'))
            for pairing in counts[CONFLICT][:5]:
                self.stdout.write(
                    f'            {copier.describe(pairing.source)}'
                    f'   {copier.describe_values(pairing.target)}'
                    f'  ->  {copier.describe_values(pairing.source)}')

    def report_discrepancies(self, target):
        """Where the two kinds of incumbency disagree about electorate seats."""
        discrepancies = seat_count_discrepancies(target)
        if not discrepancies:
            return
        self.stdout.write(self.style.WARNING(
            f'\n{len(discrepancies)} part'
            f'{"y" if len(discrepancies) == 1 else "ies"} '
            f'whose curated electorate seats differ from the seats counted:'))
        for party, curated, counted in discrepancies:
            self.stdout.write(
                f'    {party}   curated {curated}, counted {counted}')
        self.stdout.write(
            '  A seat vacated mid-term is held by nobody, so these can '
            'legitimately differ. Worth a look.')

    # -- changes ---------------------------------------------------------

    def apply(self, copier, pairings, options):
        wanted = [p for p in pairings if p.kind == COPY]
        if options['overwrite']:
            wanted += [p for p in pairings if p.kind == CONFLICT]

        if not wanted:
            return 0

        with transaction.atomic():
            count = copier.copy(wanted)

        self.stdout.write(self.style.SUCCESS(
            f'          copied {count} {copier.label}'))
        return count

    def summarise(self, totals, written, options, source, target):
        if not options['apply']:
            extra = (f' ({totals[CONFLICT]} more with --overwrite)'
                     if totals[CONFLICT] else '')
            self.stdout.write(self.style.WARNING(
                f'\nNothing was changed. --apply would copy '
                f'{totals[COPY]} row(s){extra}.'))
            return

        self.stdout.write(self.style.SUCCESS(f'\nCopied {written} row(s).'))
        if totals[CONFLICT] and not options['overwrite']:
            self.stdout.write(self.style.WARNING(
                f'{totals[CONFLICT]} row(s) were already curated differently '
                f'and were left alone.'))
        if written:
            self.stdout.write(
                'Incumbency rides in the manifest, so only the manifest has to '
                'be rewritten:\n'
                f'  python manage.py publish_election_snapshots '
                f'--election-slug {target.election.slug}')
