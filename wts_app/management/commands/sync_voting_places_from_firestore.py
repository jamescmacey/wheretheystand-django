"""Bring late voting place changes from Firestore into this database.

The Electoral Commission can change votingplaces.xml up to the day before an
election. `firebase_migrate_elections` is not safe at that point: it re-imports
every reference collection, replaces each persistent link here with whatever
Firestore holds, and never deletes a row. This reads only voting places and
keeps the curated links.

Run it after `tools_sync_voting_places.py` in election-results-manager::

    python manage.py sync_voting_places_from_firestore --election-slug 2026-general-election --version-slug election-night --dry-run
    python manage.py sync_voting_places_from_firestore --election-slug 2026-general-election --version-slug election-night

A link is cleared only when a voting place loses its coordinates or moves beyond
the matching distance. Nothing here reaches Algolia, R2 or the persistent
records, so the steps printed at the end are still needed.
"""

from contextlib import nullcontext
from dataclasses import dataclass, field

from algoliasearch_django.decorators import disable_auto_indexing
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from wts_app.firebase import push
from wts_app.firebase.client import event_filter, get_firestore_client
from wts_app.matching import geo
from wts_app.models.elections import (
    ElectionElectorate,
    ElectionResultVersion,
    ElectionVotingPlace,
    PersistentVotingPlace,
    ResultsSet,
)

LINK_FIELD = 'persistent_voting_place_id'

# About 10 cm. Below this a coordinate is only being reformatted.
COORDINATE_TOLERANCE = 1e-6


@dataclass
class Plan:
    create: list = field(default_factory=list)
    update: list = field(default_factory=list)
    delete: list = field(default_factory=list)
    # Rows whose link no longer holds, each with the reason.
    cleared: list = field(default_factory=list)
    # Firestore documents still naming a link that no longer holds.
    clear_in_firestore: list = field(default_factory=list)
    # Rows that keep their link but which a person should look at.
    review: list = field(default_factory=list)


def _same_coordinate(old, new):
    if old is None or new is None:
        return old is new
    return abs(old - new) < COORDINATE_TOLERANCE


def _link_problem(row, latitude, longitude):
    """Why this change breaks the row's link, or None if the link still holds."""
    had = row.latitude is not None and row.longitude is not None
    has = latitude is not None and longitude is not None
    if had and not has:
        return 'coordinates removed'
    if had and has:
        metres = geo.distance_metres((row.latitude, row.longitude), (latitude, longitude))
        if metres > geo.DEFAULT_THRESHOLD_METRES:
            return f'moved {metres:.0f} m'
    return None


def build_plan(version, documents):
    """Compare Firestore's documents with this version's rows. Writes nothing."""
    electorates = {
        electorate.number: electorate
        for electorate in ElectionElectorate.objects.filter(results_version=version)
    }
    rows = {
        row.number: row
        for row in ElectionVotingPlace.objects.filter(results_version=version)
        .select_related('physical_electorate', 'persistent_voting_place')
    }
    persistent = {
        place.firebase_id: place
        for place in PersistentVotingPlace.objects.exclude(firebase_id__isnull=True).exclude(firebase_id='')
    }

    plan = Plan()
    seen = set()

    for document in documents:
        data = document.to_dict()
        number = data.get('voting_place_id')
        if not number or number in seen:
            raise CommandError(f'{document.id} has a missing or duplicate voting_place_id.')
        seen.add(number)

        electorate = electorates.get(data.get('physical_electorate_id'))
        if electorate is None:
            raise CommandError(
                f'Voting place {number} names electorate '
                f'{data.get("physical_electorate_id")}, which this version does not have.')

        address = data.get('address', '')
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        row = rows.get(number)

        if row is None:
            plan.create.append(ElectionVotingPlace(
                results_version=version,
                firebase_id=document.id,
                number=number,
                physical_electorate=electorate,
                address=address,
                latitude=latitude,
                longitude=longitude,
                persistent_voting_place=persistent.get(data.get(LINK_FIELD)),
            ))
            continue

        coordinates_changed = not (_same_coordinate(row.latitude, latitude)
                                   and _same_coordinate(row.longitude, longitude))
        address_changed = row.address != address
        changed = (coordinates_changed or address_changed
                   or row.physical_electorate_id != electorate.id
                   or row.firebase_id != document.id)
        if not changed:
            continue

        problem = _link_problem(row, latitude, longitude) if coordinates_changed else None
        if problem:
            if row.persistent_voting_place_id:
                plan.cleared.append((row, problem))
                row.persistent_voting_place = None
            if data.get(LINK_FIELD):
                plan.clear_in_firestore.append(document.id)
        elif address_changed and row.persistent_voting_place_id:
            # The same coordinates do not prove the same place: in 2026 a voting
            # place changed street while keeping its coordinates.
            plan.review.append((row, row.address, address))

        row.firebase_id = document.id
        row.physical_electorate = electorate
        row.address = address
        if coordinates_changed:
            row.latitude = latitude
            row.longitude = longitude
        plan.update.append(row)

    plan.delete = [rows[number] for number in sorted(set(rows) - seen)]
    return plan


