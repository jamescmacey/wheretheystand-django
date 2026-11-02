"""Seed electorate incumbents from the site's own record of who sits where.

Incumbency is curated by hand, and the first version of a new election starts
with none of it -- seventy-odd seats to look up one at a time. But the site
already knows who holds them: a `ParliamentaryAffiliation` says which member
holds which electorate and when that ended, and a `PartyAffiliation` says which
party they sat for at any date. This reads both as at one date and writes what
it finds.

**This is a seed, not a source of truth.** It is right about the ordinary case
-- a member elected for a party, still in the seat, still in the party -- and it
says so plainly where it is unsure rather than guessing:

* An electorate abolished or redrawn since the last election has no row here
  unless `--follow-replacements` is given, and even then the mapping is only as
  good as the `replaced` links. A seat split between two successors has no
  honest answer and is left for a person.
* A member with no `PersistentCandidate` is skipped rather than written with an
  empty candidate, which the client reads as a seat that was *vacant*.
* A party that cannot be matched to a persistent record leaves the party empty,
  and the client shows no marker at all rather than a wrong one.

Everything skipped is listed with its reason, so what is left to do by hand is
the report rather than a re-reading of the whole list.

Nothing changes unless you ask::

    # 1. Look
    python manage.py seed_electorate_incumbents \\
        --election-slug 2026-general-election --version-slug preliminary \\
        --as-at 2026-11-02

    # 2. Write
    python manage.py seed_electorate_incumbents ... --as-at 2026-11-02 --apply

Rows already curated are left alone unless `--overwrite` is given: a row that
disagrees is more likely to be somebody's correction than a mistake.

Afterwards incumbency rides in the manifest, so only the manifest needs
rewriting::

    python manage.py publish_election_snapshots --election-slug <slug>
"""

from datetime import datetime

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from wts_app.management.versions import select_version
from wts_app.models.elections import (
    ElectionElectorate,
    ElectorateIncumbent,
    PersistentCandidate,
    PersistentParty,
)
from wts_app.models.parliaments import Parliament
from wts_app.models.people import ParliamentaryAffiliation, PartyAffiliation

CREATE = 'create'
SAME = 'same'
CONFLICT = 'conflict'

# What makes two rows the same row. `notes` is deliberately not here: it records
# where a row came from, including the as-at date, so comparing it would report
# every seat as a conflict on a re-run with a different date while the substance
# was identical.
COMPARE_FIELDS = ('persistent_candidate_id', 'persistent_party_id',
                  'has_left_party', 'current_persistent_party_id')

# How far to walk a chain of replaced electorates before deciding the links are
# a loop rather than a history.
REPLACEMENT_LIMIT = 5


def parse_as_at(value):
    """The date incumbency is read at, which decides the whole result."""
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise CommandError(f'--as-at: {value!r} is not a date. Use YYYY-MM-DD.')


def open_affiliations(as_at):
    """Electorate seats held on one date.

    Started by then and not yet ended. A member is counted from the day they
    were sworn in where that is recorded, and from their election where it is
    not, because an affiliation with neither date cannot be placed in time at
    all and should not be guessed at.
    """
    started = (Q(sworn_date__lte=as_at)
               | Q(sworn_date__isnull=True, elected_date__lte=as_at))
    not_ended = Q(end_date__isnull=True) | Q(end_date__gte=as_at)

    return (ParliamentaryAffiliation.objects
            .filter(electorate__isnull=False)
            .filter(started)
            .filter(not_ended)
            .select_related('electorate', 'person', 'parliament')
            .order_by('electorate__name'))


def party_at(person, when):
    """The party a person sat for on one date, or None.

    None is not the same as independent. It means the site holds no affiliation
    covering that date, which is as often a gap in the record as a statement
    about the person.
    """
    if when is None:
        return None
    return (PartyAffiliation.objects
            .filter(person=person, start_date__lte=when)
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=when))
            .select_related('party')
            .order_by('-start_date')
            .first())


