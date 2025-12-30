import csv
import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from wts_app.models import Bill


class Command(BaseCommand):
    help = 'Updates last_activity_date for bills from migration/bills.csv, matching by legacy_id.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without making any changes',
        )

    def parse_date(self, datestr):
        """Parse date string, handling various formats."""
        if not datestr or datestr.strip() == '':
            return None
        try:
            # Try ISO format (YYYY-MM-DD)
            if '/' not in datestr:
                return datetime.strptime(datestr.strip(), "%Y-%m-%d").date()
            # Try dd/mm/yyyy
            return datetime.strptime(datestr.strip(), "%d/%m/%Y").date()
        except (ValueError, TypeError):
            return None

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        bills_csv_path = os.path.join('migration', 'bills.csv')
        
        if not os.path.exists(bills_csv_path):
            raise CommandError(f"CSV file does not exist at {bills_csv_path}")

        updated_count = 0
        skipped_count = 0
        not_found_count = 0
        
        self.stdout.write("Reading bills from CSV...")
        
        # First pass: collect all updates
        updates = {}
        with open(bills_csv_path, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            for row in reader:
                # Filter out ignore columns
                filtered_row = {k: v for k, v in row.items() if 'ignore' not in k.lower()}
                
                legacy_id_str = filtered_row.get('legacy_id', '').strip()
                if not legacy_id_str:
                    skipped_count += 1
                    continue
                
                try:
                    legacy_id = int(legacy_id_str)
                except (ValueError, TypeError):
                    skipped_count += 1
                    continue
                
                last_activity_date_str = filtered_row.get('last_activity_date', '').strip()
                if not last_activity_date_str:
                    skipped_count += 1
                    continue
                
                last_activity_date = self.parse_date(last_activity_date_str)
                if not last_activity_date:
                    skipped_count += 1
                    continue
                
                updates[legacy_id] = last_activity_date
        
        if dry_run:
            self.stdout.write(f"Would update {len(updates)} bills with last_activity_date")
            # Show a few examples
            for i, (legacy_id, date) in enumerate(list(updates.items())[:5]):
                self.stdout.write(f"  legacy_id={legacy_id}: {date}")
            if len(updates) > 5:
                self.stdout.write(f"  ... and {len(updates) - 5} more")
            return
        
        # Get all bills that need updating
        legacy_ids = list(updates.keys())
        bills_dict = {bill.legacy_id: bill for bill in Bill.objects.filter(legacy_id__in=legacy_ids)}
        
        # Prepare bills for bulk update
        bills_to_update = []
        for legacy_id, last_activity_date in updates.items():
            if legacy_id not in bills_dict:
                not_found_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Bill with legacy_id={legacy_id} not found in database"
                    )
                )
                continue
            
            bill = bills_dict[legacy_id]
            bill.last_activity_date = last_activity_date
            bills_to_update.append(bill)
        
        # Bulk update in transaction
        if bills_to_update:
            self.stdout.write(f"Updating {len(bills_to_update)} bills...")
            with transaction.atomic():
                Bill.objects.bulk_update(
                    bills_to_update,
                    fields=['last_activity_date'],
                    batch_size=500
                )
                updated_count = len(bills_to_update)
        
        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Updated {updated_count} bills, "
            f"skipped {skipped_count} rows (empty/invalid data), "
            f"not found {not_found_count} bills"
        ))

