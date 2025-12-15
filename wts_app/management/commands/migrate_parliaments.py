import csv
import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from wts_app.models import Parliament

class Command(BaseCommand):
    help = 'Loads parliaments from migration/parliaments.csv into the database.'

    def handle(self, *args, **options):
        csv_path = os.path.join('migration', 'parliaments.csv')
        if not os.path.exists(csv_path):
            raise CommandError(f"CSV file does not exist at {csv_path}")

        count = 0

        def parse_date(datestr):
            if not datestr:
                return None
            try:
                # Try ISO or dd/mm/yyyy
                if '/' in datestr:
                    return datetime.strptime(datestr, "%d/%m/%Y").date()
                return datetime.strptime(datestr, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None

        with open(csv_path, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                legacy_id = int(row['legacy_id'])
                number = int(row['number'])
                start_date = parse_date(row['start_date'])
                end_date = parse_date(row['end_date'])

                parliament, created = Parliament.objects.update_or_create(
                    legacy_id=legacy_id,
                    defaults={
                        'number': number,
                        'start_date': start_date,
                        'end_date': end_date,
                        # election field left unset for now
                    }
                )
                count += 1
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Created: Parliament {number} (legacy_id={legacy_id})"))
                else:
                    self.stdout.write(f"Updated: Parliament {number} (legacy_id={legacy_id})")

        self.stdout.write(self.style.SUCCESS(f"Done. Processed {count} parliaments."))