def had_party_before(person, as_at):
    """Whether the person's party membership had lapsed by the as-at date.

    An affiliation that ended, with nothing after it, is the site's way of
    recording a member who left their party and did not join another. That is a
    defection to the cross benches, and it is the one case the candidate list
    can never show: a member who crossed the floor and is not standing again
    leaves no trace in it.
    """
    return (PartyAffiliation.objects
            .filter(person=person, end_date__isnull=False, end_date__lt=as_at)
            .exists())


def persistent_party_index():
    """Site parties to persistent parties, and the keys too ambiguous to use.

    The link between the two is a nullable one-to-one that nothing has filled
    in, so names do the work instead. Any key held by more than one persistent
    party is dropped rather than resolved arbitrarily: matching the wrong party
    would put a seat in the wrong column and look entirely plausible doing it.
    """
    by_party_id = {}
    candidates = {}

    for persistent in PersistentParty.objects.all():
        if persistent.party_id:
            by_party_id[persistent.party_id] = persistent
        for key in (persistent.abbreviation, persistent.display_name,
                    persistent.short_name):
            if key and key.strip():
                candidates.setdefault(key.strip().casefold(), set()).add(persistent)

    by_name = {key: next(iter(found))
               for key, found in candidates.items() if len(found) == 1}
    return by_party_id, by_name


def match_persistent_party(party, index):
    """One site party as its persistent record, or None where nothing matches."""
    if party is None:
        return None

    by_party_id, by_name = index
    if party.id in by_party_id:
        return by_party_id[party.id]

    for key in (party.abbreviation, party.display_name, party.short_name,
                party.legal_name):
        if key and key.strip():
            found = by_name.get(key.strip().casefold())
            if found:
                return found
    return None


def predecessors(electorate):
    """The electorates this one was drawn from, nearest first.

    Walked from this election's side rather than the other way round, because
    the question being asked is "who held this seat", and the answer for a
    redrawn seat lies in the one it replaced. Stops at a loop or a chain long
    enough to be one.
    """
    chain = []
    current = electorate

    for _ in range(REPLACEMENT_LIMIT):
        previous = current.replaced
        if previous is None or previous.id in {link.id for link in chain}:
            break
        chain.append(previous)
        current = previous

    return chain


def last_member_of(electorates, parliament, as_at):
    """The member who last held one of these seats, where it is now empty.

    A seat whose member died or resigned with no by-election before polling day
    is held by nobody, and that is a fact about it worth recording: this model
    says it with a row naming the party but no candidate. Limited to the
    Parliament sitting on the as-at date, so that an electorate abolished years
    ago is not resurrected as a vacancy.
    """
    if parliament is None:
        return None
    return (ParliamentaryAffiliation.objects
            .filter(electorate__in=electorates, parliament=parliament,
                    end_date__isnull=False, end_date__lt=as_at)
            .select_related('electorate', 'person')
            .order_by('-end_date')
            .first())


class Proposal:
    """One seat of this election: the row it would get, or why it gets none.

    One per electorate being contested, rather than one per sitting member.
    Those are the same list at a general election and nothing like it at a
    by-election, where every other seat in the country is simply not up for
    election and has no business in the report.
    """

    def __init__(self, electorate, affiliation=None, row=None, kind=None,
                 existing=None, skipped=None, detail='', new_candidate=False):
        self.electorate = electorate
        self.affiliation = affiliation
        self.row = row
        self.kind = kind
        self.existing = existing
        self.skipped = skipped
        self.detail = detail
        # Carried explicitly rather than inferred from the candidate's pk: a
        # UUID primary key has a default, so an unsaved instance already has
        # one and nothing about it looks new.
        self.new_candidate = new_candidate

    @property
    def member(self):
        if self.affiliation is not None:
            return self.affiliation.person.display_name
        # A row with no affiliation is a vacancy; no row at all is a seat this
        # could not speak for, and naming nobody is the honest answer.
        return 'vacant' if self.row is not None else ''

    @property
    def seat(self):
        return self.electorate.name


