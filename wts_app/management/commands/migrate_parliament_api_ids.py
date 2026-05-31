import json
import os
import re
import unicodedata

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Prefetch

from wts_app.models.people import ParliamentaryAffiliation, Person

JSON_FILE = "migration/parliament_api_filters.json"

HONORIFIC_PREFIX = re.compile(
    r"^(?:(?:Rt\s+)?Hon\.?|Hon\.?|Dr\.?|Sir|Dame|Cr\.?|Rev\.?|Prof\.?)\s+",
    re.IGNORECASE,
)


def parse_member_display_name(display_name):
    """
    Parse a parliament API member DisplayName ("Last, First") into name parts.
    Strips honorific prefixes from the first-name portion.
    """
    if "," not in display_name:
        return None, None

    last_name, first_part = display_name.split(",", 1)
    last_name = last_name.strip()
    first_name = first_part.strip()

    while True:
        stripped = HONORIFIC_PREFIX.sub("", first_name, count=1).strip()
        if stripped == first_name:
            break
        first_name = stripped

    return last_name, first_name


def normalize_for_matching(value):
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(
        char for char in normalized if not unicodedata.combining(char)
    ).casefold()


def first_names_match(person_first_name, member_first_name):
    person_first_name = normalize_for_matching(person_first_name)
    member_first_name = normalize_for_matching(member_first_name)

    if person_first_name == member_first_name:
        return True

    if (
        person_first_name.startswith(member_first_name)
        or member_first_name.startswith(person_first_name)
    ):
        return True

    person_parts = person_first_name.split()
    member_parts = member_first_name.split()
    return any(part in member_parts for part in person_parts)


def last_names_match(person_last_name, member_last_name):
    person_last_name = normalize_for_matching(person_last_name)
    member_last_name = normalize_for_matching(member_last_name)

    if person_last_name == member_last_name:
        return True

    person_parts = person_last_name.split("-")
    return member_last_name in person_parts or person_last_name.startswith(
        member_last_name + "-"
    )


def member_matches_person(person, member_last_name, member_first_name):
    if not last_names_match(person.last_name, member_last_name):
        return False

    if first_names_match(person.first_name, member_first_name):
        return True

    expected_display = normalize_for_matching(f"{person.first_name} {person.last_name}")
    member_display = normalize_for_matching(f"{member_first_name} {member_last_name}")
    return expected_display == member_display or normalize_for_matching(
        person.display_name
    ) == member_display


