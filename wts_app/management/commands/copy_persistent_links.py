"""Copy curated persistent links from one results version to another.

Duplicating a results version duplicates the election entities with it, but not
the curation. A new version arrives with every ``persistent_candidate``,
``persistent_party``, ``electorate`` and ``persistent_voting_place`` empty, and
`match_persistent_entities` would have to decide hundreds of rows a second time
-- including the handful that needed a person to look at them.

Almost always the reference data has not changed between versions of the same
event: the same candidates stand in the same electorates for the same parties,
and the Commission numbers them the same way. So the links can simply be moved
across.

Rows are paired by Electoral Commission ``number``, which is what the numbering
is for, and then **checked** before anything is copied -- names must agree,
voting places must be within a few metres. A pair whose number matches but whose
identity does not is reported and left alone, because that means the two
versions are not numbered alike and copying would attach the wrong record.

Nothing changes unless you ask::

    # 1. Look
    python manage.py copy_persistent_links --from final --to final-revised

    # 2. Copy
    python manage.py copy_persistent_links --from final --to final-revised --apply

Afterwards the new version's reference data has changed, so push and publish::

    python manage.py push_election_links --version-slug final-revised
    python manage.py publish_election_snapshots --election-slug <slug>
"""

from dataclasses import dataclass, field

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from wts_app.matching import geo, names
from wts_app.models.elections import (
    ElectionCandidate,
    ElectionElectorate,
    ElectionParty,
    ElectionResultVersion,
    ElectionVotingPlace,
)

COPY = 'copy'
CONFLICT = 'conflict'
SAME = 'same'
MISMATCH = 'mismatch'
ABSENT = 'absent'


@dataclass
class Pairing:
    """One source row and the target row carrying its number."""

    source: object
    target: object | None
    persistent: object
    kind: str
    detail: str = ''


class Copier:
    """Base class. Subclasses name the field and supply the identity check."""

    key = ''
    label = ''
    model = None
    link_field = ''
    select_related = ()

    def __init__(self, source_version, target_version, threshold_metres=None):
        self.source_version = source_version
        self.target_version = target_version
        self.threshold_metres = threshold_metres or geo.DEFAULT_THRESHOLD_METRES

    # -- rows ------------------------------------------------------------

    def rows(self, version):
        return (self.model.objects
                .filter(results_version=version)
                .select_related(*self.select_related)
                .order_by('number'))

    def linked_sources(self):
        return self.rows(self.source_version).exclude(**{f'{self.link_field}__isnull': True})

    def target_total(self):
        return self.rows(self.target_version).count()

    def target_linked(self):
        return self.rows(self.target_version).exclude(
            **{f'{self.link_field}__isnull': True}).count()

    # -- pairing ---------------------------------------------------------

    def pairings(self):
        """Classify every linked source row against its counterpart."""
        by_number = {row.number: row for row in self.rows(self.target_version)}
        results = []

        for source in self.linked_sources():
            persistent = getattr(source, self.link_field)
            target = by_number.get(source.number)

            if target is None:
                results.append(Pairing(source, None, persistent, ABSENT,
                                       f'no number {source.number} in target'))
                continue

            existing_id = getattr(target, f'{self.link_field}_id')
            if existing_id == persistent.pk:
                results.append(Pairing(source, target, persistent, SAME))
                continue

            agrees, detail = self.agrees(source, target)
            if not agrees:
                results.append(Pairing(source, target, persistent, MISMATCH, detail))
                continue

            kind = CONFLICT if existing_id else COPY
            results.append(Pairing(source, target, persistent, kind, detail))

        return results

    def agrees(self, source, target):
        """Whether the two rows are the same thing. Returns (bool, detail)."""
        raise NotImplementedError

    # -- changes ---------------------------------------------------------

    def copy(self, pairings):
        """Write the links. Does not call save(), so no validation re-runs --
        only the persistent link changes, never results_version."""
        rows = []
        for pairing in pairings:
            setattr(pairing.target, self.link_field, pairing.persistent)
            rows.append(pairing.target)
        self.model.objects.bulk_update(rows, [self.link_field], batch_size=500)
        return len(rows)

    # -- description -----------------------------------------------------

    def describe(self, row):
        return f'{row.number}  {row.name}'

    def describe_persistent(self, persistent):
        return str(persistent)


class CandidateCopier(Copier):
    key = 'candidates'
    label = 'candidates'
    model = ElectionCandidate
    link_field = 'persistent_candidate'
    select_related = ('persistent_candidate', 'party', 'electorate')

    def agrees(self, source, target):
        # Trailing given names come and go between publications, so the same
        # structural rule match_persistent_entities links on is enough here.
        if names.normalise(source.name) == names.normalise(target.name):
            return True, ''
        if names.is_structural_match(source.name, target.name):
            return True, 'differs by middle names'
        return False, f'{source.name!r} vs {target.name!r}'

    def describe_persistent(self, persistent):
        return persistent.display_name