class Command(BaseCommand):
    help = ('Seed a results version\'s electorate incumbents from '
            'parliamentary and party affiliations, as at a date.')

    def add_arguments(self, parser):
        parser.add_argument('--election-slug', required=True,
                            help='Election the results version belongs to.')
        parser.add_argument('--version-slug', required=True,
                            help='Results version to write the incumbents to.')
        parser.add_argument(
            '--as-at', required=True,
            help='Date (YYYY-MM-DD) to read incumbency at. Usually the day '
                 'Parliament was dissolved, or today while it still sits.',
        )
        parser.add_argument('--apply', action='store_true',
                            help='Write the rows. Without this, nothing changes.')
        parser.add_argument(
            '--overwrite', action='store_true',
            help='Also replace rows that disagree. Off by default: the row '
                 'already there is more likely to be a correction.',
        )
        parser.add_argument(
            '--create-candidates', action='store_true',
            help='Create a PersistentCandidate for a sitting member who has '
                 'none, rather than skipping the seat.',
        )
        parser.add_argument(
            '--follow-replacements', action='store_true',
            help='Carry a member of an abolished electorate to the electorate '
                 'that replaced it. Only as good as the replacement links.',
        )

    # -- the run ---------------------------------------------------------

    def handle(self, *args, **options):
        # Eight examples is enough to see the shape of a run; somebody actually
        # checking a seed before applying it wants the lot.
        self.examples = None if options['verbosity'] >= 2 else 8
        as_at = parse_as_at(options['as_at'])
        version = select_version(options['version_slug'],
                                 options['election_slug'], '--version-slug')

        electorates = {
            row.electorate_id: row
            for row in ElectionElectorate.objects.filter(results_version=version)
            if row.electorate_id
        }
        if not electorates:
            raise CommandError(
                f'{version.election.slug} / {version.slug} has no electorates '
                f'linked to persistent records yet, so there is nothing to '
                f'attach incumbents to. Build its reference data first, then '
                f'link it with:\n'
                f'  python manage.py match_persistent_entities '
                f'--election-slug {version.election.slug}')

        self.parliament = (Parliament.objects
                           .filter(start_date__lte=as_at)
                           .filter(Q(end_date__isnull=True)
                                   | Q(end_date__gte=as_at))
                           .order_by('-start_date')
                           .first())

        self.stdout.write(f'{version.election.name}')
        self.stdout.write(f'  into    {version.slug}  ({version.name})')
        self.stdout.write(f'  as at   {as_at}  ({self.parliament or "no "
                                                 "Parliament sitting"})')
        self.stdout.write(f'  seats   {len(electorates)} in this election')

        polling_date = version.election.polling_date
        if polling_date and as_at > polling_date:
            self.stdout.write(self.style.WARNING(
                f'\n--as-at is after polling day ({polling_date}). Incumbency '
                f'is who held each seat *going into* the election, so this '
                f'would read back the members it elected.'))

        proposals = self.propose(version, electorates, as_at, options)
        self.report(proposals, options)

        if options['apply']:
            self.apply(version, proposals, options)
        else:
            self.summarise_dry_run(proposals, options)

    # -- working it out --------------------------------------------------

    def propose(self, version, electorates, as_at, options):
        """One proposal per seat being contested, in electorate order."""
        index = persistent_party_index()
        existing = {row.electorate_id: row for row in
                    ElectorateIncumbent.objects.filter(results_version=version)}

        held = {}
        for affiliation in open_affiliations(as_at):
            held.setdefault(affiliation.electorate_id, []).append(affiliation)

        self.unused = dict(held)
        proposals = [
            self.propose_one(version, electorate, held, existing, as_at, index,
                             options)
            for electorate in sorted(electorates.values(),
                                     key=lambda row: row.name)
        ]

        # Whoever is left held a seat that is not being contested under that
        # name. At a general election that is a boundary change and a hint
        # about the seats still missing a member; at a by-election it is simply
        # the rest of the country.
        self.unused = [affiliation
                       for affiliations in self.unused.values()
                       for affiliation in affiliations]
        return proposals

    def propose_one(self, version, electorate, held, existing, as_at, index,
                    options):
        """Who held this seat, looking back through the seats it replaced."""
        seat = electorate.electorate
        chain = [seat]
        if options['follow_replacements']:
            chain += predecessors(seat)

        for position, link in enumerate(chain):
            affiliations = held.get(link.id)
            if not affiliations:
                continue

            self.unused.pop(link.id, None)
            # Two open affiliations for one seat means a by-election whose
            # predecessor was never closed off. Report it rather than pick.
            if len(affiliations) > 1:
                names = ', '.join(a.person.display_name for a in affiliations)
                return Proposal(seat, skipped='two members hold this seat',
                                detail=names)

            carried = link.name if position else ''
            return self.build_proposal(version, seat, affiliations[0], existing,
                                       as_at, index, options, carried)

        return self.propose_vacancy(version, seat, chain, existing, as_at,
                                    index, options)

    def propose_vacancy(self, version, seat, chain, existing, as_at, index,
                        options):
        """A seat nobody holds, or one this cannot speak for at all."""
        parliament = self.parliament
        last = last_member_of(chain, parliament, as_at)
        if last is None:
            return Proposal(seat, skipped='no member found',
                            detail=self.describe_gap(seat, options))

        won_for, _, party_detail = self.resolve_parties(last, as_at, index)
        row = ElectorateIncumbent(
            results_version=version,
            electorate=seat,
            # No candidate is this model's way of saying the seat was vacant,
            # which is exactly what happened: the member left mid-term and no
            # by-election filled it before polling day.
            persistent_candidate=None,
            persistent_party=won_for,
            notes=(f'Seeded as vacant from parliamentary affiliations as at '
                   f'{as_at}. {last.person.display_name} held it until '
                   f'{last.end_date}.'),
        )
        return self.classify(Proposal(seat, affiliation=None, row=row,
                                      detail=party_detail or 'vacant'), existing)

    def build_proposal(self, version, seat, affiliation, existing, as_at, index,
                       options, carried):
        candidate, new_candidate = self.resolve_candidate(affiliation, options)
        if candidate is None:
            return Proposal(seat, affiliation=affiliation,
                            skipped='no persistent candidate')

        won_for, sits_for, party_detail = self.resolve_parties(
            affiliation, as_at, index)

        row = ElectorateIncumbent(
            results_version=version,
            electorate=seat,
            persistent_candidate=candidate,
            persistent_party=won_for,
        )
        # Only a party the member has genuinely moved away from. Where the two
        # agree, or the party at election is unknown, there is no defection to
        # record -- and `clean()` would reject the pair anyway.
        if won_for and sits_for != won_for:
            row.has_left_party = True
            row.current_persistent_party = sits_for
        row.notes = self.build_note(as_at, carried)

        try:
            row.clean()
        except ValidationError as error:
            return Proposal(seat, affiliation=affiliation,
                            skipped='would not validate',
                            detail='; '.join(error.messages))

        return self.classify(
            Proposal(seat, affiliation=affiliation, row=row,
                     detail=party_detail, new_candidate=new_candidate),
            existing)

    def classify(self, proposal, existing):
        """Whether this row is new, unchanged, or a disagreement."""
        held = existing.get(proposal.electorate.id)
        proposal.existing = held
        if held is None:
            proposal.kind = CREATE
        elif self.values(held) == self.values(proposal.row):
            proposal.kind = SAME
        else:
            proposal.kind = CONFLICT
        return proposal

    def describe_gap(self, seat, options):
        """Why a seat has no member, in terms of what would change it."""
        chain = predecessors(seat)
        if not chain:
            return f'{seat.status}, replaced nothing'
        names = ', '.join(link.name for link in chain)
        if options['follow_replacements']:
            return f'replaced {names}, none of them held at this date'
        return f'replaced {names} -- --follow-replacements would look there'

    def resolve_candidate(self, affiliation, options):
        """The member as a persistent candidate, creating one where asked.

        Never silently left empty: an empty candidate is how this model says a
        seat was *vacant*, and a retiring member is not a vacancy.
        """
        candidate = PersistentCandidate.objects.filter(
            person=affiliation.person).first()
        if candidate or not options['create_candidates']:
            return candidate, False

        person = affiliation.person
        # The Electoral Commission's own format, which is what every other
        # persistent candidate in the table looks like.
        display_name = f'{person.last_name.upper()}, {person.first_name}'.strip()
        return PersistentCandidate(
            person=person, display_name=display_name), True

    def resolve_parties(self, affiliation, as_at, index):
        """The party the seat was won for, and the one the member sits for now.

        The first is what a flip is measured against and comes from the date
        they were elected, not today: a member who crossed the floor did not
        change who won the seat.
        """
        elected_on = affiliation.elected_date or affiliation.sworn_date
        at_election = party_at(affiliation.person, elected_on)
        now = party_at(affiliation.person, as_at)

        won_for = match_persistent_party(
            at_election.party if at_election else None, index)
        sits_for = match_persistent_party(now.party if now else None, index)

        detail = ''
        if at_election and not won_for:
            detail = f'no persistent party for {at_election.party.display_name}'
        elif not at_election:
            detail = f'no party affiliation at {elected_on}'

        if now is None and won_for is not None:
            # Membership lapsed with nothing after it: the cross benches.
            if had_party_before(affiliation.person, as_at):
                sits_for = None
                detail = detail or 'party membership lapsed, now independent'
            else:
                # No record either way. Say nothing rather than call somebody
                # an independent on the strength of a missing row.
                sits_for = won_for

        return won_for, sits_for, detail

    def build_note(self, as_at, carried):
        note = f'Seeded from parliamentary affiliations as at {as_at}.'
        if carried:
            note = f'{note} Held {carried}.'
        return note

    def values(self, row):
        return {field: getattr(row, field) for field in COMPARE_FIELDS}

    # -- reporting -------------------------------------------------------

    def report(self, proposals, options):
        for kind, label, style in ((CREATE, 'to write', self.style.SUCCESS),
                                   (SAME, 'already the same', None),
                                   (CONFLICT, 'already curated differently',
                                    self.style.WARNING)):
            rows = [p for p in proposals if p.kind == kind]
            if not rows:
                continue

            heading = f'  {len(rows):>6}  {label}'
            if kind == CONFLICT:
                heading += '   --overwrite would replace'
            self.stdout.write('\n' + (style(heading) if style else heading))

            if kind == SAME:
                continue
            shown = rows if self.examples is None else rows[:self.examples]
            for proposal in shown:
                self.stdout.write(f'            {self.describe(proposal)}')
            if len(shown) < len(rows):
                self.stdout.write(
                    f'            ... and {len(rows) - len(shown)} more '
                    f'(-v 2 lists them all)')

        self.report_skipped(proposals)
        self.report_unplaced(proposals)
        self.report_ambiguous_parties(proposals)

    def describe(self, proposal):
        row = proposal.row
        party = (row.persistent_party.display_name
                 if row.persistent_party else 'no party matched')
        text = f'{proposal.seat:22} {proposal.member}  ({party}'
        if row.has_left_party:
            now = (row.current_persistent_party.display_name
                   if row.current_persistent_party else 'independent')
            text += f', now {now}'
        return text + ')'

    def report_skipped(self, proposals):
        """What is left to do by hand, grouped by why."""
        skipped = [p for p in proposals if p.skipped]
        if not skipped:
            return

        self.stdout.write(self.style.WARNING(
            f'\n  {len(skipped):>6}  skipped, for a person to decide'))

        reasons = {}
        for proposal in skipped:
            reasons.setdefault(proposal.skipped, []).append(proposal)

        for reason, rows in sorted(reasons.items()):
            self.stdout.write(f'\n      {reason}  ({len(rows)})')
            for proposal in rows:
                detail = f'   {proposal.detail}' if proposal.detail else ''
                self.stdout.write(
                    f'        {proposal.seat:22} {proposal.member}{detail}')

    def report_unplaced(self, proposals):
        """Members whose seat is not contested, where a seat still needs one.

        Only shown where something is missing. These are the members a
        boundary change stranded, and one of them is usually the answer to a
        seat the command could not fill -- but at a by-election the list is
        every other member in the country, so it is worth nothing unless there
        is a gap to fill.
        """
        gaps = [p for p in proposals if p.skipped == 'no member found']
        if not gaps or not self.unused:
            return

        self.stdout.write(self.style.WARNING(
            f'\n  {len(self.unused)} member(s) held a seat that is not being '
            f'contested under that name, and may belong to a seat above:'))
        shown = (self.unused if self.examples is None
                 else self.unused[:self.examples])
        for affiliation in shown:
            self.stdout.write(
                f'        {affiliation.electorate.name:22} '
                f'{affiliation.person.display_name} '
                f'({affiliation.electorate.status})')
        if len(shown) < len(self.unused):
            self.stdout.write(
                f'        ... and {len(self.unused) - len(shown)} more')

    def report_ambiguous_parties(self, proposals):
        """Seats written without a party, which show no marker at all."""
        unmatched = [p for p in proposals
                     if p.row is not None and p.row.persistent_party is None]
        if not unmatched:
            return
        self.stdout.write(self.style.WARNING(
            f'\n  {len(unmatched)} seat(s) have no persistent party, so the '
            f'dashboard will show no hold, gain or marker for them:'))
        shown = unmatched if self.examples is None else unmatched[:self.examples]
        for proposal in shown:
            self.stdout.write(f'        {proposal.seat:22} {proposal.detail}')

    # -- writing ---------------------------------------------------------

    def apply(self, version, proposals, options):
        wanted = [p for p in proposals if p.kind == CREATE]
        if options['overwrite']:
            wanted += [p for p in proposals if p.kind == CONFLICT]

        if not wanted:
            self.stdout.write(self.style.WARNING('\nNothing to write.'))
            return

        created_candidates = [p.row.persistent_candidate for p in wanted
                              if p.new_candidate]

        with transaction.atomic():
            # Saved first: each row holds the instance rather than an id, and
            # Django fills the foreign key in from it on the row's own save.
            for candidate in created_candidates:
                candidate.save()

            written = updated = 0
            for proposal in wanted:
                if proposal.kind == CREATE:
                    proposal.row.save()
                    written += 1
                else:
                    # Only the substance. A curator's note on the row being
                    # replaced is theirs and is left as it is.
                    for field in COMPARE_FIELDS:
                        setattr(proposal.existing, field,
                                getattr(proposal.row, field))
                    proposal.existing.save()
                    updated += 1

        if created_candidates:
            self.stdout.write(self.style.SUCCESS(
                f'\nCreated {len(created_candidates)} persistent candidate(s).'))
        self.stdout.write(self.style.SUCCESS(
            f'Wrote {written} incumbent(s), replaced {updated}.'))

        skipped = len([p for p in proposals if p.skipped])
        if skipped:
            self.stdout.write(self.style.WARNING(
                f'{skipped} seat(s) were skipped and still need a person.'))

        self.stdout.write(
            'Incumbency rides in the manifest, so only the manifest has to be '
            'rewritten:\n'
            f'  python manage.py publish_election_snapshots '
            f'--election-slug {version.election.slug}')

    def summarise_dry_run(self, proposals, options):
        creating = len([p for p in proposals if p.kind == CREATE])
        conflicts = len([p for p in proposals if p.kind == CONFLICT])
        missing = len([p for p in proposals
                       if p.skipped == 'no persistent candidate'])

        extra = f' ({conflicts} more with --overwrite)' if conflicts else ''
        self.stdout.write(self.style.WARNING(
            f'\nNothing was changed. --apply would write '
            f'{creating} row(s){extra}.'))
        if missing:
            self.stdout.write(
                f'--create-candidates would recover {missing} more by creating '
                f'a persistent candidate for each sitting member who has none.')