class Command(BaseCommand):
    help = (
        "Match parliament_api_id values to Person records using "
        "migration/parliament_api_filters.json."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            type=str,
            default=JSON_FILE,
            help=f"Path to parliament API filters JSON (default: {JSON_FILE})",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report matches without saving changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Update people who already have a parliament_api_id",
        )
        parser.add_argument(
            "--skip-linked",
            action="store_true",
            help="Skip people who already have a parliament_api_id",
        )

    def handle(self, *args, **options):
        json_path = options["json"]
        dry_run = options["dry_run"]
        force = options["force"]
        skip_linked = options["skip_linked"]

        if force and skip_linked:
            raise CommandError("Use either --force or --skip-linked, not both.")

        if not os.path.exists(json_path):
            raise CommandError(f"JSON file does not exist at {json_path}")

        with open(json_path, encoding="utf-8") as json_file:
            data = json.load(json_file)

        members_by_parliament, member_display_names = self.build_members_by_parliament(
            data.get("Members", {})
        )

        people = Person.objects.prefetch_related(
            Prefetch(
                "parliamentaryaffiliation_set",
                queryset=ParliamentaryAffiliation.objects.select_related("parliament"),
            )
        ).order_by("last_name", "first_name")

        matched_count = 0
        skipped_linked_count = 0
        unmatched_people = []
        ambiguous_people = []
        conflict_people = []
        assigned_member_ids = {}

        for person in people:
            if person.parliament_api_id and skip_linked:
                skipped_linked_count += 1
                continue

            if person.parliament_api_id and not force:
                skipped_linked_count += 1
                continue

            parliament_numbers = {
                affiliation.parliament.number
                for affiliation in person.parliamentaryaffiliation_set.all()
                if affiliation.parliament_id
            }

            member_id, ambiguous_member_ids = self.find_member_id_for_person(
                person,
                parliament_numbers,
                members_by_parliament,
            )

            if ambiguous_member_ids:
                ambiguous_people.append((person, ambiguous_member_ids))
                continue

            if not member_id:
                unmatched_people.append(person)
                continue

            if member_id in assigned_member_ids and assigned_member_ids[member_id] != person.id:
                conflict_people.append(
                    (person, assigned_member_ids[member_id], member_id)
                )
                continue

            if (
                person.parliament_api_id
                and person.parliament_api_id != member_id
                and not force
            ):
                conflict_people.append(
                    (person, person.parliament_api_id, member_id)
                )
                continue

            assigned_member_ids[member_id] = person.id
            matched_count += 1

            action = "Would set" if dry_run else "Set"
            match_label = (
                member_display_names.get(member_id, member_id)
                if dry_run
                else member_id
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"{action} {person.display_name} -> {match_label}"
                )
            )

            if not dry_run:
                person.parliament_api_id = member_id
                person.save(update_fields=["parliament_api_id"])

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Summary ==="))
        self.stdout.write(f"Matched: {matched_count}")
        self.stdout.write(f"Skipped (already linked): {skipped_linked_count}")
        self.stdout.write(f"Unmatched people: {len(unmatched_people)}")
        self.stdout.write(f"Ambiguous people: {len(ambiguous_people)}")
        self.stdout.write(f"Conflicts: {len(conflict_people)}")

        if unmatched_people:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Unmatched people:"))
            for person in unmatched_people:
                self.stdout.write(f"  - {person.display_name} (legacy_id={person.legacy_id})")

        if ambiguous_people:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Ambiguous people:"))
            for person, member_ids in ambiguous_people:
                self.stdout.write(
                    f"  - {person.display_name}: {', '.join(sorted(member_ids))}"
                )

        if conflict_people:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("Conflicts:"))
            for person, existing, member_id in conflict_people:
                self.stdout.write(
                    f"  - {person.display_name}: existing={existing}, new={member_id}"
                )

        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE("Dry run only; no changes were saved."))

    def build_members_by_parliament(self, members_data):
        members_by_parliament = {}
        member_display_names = {}

        for parliament_number, members in members_data.items():
            parsed_members = []
            for member in members:
                member_id = member.get("MemberId")
                display_name = member.get("DisplayName", "")
                last_name, first_name = parse_member_display_name(display_name)
                if not member_id or not last_name or not first_name:
                    continue
                member_display_names[member_id] = display_name
                parsed_members.append(
                    {
                        "member_id": member_id,
                        "display_name": display_name,
                        "last_name": last_name,
                        "first_name": first_name,
                    }
                )
            members_by_parliament[int(parliament_number)] = parsed_members

        return members_by_parliament, member_display_names

    def find_member_id_for_person(
        self,
        person,
        parliament_numbers,
        members_by_parliament,
    ):
        candidate_member_ids = self.find_matching_member_ids(
            person,
            parliament_numbers,
            members_by_parliament,
        )

        if len(candidate_member_ids) == 1:
            return next(iter(candidate_member_ids)), set()

        if len(candidate_member_ids) > 1:
            return None, candidate_member_ids

        candidate_member_ids = self.find_matching_member_ids(
            person,
            members_by_parliament.keys(),
            members_by_parliament,
        )

        if len(candidate_member_ids) == 1:
            return next(iter(candidate_member_ids)), set()

        if len(candidate_member_ids) > 1:
            return None, candidate_member_ids

        return None, set()

    def find_matching_member_ids(self, person, parliament_numbers, members_by_parliament):
        candidate_member_ids = set()

        for parliament_number in parliament_numbers:
            for member in members_by_parliament.get(parliament_number, []):
                if member_matches_person(
                    person, member["last_name"], member["first_name"]
                ):
                    candidate_member_ids.add(member["member_id"])

        return candidate_member_ids
