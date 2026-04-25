import csv
import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from wts_app.models.parties import Party

class Command(BaseCommand):
    help = 'Loads parties from migration/parties.csv into the database.'

    def handle(self, *args, **options):
        csv_path = os.path.join('migration', 'parties.csv')
        if not os.path.exists(csv_path):
            raise CommandError(f"CSV file does not exist at {csv_path}")

        count = 0
        created_count = 0
        updated_count = 0

        def parse_date(datestr):
            if not datestr:
                return None
            try:
                # Try ISO format YYYY-MM-DD
                return datetime.strptime(datestr, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None

        def parse_boolean(value):
            """Convert CSV 1/0 or empty string to boolean."""
            if not value:
                return False
            return str(value).strip() in ('1', 'true', 'True', 'TRUE')

        def parse_colour(colour_str):
            """Parse colour, adding # if not present."""
            if not colour_str:
                return None
            colour_str = colour_str.strip()
            if colour_str and not colour_str.startswith('#'):
                return f"#{colour_str}"
            return colour_str

        with open(csv_path, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                legacy_id = row.get('legacy_id', '').strip()
                if not legacy_id:
                    self.stdout.write(self.style.WARNING("Skipping party with empty legacy_id"))
                    continue
                try:
                    legacy_id_int = int(legacy_id)
                except ValueError:
                    self.stdout.write(self.style.WARNING(f"Skipping party with invalid legacy_id '{legacy_id}'"))
                    continue

                legal_name = row.get('legal_name', '').strip()
                display_name = row.get('display_name', '').strip()
                short_name = row.get('short_name', '').strip()
                abbreviation = row.get('abbreviation', '').strip()
                
                if not legal_name or not display_name or not abbreviation:
                    self.stdout.write(self.style.WARNING(f"Skipping party with missing required fields (legacy_id={legacy_id})"))
                    continue

                registered_date = parse_date(row.get('registered_date', '').strip())
                deregistered_date = parse_date(row.get('deregistered_date', '').strip())
                slug = row.get('slug', '').strip() or None
                color_str = row.get('colour_without_hash', '').strip()
                colour = parse_colour(color_str)
                is_registered = parse_boolean(row.get('is_registered', '').strip())
                registration_dates_precise = parse_boolean(row.get('registration_dates_precise', '').strip())
                party_leader_role = row.get('party_leader_role', '').strip() or 'Leader'
                party_leader_role_plural = row.get('party_leader_role_plural', '').strip() or 'Leaders'

                party, created = Party.objects.update_or_create(
                    legacy_id=legacy_id_int,
                    defaults={
                        'legal_name': legal_name,
                        'display_name': display_name,
                        'short_name': short_name,
                        'abbreviation': abbreviation,
                        'registered_date': registered_date,
                        'deregistered_date': deregistered_date,
                        'slug': slug,
                        'colour': colour,
                        'is_registered': is_registered,
                        'registration_dates_precise': registration_dates_precise,
                        'party_leader_role': party_leader_role,
                        'party_leader_role_plural': party_leader_role_plural,
                    }
                )
                count += 1
                if created:
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(f"Created: {display_name} (legacy_id={legacy_id})"))
                else:
                    updated_count += 1
                    self.stdout.write(f"Updated: {display_name} (legacy_id={legacy_id})")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Processed {count} parties (Created: {created_count}, Updated: {updated_count})."
        ))