def apply_plan(plan):
    """Write the plan to Firestore's link fields, then to this database.

    Firestore goes first because a failure there leaves this database unchanged,
    so running the command again finds the same work. In the other order, a
    failure would leave a stale link in Firestore that nothing would look for.

    Results for the voting places being removed go too. The command asks first.
    """
    push.clear_voting_place_links(plan.clear_in_firestore)

    with transaction.atomic():
        ElectionVotingPlace.objects.bulk_create(plan.create, batch_size=500)
        ElectionVotingPlace.objects.bulk_update(
            plan.update,
            fields=['firebase_id', 'physical_electorate', 'address', 'latitude',
                    'longitude', 'persistent_voting_place', 'updated_at'],
            batch_size=500,
        )
        # A queryset delete would otherwise call Algolia per row, from inside
        # this transaction. sync_voting_places removes the stale records.
        # disable_auto_indexing reconnects its receivers on exit, even where
        # auto indexing was off, so it's only used where it was on.
        pause_indexing = (disable_auto_indexing(ElectionVotingPlace)
                          if settings.ALGOLIA.get('AUTO_INDEXING') else nullcontext())
        removed = [row.pk for row in plan.delete]
        with pause_indexing:
            ResultsSet.objects.filter(voting_place__in=removed).delete()
            ElectionVotingPlace.objects.filter(pk__in=removed).delete()


class Command(BaseCommand):
    help = 'Apply late voting place changes from Firestore, keeping persistent links.'

    def add_arguments(self, parser):
        parser.add_argument('--election-slug', required=True, help='The election.')
        parser.add_argument('--version-slug', required=True, help='The results version.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without writing.')
        parser.add_argument('--max-removals', type=int, default=25,
                            help='Refuse if more voting places than this would go (default 25).')

    def handle(self, *args, **options):
        version = self.select_version(options['election_slug'], options['version_slug'])

        db = get_firestore_client()
        collection = db.collection(push.ELECTION_VOTING_PLACES)
        documents = list(event_filter(collection, version.firebase_id).stream())
        if not documents:
            raise CommandError(
                f'Firestore has no voting places for {version.firebase_id}. '
                'Nothing was changed.')

        plan = build_plan(version, documents)
        self.report(version, len(documents), plan)
        self.check_safe(plan, options['max_removals'])

        if not (plan.create or plan.update or plan.delete):
            self.stdout.write('Nothing to do.')
            return

        with_results = self.results_to_delete(plan)
        self.report_results(with_results)

        if options['dry_run']:
            if with_results:
                self.stdout.write('A real run asks before deleting these results.')
            self.stdout.write(self.style.WARNING('Dry run. Nothing was written.'))
            return

        if with_results and not self.confirm_results_deletion(with_results):
            raise CommandError(
                'Those results were kept, so nothing was changed. Voting places '
                'with results cannot be removed without deleting them.')

        try:
            apply_plan(plan)
        except push.FirebasePushDisabled as exc:
            raise CommandError(f'{exc} Nothing was changed.')

        self.stdout.write(self.style.SUCCESS('Done.'))
        self.print_next_steps(options['election_slug'], options['version_slug'])

    def select_version(self, election_slug, version_slug):
        version = (ElectionResultVersion.objects.select_related('election')
                   .filter(election__slug=election_slug, slug=version_slug)
                   .exclude(firebase_id__isnull=True).exclude(firebase_id='')
                   .first())
        if version is None:
            raise CommandError(
                'No results version with a Firestore event id matched those slugs.')
        return version

    def check_safe(self, plan, max_removals):
        if len(plan.delete) > max_removals:
            raise CommandError(
                f'{len(plan.delete)} voting places would be removed, over the limit of '
                f'{max_removals}. Check Firestore, then raise --max-removals if it is right.')

    def results_to_delete(self, plan):
        """Result set counts for the voting places being removed, by number."""
        rows = (ResultsSet.objects
                .filter(voting_place__in=[row.pk for row in plan.delete])
                .values('voting_place__number')
                .annotate(count=Count('pk'))
                .order_by('voting_place__number'))
        return {row['voting_place__number']: row['count'] for row in rows}

    def report_results(self, with_results):
        if with_results:
            self.stdout.write('Voting places being removed that have results')
            for number, count in with_results.items():
                self.stdout.write(f'  {number}: {count} result set(s)')
            self.stdout.write('')

    def confirm_results_deletion(self, with_results):
        """Ask before deleting results. No answer, as in a script, means no."""
        total = sum(with_results.values())
        try:
            answer = input(
                f'Delete these {total} result set(s) and remove the voting places? [y/N] ')
        except EOFError:
            self.stdout.write('')
            return False
        return answer.strip().lower() in ('y', 'yes')

    def report(self, version, document_count, plan):
        write = self.stdout.write
        write(f'{version.election.slug}/{version.slug} ({version.firebase_id}): '
              f'{document_count} voting places in Firestore')
        write(f'  {len(plan.create)} to create, {len(plan.update)} to update, '
              f'{len(plan.delete)} to remove\n')

        def section(title, lines):
            if lines:
                write(title)
                for line in lines:
                    write(f'  {line}')
                write('')

        section('Create', [f'{row.number}: {row.address}' for row in plan.create])
        section('Remove', [f'{row.number}: {row.address}' for row in plan.delete])
        section('Link cleared: rematch these',
                [f'{row.number}: {problem}. {row.address}' for row, problem in plan.cleared])
        section('Link kept: check it still fits',
                [f'{row.number}: {old} -> {new}' for row, old, new in plan.review])

    def print_next_steps(self, election, version):
        slugs = f'--election-slug {election} --version-slug {version}'
        self.stdout.write('\nNext, in this order:')
        for command in (
            f'match_persistent_entities {slugs} --only voting-places --interactive',
            'push_persistent_to_firebase',
            f'push_election_links {slugs} --only voting-places',
            f'publish_election_snapshots {slugs} --voting-places',
            f'sync_voting_places {slugs}',
        ):
            self.stdout.write(f'  python manage.py {command}')
        self.stdout.write('Then restart election-feed-worker, which reads voting places at startup.')
