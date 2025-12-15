import csv
import os

from django.core.management.base import BaseCommand, CommandError
from wts_app.models import Person

class Command(BaseCommand):
    help = 'Loads people from migration/people.csv into the database.'

    def handle(self, *args, **options):
        csv_path = os.path.join('migration', 'people.csv')
        if not os.path.exists(csv_path):
            raise CommandError(f"CSV file does not exist at {csv_path}")

        count = 0
        with open(csv_path, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                legacy_id = int(row['legacy_id'])
                first_name = row['first_name']
                last_name = row['last_name']
                display_name = row['display_name']
                slug = row['slug']

                person, created = Person.objects.update_or_create(
                    legacy_id=legacy_id,
                    defaults={
                        'first_name': first_name,
                        'last_name': last_name,
                        'display_name': display_name,
                        'slug': slug,
                    }
                )
                count += 1
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Created: {display_name} (legacy_id={legacy_id})"))
                else:
                    self.stdout.write(f"Updated: {display_name} (legacy_id={legacy_id})")

        self.stdout.write(self.style.SUCCESS(f"Done. Processed {count} people."))