class PartyCopier(Copier):
    key = 'parties'
    label = 'parties'
    model = ElectionParty
    link_field = 'persistent_party'
    select_related = ('persistent_party',)

    def agrees(self, source, target):
        if names.normalise(source.name) == names.normalise(target.name):
            return True, ''
        # A party's registered name is edited between publications more often
        # than its abbreviation, which is the Commission's own short code.
        if source.abbreviation and source.abbreviation == target.abbreviation:
            return True, f'name differs, abbreviation {source.abbreviation} agrees'
        return False, f'{source.name!r} vs {target.name!r}'

    def describe_persistent(self, persistent):
        return persistent.display_name or persistent.abbreviation or str(persistent.pk)


class ElectorateCopier(Copier):
    key = 'electorates'
    label = 'electorates'
    model = ElectionElectorate
    link_field = 'electorate'
    select_related = ('electorate',)

    def agrees(self, source, target):
        if names.normalise(source.name) == names.normalise(target.name):
            return True, ''
        return False, f'{source.name!r} vs {target.name!r}'

    def describe_persistent(self, persistent):
        return persistent.name


class VotingPlaceCopier(Copier):
    key = 'voting-places'
    label = 'voting places'
    model = ElectionVotingPlace
    link_field = 'persistent_voting_place'
    select_related = ('persistent_voting_place', 'physical_electorate')

    def agrees(self, source, target):
        # Checked by proximity first, the same way these are matched in the
        # first place: the Commission republishes coordinates for one hall and
        # they drift by metres.
        metres = geo.distance_metres(
            (source.latitude, source.longitude), (target.latitude, target.longitude))
        if metres is not None:
            if metres <= self.threshold_metres:
                return True, (f'{metres:.0f} m apart' if metres >= 1 else '')
            return False, f'{metres:.0f} m apart'

        # One side has no coordinates, so fall back to the address text.
        if names.normalise(source.address) == names.normalise(target.address):
            return True, 'no coordinates; addresses identical'
        return False, 'no coordinates, and addresses differ'

    def describe(self, row):
        return f'{row.number}  {row.address}'

    def describe_persistent(self, persistent):
        return persistent.address


COPIERS = {copier.key: copier for copier in
           (CandidateCopier, PartyCopier, ElectorateCopier, VotingPlaceCopier)}


