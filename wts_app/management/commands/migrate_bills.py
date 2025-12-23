import csv
import os
import json
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from wts_app.models import Bill, Parliament, Person


class Command(BaseCommand):
    help = 'Loads bills from migration/bills.csv and people responsible from migration/bills_people_responsible.csv into the database.'

    # Mapping for bill types
    BILL_TYPE_MAP = {
        'mem': 'members',
        'gov': 'government',
        'pri': 'private',
        'loc': 'local',
    }

    # Mapping for voting methods
    VOTING_METHODS_MAP = {
        'per': 'personal',
        'par': 'party',
        'mix': 'mixed',
        'unk': 'unknown',
    }

    # Mapping for statuses
    STATUS_MAP = {
        'unk': 'unknown',
        'inp': 'in_progress',
        'def': 'defeated',
        'wit': 'withdrawn',
        'pas': 'passed',
        'ena': 'enacted',
        'div': 'divided',
        'lap': 'lapsed',
        'unx': 'unknown_not_current',
        # Note: 'discharged' doesn't appear in CSV but is in model
    }

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


    def get_date_fields(self, row):
        """Extract all date fields from a row."""
        date_fields = [
            'introduction_date',
            'first_reading_date',
            'second_reading_date',
            'third_reading_date',
            'royal_assent_date',
            'whole_house_date',
            'withdrawn_date',
            'defeated_date'
        ]
        dates = []
        for field in date_fields:
            date_val = self.parse_date(row.get(field, ''))
            if date_val:
                dates.append(date_val)
        return dates

    def find_parliaments_for_bill(self, dates):
        """Find which parliaments a bill belongs to based on date range."""
        if not dates:
            return []
        
        earliest_date = min(dates)
        latest_date = max(dates)
        
        # Find parliaments that overlap with the bill's date range
        # A parliament overlaps if:
        # - parliament.start_date <= latest_date AND
        # - (parliament.end_date is None OR parliament.end_date >= earliest_date)
        parliaments = Parliament.objects.filter(
            start_date__lte=latest_date
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=earliest_date)
        )
        
        return list(parliaments)

    def handle(self, *args, **options):

        Bill.objects.all().delete()
        dry_run = options['dry_run']
        
        bills_csv_path = os.path.join('migration', 'bills.csv')
        people_responsible_csv_path = os.path.join('migration', 'bills_people_responsible.csv')
        
        if not os.path.exists(bills_csv_path):
            raise CommandError(f"CSV file does not exist at {bills_csv_path}")
        if not os.path.exists(people_responsible_csv_path):
            raise CommandError(f"CSV file does not exist at {people_responsible_csv_path}")

        # Step 1: Load bills
        bills_created = 0
        bills_updated = 0
        bills_skipped = 0
        
        # First pass: collect all bill data
        bills_data = []
        parliament_assignments = {}  # legacy_id -> list of parliament objects
        
        self.stdout.write("Reading bills from CSV...")
        with open(bills_csv_path, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            for row in reader:
                    # Skip columns with "ignore" in their name
                    # Filter out ignore columns
                    filtered_row = {k: v for k, v in row.items() if 'ignore' not in k.lower()}
                    
                    legacy_id = int(filtered_row['legacy_id'])
                    
                    # Map bill_type
                    bill_type_code = filtered_row.get('bill_type', '').strip()
                    bill_type = self.BILL_TYPE_MAP.get(bill_type_code) if bill_type_code else None
                    
                    # Map voting_methods
                    voting_methods_code = filtered_row.get('voting_methods', '').strip()
                    voting_methods = self.VOTING_METHODS_MAP.get(voting_methods_code, 'unknown')
                    
                    # Map status
                    status_code = filtered_row.get('status', '').strip()
                    status = self.STATUS_MAP.get(status_code, 'unknown')
                    
                    # Parse dates
                    introduction_date = self.parse_date(filtered_row.get('introduction_date', ''))
                    first_reading_date = self.parse_date(filtered_row.get('first_reading_date', ''))
                    submissions_due_date = self.parse_date(filtered_row.get('submissions_due_date', ''))
                    second_reading_date = self.parse_date(filtered_row.get('second_reading_date', ''))
                    third_reading_date = self.parse_date(filtered_row.get('third_reading_date', ''))
                    royal_assent_date = self.parse_date(filtered_row.get('royal_assent_date', ''))
                    report_back_date = self.parse_date(filtered_row.get('report_back_date', ''))
                    whole_house_date = self.parse_date(filtered_row.get('whole_house_date', ''))
                    withdrawn_date = self.parse_date(filtered_row.get('withdrawn_date', ''))
                    defeated_date = self.parse_date(filtered_row.get('defeated_date', ''))
                    lapsed_date = self.parse_date(filtered_row.get('lapsed_date', ''))
                    
                    # Parse defeated_reading
                    defeated_reading = None
                    if filtered_row.get('defeated_reading', '').strip():
                        try:
                            defeated_reading = int(filtered_row['defeated_reading'])
                            if defeated_reading < 1 or defeated_reading > 3:
                                defeated_reading = None
                        except (ValueError, TypeError):
                            defeated_reading = None
                    
                    # Parse retrieved_at (assumed to be in UTC)
                    retrieved_at = None
                    if filtered_row.get('retrieved_at', '').strip():
                        retrieved_at_str = filtered_row['retrieved_at'].strip()
                        try:
                            # Try common datetime formats
                            for fmt in ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]:
                                try:
                                    naive_dt = datetime.strptime(retrieved_at_str, fmt)
                                    # Make timezone-aware by adding UTC timezone
                                    retrieved_at = timezone.make_aware(naive_dt, timezone.UTC)
                                    break
                                except ValueError:
                                    continue
                        except (ValueError, TypeError):
                            pass
                    
                    # Parse act_number and act_year
                    act_number = None
                    if filtered_row.get('act_number', '').strip():
                        try:
                            act_number = int(filtered_row['act_number'])
                        except (ValueError, TypeError):
                            act_number = None
                    
                    act_year = None
                    if filtered_row.get('act_year', '').strip():
                        try:
                            act_year = int(filtered_row['act_year'])
                        except (ValueError, TypeError):
                            act_year = None
                    
                    # Parse boolean fields
                    is_divided = filtered_row.get('is_divided', '').strip() == '1'
                    extended_sittings_used = filtered_row.get('extended_sittings_used', '').strip() == '1'
                    urgency_used = filtered_row.get('urgency_used', '').strip() == '1'
                    flag_scraped_under_v2 = filtered_row.get('flag_scraped_under_v2', '').strip() == '1'
                    flag_enacted_but_missing_assent_number = filtered_row.get('flag_enacted_but_missing_assent_number', '').strip() == '1'
                    
                    # Parse original_api_response JSON
                    original_api_response = None
                    if filtered_row.get('original_api_response', '').strip():
                        try:
                            original_api_response = json.loads(filtered_row['original_api_response'])
                        except (json.JSONDecodeError, TypeError):
                            original_api_response = None
                    
                    # Get all dates to determine parliaments
                    all_dates = self.get_date_fields(filtered_row)
                    
                    if dry_run:
                        self.stdout.write(f"Would process bill: {filtered_row['name']} (legacy_id={legacy_id})")
                        if all_dates:
                            self.stdout.write(f"  Date range: {min(all_dates)} to {max(all_dates)}")
                        bills_skipped += 1
                        continue
                    
                    # Find parliaments (store for later assignment)
                    parliaments = self.find_parliaments_for_bill(all_dates) if all_dates else []
                    
                    # Store bill data for bulk processing
                    bills_data.append({
                        'legacy_id': legacy_id,
                        'name': filtered_row['name'],
                        'description': filtered_row.get('description', ''),
                        'retrieved_at': retrieved_at,
                        'parliament_document_id': filtered_row.get('parliament_document_id', ''),
                        'parliament_api_id': filtered_row.get('parliament_api_id', ''),
                        'parliament_api_status': filtered_row.get('parliament_api_status', ''),
                        'ref': filtered_row.get('ref', ''),
                        'bill_type': bill_type,
                        'voting_methods': voting_methods,
                        'status': status,
                        'select_committee_name': filtered_row.get('select_committee_name', ''),
                        'select_committee_status': filtered_row.get('select_committee_status', ''),
                        'introduction_date': introduction_date,
                        'first_reading_date': first_reading_date,
                        'submissions_due_date': submissions_due_date,
                        'report_back_date': report_back_date,
                        'second_reading_date': second_reading_date,
                        'whole_house_date': whole_house_date,
                        'third_reading_date': third_reading_date,
                        'royal_assent_date': royal_assent_date,
                        'withdrawn_date': withdrawn_date,
                        'defeated_date': defeated_date,
                        'defeated_reading': defeated_reading,
                        'lapsed_date': lapsed_date,
                        'act_name': filtered_row.get('act_name', ''),
                        'act_number': act_number,
                        'act_year': act_year,
                        'legislation_url': filtered_row.get('legislation_url', ''),
                        'original_api_response': original_api_response,
                        'is_divided': is_divided,
                        'extended_sittings_used': extended_sittings_used,
                        'urgency_used': urgency_used,
                        'flag_scraped_under_v2': flag_scraped_under_v2,
                        'flag_enacted_but_missing_assent_number': flag_enacted_but_missing_assent_number,
                    })
                    parliament_assignments[legacy_id] = parliaments
        
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"\nWould process {len(bills_data)} bills"))
            return
        
        # Bulk process bills
        self.stdout.write(f"Processing {len(bills_data)} bills in bulk...")
        
        # Get existing bills in one query
        legacy_ids = [bd['legacy_id'] for bd in bills_data]
        existing_bills = {bill.legacy_id: bill for bill in Bill.objects.filter(legacy_id__in=legacy_ids)}
        
        bills_to_create = []
        bills_to_update = []
        
        for bill_data in bills_data:
            legacy_id = bill_data.pop('legacy_id')
            if legacy_id in existing_bills:
                # Update existing bill
                bill = existing_bills[legacy_id]
                for key, value in bill_data.items():
                    setattr(bill, key, value)
                bills_to_update.append(bill)
            else:
                # Create new bill
                bill = Bill(legacy_id=legacy_id, **bill_data)
                bills_to_create.append(bill)
        
        # Bulk create and update in transaction
        with transaction.atomic():
            if bills_to_create:
                Bill.objects.bulk_create(bills_to_create, batch_size=500)
                bills_created = len(bills_to_create)
                self.stdout.write(self.style.SUCCESS(f"Created {bills_created} bills"))
            
            if bills_to_update:
                Bill.objects.bulk_update(
                    bills_to_update,
                    fields=[
                        'name', 'description', 'retrieved_at', 'parliament_document_id',
                        'parliament_api_id', 'parliament_api_status', 'ref', 'bill_type',
                        'voting_methods', 'status', 'select_committee_name', 'select_committee_status',
                        'introduction_date', 'first_reading_date', 'submissions_due_date', 'report_back_date',
                        'second_reading_date', 'whole_house_date', 'third_reading_date', 'royal_assent_date',
                        'withdrawn_date', 'defeated_date', 'defeated_reading', 'lapsed_date',
                        'act_name', 'act_number', 'act_year', 'legislation_url', 'original_api_response',
                        'is_divided', 'extended_sittings_used', 'urgency_used', 'flag_scraped_under_v2',
                        'flag_enacted_but_missing_assent_number'
                    ],
                    batch_size=500
                )
                bills_updated = len(bills_to_update)
                self.stdout.write(f"Updated {bills_updated} bills")
        
        # Now handle parliament assignments (ManyToMany)
        self.stdout.write("Assigning parliaments to bills...")
        with transaction.atomic():
            # Get all bills again to ensure we have the created ones
            all_bills = {bill.legacy_id: bill for bill in Bill.objects.filter(legacy_id__in=legacy_ids)}
            
            for legacy_id, parliaments in parliament_assignments.items():
                if parliaments and legacy_id in all_bills:
                    all_bills[legacy_id].parliaments.set(parliaments)
        
        self.stdout.write(self.style.SUCCESS(f"\nBills: Created {bills_created}, Updated {bills_updated}"))
        
        # Step 2: Add people responsible
        if dry_run:
            self.stdout.write(self.style.WARNING("\nSkipping people responsible (dry run)"))
            return
        
        people_responsible_count = 0
        people_responsible_skipped = 0
        
        # Collect people responsible relationships
        self.stdout.write("Reading people responsible from CSV...")
        relationships = []
        with open(people_responsible_csv_path, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                relationships.append({
                    'bill_id': int(row['bill_id']),
                    'politician_id': int(row['politician_id']),
                })
        
        # Get all bills and people in bulk
        bill_ids = list(set(r['bill_id'] for r in relationships))
        person_ids = list(set(r['politician_id'] for r in relationships))
        
        bills_dict = {bill.legacy_id: bill for bill in Bill.objects.filter(legacy_id__in=bill_ids)}
        people_dict = {person.legacy_id: person for person in Person.objects.filter(legacy_id__in=person_ids)}
        
        # Get the through model for the ManyToMany relationship
        through_model = Bill.people_responsible.through
        
        # Prepare bulk relationships
        relationships_to_create = []
        for rel in relationships:
            bill_id = rel['bill_id']
            politician_id = rel['politician_id']
            
            if bill_id not in bills_dict:
                people_responsible_skipped += 1
                continue
            
            if politician_id not in people_dict:
                people_responsible_skipped += 1
                continue
            
            relationships_to_create.append(
                through_model(bill=bills_dict[bill_id], person=people_dict[politician_id])
            )
            people_responsible_count += 1
        
        # Bulk create relationships
        self.stdout.write(f"Creating {people_responsible_count} people responsible relationships...")
        with transaction.atomic():
            # Clear existing relationships first (optional, remove if you want to keep existing)
            through_model.objects.filter(bill__legacy_id__in=bill_ids).delete()
            
            # Bulk create new relationships
            if relationships_to_create:
                through_model.objects.bulk_create(relationships_to_create, batch_size=500, ignore_conflicts=True)
        
        self.stdout.write(self.style.SUCCESS(f"\nPeople responsible: Added {people_responsible_count} relationships, Skipped {people_responsible_skipped}"))
        self.stdout.write(self.style.SUCCESS(f"\nDone. Processed {bills_created + bills_updated} bills and {people_responsible_count} people responsible relationships."))

