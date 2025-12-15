import csv
import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from wts_app.models import Electorate

class Command(BaseCommand):
    help = 'Loads electorates from migration/electorates.csv into the database.'

    def handle(self, *args, **options):
        csv_path = os.path.join('migration', 'electorates.csv')
        if not os.path.exists(csv_path):
            raise CommandError(f"CSV file does not exist at {csv_path}")

        electorates = []
        legacy_id_to_instance = {}

        def parse_date(datestr):
            if not datestr:
                return None
            try:
                # CSV format is dd/mm/yyyy
                return datetime.strptime(datestr, "%d/%m/%Y").date()
            except ValueError:
                return None

        with open(csv_path, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                legacy_id = int(row['legacy_id'])
                name = row['name']
                electorate_type = row['type']
                status = row['status']
                region = row['region']
                slug = row['slug']
                replaced_legacy_id = row['replaced_legacy_id']
                valid_from = parse_date(row['valid_from'])
                valid_to = parse_date(row['valid_to'])

                electorate, created = Electorate.objects.update_or_create(
                    legacy_id=legacy_id,
                    defaults={
                        'name': name,
                        'electorate_type': electorate_type,
                        'status': status,
                        'region': region,
                        'slug': slug,
                        'valid_from': valid_from,
                        'valid_to': valid_to,
                        # don't set replaced for now
                    }
                )
                legacy_id_to_instance[legacy_id] = electorate

                electorates.append({
                    'instance': electorate,
                    'created': created,
                    'display_name': name,
                    'legacy_id': legacy_id,
                    'replaced_legacy_id': replaced_legacy_id,
                })

        # Second pass: set the replaced field (FK), if any
        for entry in electorates:
            replaced_legacy_id = entry['replaced_legacy_id']
            electorate = entry['instance']
            if replaced_legacy_id:
                try:
                    replaced_electorate = legacy_id_to_instance.get(int(replaced_legacy_id))
                    if replaced_electorate:
                        electorate.replaced = replaced_electorate
                        electorate.save(update_fields=['replaced'])
                except (ValueError, KeyError):
                    self.stdout.write(
                        self.style.WARNING(
                            f"Could not resolve replaced_legacy_id {replaced_legacy_id} for electorate {entry['display_name']} (legacy_id={entry['legacy_id']})"
                        )
                    )
        
        # Output results
        for entry in electorates:
            if entry['created']:
                self.stdout.write(self.style.SUCCESS(f"Created: {entry['display_name']} (legacy_id={entry['legacy_id']})"))
            else:
                self.stdout.write(f"Updated: {entry['display_name']} (legacy_id={entry['legacy_id']})")

        self.stdout.write(self.style.SUCCESS(f"Done. Processed {len(electorates)} electorates."))