class Command(BaseCommand):
    help = ('Copy persistent entity links from one results version to another '
            'version of the same election.')

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='source', required=True,
                            help='Slug of the results version to copy links from.')
        parser.add_argument('--to', dest='target', required=True,
                            help='Slug of the results version to copy links to.')
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
                            help='Write the links. Without this, nothing changes.')
        parser.add_argument(
            '--overwrite', action='store_true',
            help='Also replace links the target already has, where they differ '
                 'from the source. Off by default: an existing link may be the '
                 'one that was curated.',
        )
        parser.add_argument(
            '--allow-mismatch', action='store_true',
            help='Copy even where the paired rows disagree about what they are. '
                 'Trusts the Commission numbers over the names; only use this '
                 'having looked at what the report says differs.',
        )
        parser.add_argument(
            '--distance-metres', type=int, default=geo.DEFAULT_THRESHOLD_METRES,
            help=f'How far two voting places with the same number may sit apart '
                 f'and still count as the same place. Default '
                 f'{geo.DEFAULT_THRESHOLD_METRES}.',
        )

    def handle(self, *args, **options):
        source = self.select_version(options['source'], options['election_slug'], '--from')
        target = self.select_version(options['target'], options['election_slug'], '--to')

        if source.pk == target.pk:
            raise CommandError('--from and --to are the same results version.')
        if source.election_id != target.election_id:
            raise CommandError(
                f'--from and --to belong to different elections '
                f'({source.election.slug} and {target.election.slug}). Links are '
                f'only comparable within one event; use '
                f'match_persistent_entities across elections.')

        copiers = self.select_copiers(options, source, target)

        self.stdout.write(f'{source.election.name}')
        self.stdout.write(f'  from  {source.slug}  ({source.name})')
        self.stdout.write(f'  to    {target.slug}  ({target.name})')

        totals = {COPY: 0, CONFLICT: 0, SAME: 0, MISMATCH: 0, ABSENT: 0}
        written = 0

        for copier in copiers:
            pairings = copier.pairings()
            self.report(copier, pairings)

            for pairing in pairings:
                totals[pairing.kind] += 1

            if options['apply']:
                written += self.apply(copier, pairings, options)

        self.summarise(totals, written, options)

    # -- selection -------------------------------------------------------

    def select_version(self, slug, election_slug, flag):
        versions = ElectionResultVersion.objects.select_related('election').filter(slug=slug)
        if election_slug:
            versions = versions.filter(election__slug=election_slug)

        found = list(versions)
        if not found:
            raise CommandError(f'{flag}: no results version has the slug {slug!r}.')
        if len(found) > 1:
            listed = '\n'.join(f'    {v.election.slug} / {v.slug}' for v in found)
            raise CommandError(
                f'{flag}: {len(found)} results versions have the slug {slug!r}. '
                f'Narrow with --election-slug:\n{listed}')
        return found[0]

    def select_copiers(self, options, source, target):
        keys = sorted(COPIERS)
        if options['only']:
            keys = [k.strip() for k in options['only'].split(',') if k.strip()]
            unknown = [k for k in keys if k not in COPIERS]
            if unknown:
                raise CommandError(
                    f'Unknown type(s): {", ".join(unknown)}. '
                    f'Choose from: {", ".join(sorted(COPIERS))}')

        return [COPIERS[key](source, target,
                             threshold_metres=options['distance_metres'])
                for key in keys]

    # -- reporting -------------------------------------------------------

    def report(self, copier, pairings):
        counts = {kind: [p for p in pairings if p.kind == kind]
                  for kind in (COPY, CONFLICT, SAME, MISMATCH, ABSENT)}
        total = copier.target_total()
        already = copier.target_linked()

        self.stdout.write(f'\n{copier.label}  {total} in target, {already} already linked')

        if not pairings:
            self.stdout.write('       nothing linked in the source version')
            return

        if counts[COPY]:
            self.stdout.write(self.style.SUCCESS(
                f'  {len(counts[COPY]):>6}  to copy'))
            for pairing in counts[COPY][:5]:
                self.stdout.write(
                    f'            {copier.describe(pairing.target)}'
                    f'  ->  {copier.describe_persistent(pairing.persistent)}'
                    + (f'   ({pairing.detail})' if pairing.detail else ''))
            if len(counts[COPY]) > 5:
                self.stdout.write(f'            ... and {len(counts[COPY]) - 5} more')
        if counts[SAME]:
            self.stdout.write(f'  {len(counts[SAME]):>6}  already the same link')
        if counts[CONFLICT]:
            self.stdout.write(self.style.WARNING(
                f'  {len(counts[CONFLICT]):>6}  linked to something else   '
                f'--overwrite would replace'))
            for pairing in counts[CONFLICT][:5]:
                existing = getattr(pairing.target, copier.link_field)
                self.stdout.write(
                    f'            {copier.describe(pairing.target)}'
                    f'   {copier.describe_persistent(existing)}'
                    f'  ->  {copier.describe_persistent(pairing.persistent)}')
        if counts[MISMATCH]:
            self.stdout.write(self.style.ERROR(
                f'  {len(counts[MISMATCH]):>6}  same number, different row  '
                f'never copied without --allow-mismatch'))
            for pairing in counts[MISMATCH][:10]:
                self.stdout.write(f'            {pairing.source.number}  {pairing.detail}')
        if counts[ABSENT]:
            self.stdout.write(self.style.WARNING(
                f'  {len(counts[ABSENT]):>6}  no counterpart in target'))
            for pairing in counts[ABSENT][:5]:
                self.stdout.write(f'            {copier.describe(pairing.source)}')

    # -- changes ---------------------------------------------------------

    def apply(self, copier, pairings, options):
        wanted = [p for p in pairings if p.kind == COPY]
        if options['overwrite']:
            wanted += [p for p in pairings if p.kind == CONFLICT]
        if options['allow_mismatch']:
            mismatched = [p for p in pairings if p.kind == MISMATCH]
            if not options['overwrite']:
                mismatched = [p for p in mismatched
                              if not getattr(p.target, f'{copier.link_field}_id')]
            wanted += mismatched

        if not wanted:
            return 0

        with transaction.atomic():
            count = copier.copy(wanted)

        self.stdout.write(self.style.SUCCESS(
            f'          copied {count} {copier.label}'))
        return count

    def summarise(self, totals, written, options):
        if not options['apply']:
            pending = totals[COPY]
            extra = []
            if totals[CONFLICT]:
                extra.append(f'{totals[CONFLICT]} more with --overwrite')
            if totals[MISMATCH]:
                extra.append(f'{totals[MISMATCH]} more with --allow-mismatch')
            tail = f' ({", ".join(extra)})' if extra else ''
            self.stdout.write(self.style.WARNING(
                f'\nNothing was changed. --apply would copy {pending} link(s){tail}.'))
            return

        self.stdout.write(self.style.SUCCESS(f'\nCopied {written} link(s).'))
        if totals[MISMATCH] and not options['allow_mismatch']:
            self.stdout.write(self.style.WARNING(
                f'{totals[MISMATCH]} row(s) share a number but are not the same '
                f'row, and were left alone.'))
        if written:
            self.stdout.write(
                'Reference data for the target version has changed. Push and publish:\n'
                '  python manage.py push_election_links --version-slug <target>\n'
                '  python manage.py publish_election_snapshots --election-slug <election>')
