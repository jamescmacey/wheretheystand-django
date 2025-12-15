import csv
import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from wts_app.models.people import PartyAffiliation, Person
from wts_app.models.parties import Party

class Command(BaseCommand):
    help = 'Loads party affiliations from migration/party_affiliations.csv into the database.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv',
            type=str,
            default='migration/party_affiliations.csv',
            help='Path to CSV file to use (default: migration/party_affiliations.csv)'
        )

    def handle(self, *args, **options):
        csv_path = options['csv']
        if not os.path.exists(csv_path):
            raise CommandError(f"CSV file does not exist at {csv_path}")

        created_count = 0
        updated_count = 0
        skipped_count = 0

        def parse_date(datestr):
            if not datestr:
                return None
            try:
                # Try ISO format YYYY-MM-DD
                return datetime.strptime(datestr.strip(), "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None

        with open(csv_path, mode='r', encoding='utf-8', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                # Get legacy IDs for person and party
                person_legacy_id = row.get('legacy_person_id', '').strip()
                party_legacy_id = row.get('legacy_party_id', '').strip()

                if not person_legacy_id:
                    self.stdout.write(self.style.WARNING("Skipping affiliation with empty legacy_person_id"))
                    skipped_count += 1
                    continue

                if not party_legacy_id:
                    self.stdout.write(self.style.WARNING("Skipping affiliation with empty legacy_party_id"))
                    skipped_count += 1
                    continue

                # Look up Person
                try:
                    person_legacy_id_int = int(person_legacy_id)
                    person = Person.objects.get(legacy_id=person_legacy_id_int)
                except (ValueError, Person.DoesNotExist) as e:
                    self.stdout.write(self.style.WARNING(
                        f"Could not find Person with legacy_id={person_legacy_id}, skipping."
                    ))
                    skipped_count += 1
                    continue

                # Look up Party
                try:
                    party_legacy_id_int = int(party_legacy_id)
                    party = Party.objects.get(legacy_id=party_legacy_id_int)
                except (ValueError, Party.DoesNotExist) as e:
                    self.stdout.write(self.style.WARNING(
                        f"Could not find Party with legacy_id={party_legacy_id}, skipping."
                    ))
                    skipped_count += 1
                    continue

                # Parse dates
                start_date_str = row.get('start_date', '').strip()
                end_date_str = row.get('end_date', '').strip()

                start_date = parse_date(start_date_str)
                if not start_date:
                    self.stdout.write(self.style.WARNING(
                        f"Skipping affiliation: invalid or missing start_date for Person {person.display_name}, Party {party.display_name}"
                    ))
                    skipped_count += 1
                    continue

                end_date = parse_date(end_date_str)

                # Use update_or_create with person, party, and start_date as lookup
                # (since CSV doesn't have legacy_id for affiliations)
                affiliation, created = PartyAffiliation.objects.update_or_create(
                    person=person,
                    party=party,
                    start_date=start_date,
                    defaults={
                        'end_date': end_date,
                    }
                )

                if created:
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"Created: {person.display_name} -> {party.display_name} ({start_date} - {end_date or 'ongoing'})"
                    ))
                else:
                    updated_count += 1
                    self.stdout.write(
                        f"Updated: {person.display_name} -> {party.display_name} ({start_date} - {end_date or 'ongoing'})"
                    )

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created {created_count}, Updated {updated_count}, Skipped {skipped_count} party affiliations."
        ))

