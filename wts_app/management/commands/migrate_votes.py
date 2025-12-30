import csv
import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from wts_app.models import Vote, VoteRecord, Bill, Person, Party


class Command(BaseCommand):
    help = 'Loads votes from migration/votes.csv and vote records from migration/vote_records.csv into the database.'

    # Mapping for vote types
    VOTE_TYPE_MAP = {
        'party': 'party',
        'personal': 'personal',
        'voice': 'voice',
    }

    # Mapping for positions
    POSITION_MAP = {
        'y': 'aye',
        'n': 'no',
        'a': 'abstention',
        'x': 'absent',
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

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        votes_csv_path = os.path.join('migration', 'votes.csv')
        vote_records_csv_path = os.path.join('migration', 'vote_records.csv')
        
        if not os.path.exists(votes_csv_path):
            raise CommandError(f"CSV file does not exist at {votes_csv_path}")
        if not os.path.exists(vote_records_csv_path):
            raise CommandError(f"CSV file does not exist at {vote_records_csv_path}")

        # Step 1: Load votes
        votes_created = 0
        votes_updated = 0
        votes_skipped = 0
        
        # First pass: collect all vote data
        votes_data = []
        
        self.stdout.write("Reading votes from CSV...")
        with open(votes_csv_path, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            for row in reader:
                # Skip columns with "ignore" in their name
                filtered_row = {k: v for k, v in row.items() if 'ignore' not in k.lower()}
                
                legacy_id = int(filtered_row['legacy_id'])
                legacy_bill_id = int(filtered_row.get('legacy_bill_id', '').strip()) if filtered_row.get('legacy_bill_id', '').strip() else None
                
                if not legacy_bill_id:
                    votes_skipped += 1
                    self.stdout.write(self.style.WARNING(f"Vote {legacy_id} has no legacy_bill_id, skipping"))
                    continue
                
                # Parse date
                vote_date = self.parse_date(filtered_row.get('vote_date', ''))
                if not vote_date:
                    votes_skipped += 1
                    self.stdout.write(self.style.WARNING(f"Vote {legacy_id} has no valid vote_date, skipping"))
                    continue
                
                # Parse reading
                reading = None
                if filtered_row.get('reading', '').strip():
                    try:
                        reading = int(filtered_row['reading'])
                        if reading < 1 or reading > 3:
                            reading = None
                    except (ValueError, TypeError):
                        reading = None
                
                if not reading:
                    votes_skipped += 1
                    self.stdout.write(self.style.WARNING(f"Vote {legacy_id} has no valid reading, skipping"))
                    continue
                
                # Parse counts
                ayes = int(filtered_row.get('ayes', 0) or 0)
                noes = int(filtered_row.get('noes', 0) or 0)
                abstentions = int(filtered_row.get('abstentions', 0) or 0)
                absentees = int(filtered_row.get('absent', 0) or 0)
                
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
                
                # Parse boolean fields
                motion_agreed = filtered_row.get('motion_agreed', '').strip() == '1'
                contains_split_party_votes = filtered_row.get('contains_split_party_votes', '').strip() == '1'
                
                # Map vote_type
                vote_type_code = filtered_row.get('type', '').strip()
                vote_type = self.VOTE_TYPE_MAP.get(vote_type_code) if vote_type_code else None
                
                # Store vote data for bulk processing
                votes_data.append({
                    'legacy_id': legacy_id,
                    'legacy_bill_id': legacy_bill_id,
                    'parliament_document_id': filtered_row.get('parliament_document_id', ''),
                    'retrieved_at': retrieved_at,
                    'date': vote_date,
                    'reading': reading,
                    'ayes': ayes,
                    'noes': noes,
                    'abstentions': abstentions,
                    'absentees': absentees,
                    'motion_agreed': motion_agreed,
                    'outcome_text': filtered_row.get('outcome', ''),
                    'reason_text': filtered_row.get('reason', ''),
                    'hansard_status': filtered_row.get('hansard_status', ''),
                    'vote_type': vote_type,
                    'contains_split_party_votes': contains_split_party_votes,
                    'import_method': 'parse'
                })
        
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"\nWould process {len(votes_data)} votes"))
            return
        
        # Bulk process votes
        self.stdout.write(f"Processing {len(votes_data)} votes in bulk...")
        
        # Get all bills by legacy_id in one query
        legacy_bill_ids = list(set(vd['legacy_bill_id'] for vd in votes_data))
        bills_dict = {bill.legacy_id: bill for bill in Bill.objects.filter(legacy_id__in=legacy_bill_ids)}
        
        votes_to_create = []
        votes_to_update = []
        
        # Get existing votes by legacy_id
        legacy_ids = [vd['legacy_id'] for vd in votes_data]
        existing_votes = {vote.legacy_id: vote for vote in Vote.objects.filter(legacy_id__in=legacy_ids)}
        
        for vote_data in votes_data:
            legacy_id = vote_data.pop('legacy_id')
            legacy_bill_id = vote_data.pop('legacy_bill_id')
            
            # Get bill
            if legacy_bill_id not in bills_dict:
                votes_skipped += 1
                self.stdout.write(self.style.WARNING(f"Bill with legacy_id={legacy_bill_id} not found for vote {legacy_id}, skipping"))
                continue
            
            bill = bills_dict[legacy_bill_id]
            vote_data['bill'] = bill
            
            if legacy_id in existing_votes:
                # Update existing vote
                vote = existing_votes[legacy_id]
                for key, value in vote_data.items():
                    setattr(vote, key, value)
                votes_to_update.append(vote)
            else:
                # Create new vote
                vote = Vote(legacy_id=legacy_id, **vote_data)
                votes_to_create.append(vote)
        
        # Bulk create and update in transaction
        with transaction.atomic():
            if votes_to_create:
                Vote.objects.bulk_create(votes_to_create, batch_size=500)
                votes_created = len(votes_to_create)
                self.stdout.write(self.style.SUCCESS(f"Created {votes_created} votes"))
            
            if votes_to_update:
                Vote.objects.bulk_update(
                    votes_to_update,
                    fields=[
                        'parliament_document_id', 'retrieved_at', 'bill', 'date', 'reading',
                        'ayes', 'noes', 'abstentions', 'absentees', 'motion_agreed',
                        'outcome_text', 'reason_text', 'hansard_status', 'vote_type',
                        'contains_split_party_votes', 'import_method'
                    ],
                    batch_size=500
                )
                votes_updated = len(votes_to_update)
                self.stdout.write(f"Updated {votes_updated} votes")
        
        self.stdout.write(self.style.SUCCESS(f"\nVotes: Created {votes_created}, Updated {votes_updated}, Skipped {votes_skipped}"))
        
        # Step 2: Load vote records
        if dry_run:
            self.stdout.write(self.style.WARNING("\nSkipping vote records (dry run)"))
            return
        
        vote_records_created = 0
        vote_records_updated = 0
        vote_records_skipped = 0
        
        # Collect vote record data
        self.stdout.write("Reading vote records from CSV...")
        vote_records_data = []
        
        with open(vote_records_csv_path, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            for row in reader:
                legacy_id = int(row['legacy_id'])
                legacy_vote_id = int(row.get('legacy_vote_id', '').strip()) if row.get('legacy_vote_id', '').strip() else None
                
                if not legacy_vote_id:
                    vote_records_skipped += 1
                    self.stdout.write(self.style.WARNING(f"Vote record {legacy_id} has no valid legacy_vote_id, skipping"))
                    continue
                
                # Parse position
                position_code = row.get('position', '').strip()
                position = self.POSITION_MAP.get(position_code)
                if not position:
                    vote_records_skipped += 1
                    self.stdout.write(self.style.WARNING(f"Vote record {legacy_id} has no valid position, skipping"))
                    continue
                
                # Parse contribution
                contribution = None
                if row.get('contribution', '').strip():
                    try:
                        contribution = int(row['contribution'])
                    except (ValueError, TypeError):
                        contribution = None
                
                # Parse boolean fields
                is_proxy_vote = row.get('is_proxy_vote', '').strip() == '1'
                is_split_party_vote = row.get('is_split_party_vote', '').strip() == '1'
                
                # Get legacy_party_id and legacy_person_id (one or the other, not both)
                legacy_party_id = int(row.get('legacy_party_id', '').strip()) if row.get('legacy_party_id', '').strip() else None
                legacy_person_id = int(row.get('legacy_person_id', '').strip()) if row.get('legacy_person_id', '').strip() else None
                
                vote_records_data.append({
                    'legacy_id': legacy_id,
                    'legacy_vote_id': legacy_vote_id,
                    'legacy_party_id': legacy_party_id,
                    'legacy_person_id': legacy_person_id,
                    'position': position,
                    'contribution': contribution,
                    'is_proxy_vote': is_proxy_vote,
                    'is_split_party_vote': is_split_party_vote,
                })
        
        # Bulk process vote records
        self.stdout.write(f"Processing {len(vote_records_data)} vote records in bulk...")
        
        # Get all votes, parties, and people by legacy_id
        legacy_vote_ids = list(set(vrd['legacy_vote_id'] for vrd in vote_records_data))
        votes_dict = {vote.legacy_id: vote for vote in Vote.objects.filter(legacy_id__in=legacy_vote_ids)}
        
        legacy_party_ids = list(set(vrd['legacy_party_id'] for vrd in vote_records_data if vrd['legacy_party_id']))
        parties_dict = {party.legacy_id: party for party in Party.objects.filter(legacy_id__in=legacy_party_ids)} if legacy_party_ids else {}
        
        legacy_person_ids = list(set(vrd['legacy_person_id'] for vrd in vote_records_data if vrd['legacy_person_id']))
        people_dict = {person.legacy_id: person for person in Person.objects.filter(legacy_id__in=legacy_person_ids)} if legacy_person_ids else {}
        
        # Get existing vote records
        vote_record_legacy_ids = [vrd['legacy_id'] for vrd in vote_records_data]
        existing_vote_records = {vr.legacy_id: vr for vr in VoteRecord.objects.filter(legacy_id__in=vote_record_legacy_ids)}
        
        vote_records_to_create = []
        vote_records_to_update = []
        
        for vr_data in vote_records_data:
            legacy_id = vr_data.pop('legacy_id')
            legacy_vote_id = vr_data.pop('legacy_vote_id')
            legacy_party_id = vr_data.pop('legacy_party_id')
            legacy_person_id = vr_data.pop('legacy_person_id')
            
            # Get vote
            if legacy_vote_id not in votes_dict:
                vote_records_skipped += 1
                self.stdout.write(self.style.WARNING(f"Vote record {legacy_id} has no valid legacy_vote_id, skipping"))
                continue
            
            vote = votes_dict[legacy_vote_id]
            vr_data['vote'] = vote
            
            # Get party or person
            if legacy_party_id:
                if legacy_party_id not in parties_dict:
                    vote_records_skipped += 1
                    self.stdout.write(self.style.WARNING(f"Vote record {legacy_id} has no valid legacy_party_id, skipping"))
                    continue
                vr_data['party'] = parties_dict[legacy_party_id]
                vr_data['person'] = None
            if legacy_person_id:
                if legacy_person_id not in people_dict:
                    vote_records_skipped += 1
                    self.stdout.write(self.style.WARNING(f"Vote record {legacy_id} has no valid legacy_person_id, skipping"))
                    continue
                vr_data['person'] = people_dict[legacy_person_id]
            
            if legacy_id in existing_vote_records:
                # Update existing vote record
                vote_record = existing_vote_records[legacy_id]
                for key, value in vr_data.items():
                    setattr(vote_record, key, value)
                vote_records_to_update.append(vote_record)
            else:
                # Create new vote record
                vote_record = VoteRecord(legacy_id=legacy_id, **vr_data)
                vote_records_to_create.append(vote_record)
        
        # Bulk create and update in transaction
        with transaction.atomic():
            if vote_records_to_create:
                VoteRecord.objects.bulk_create(vote_records_to_create, batch_size=500)
                vote_records_created = len(vote_records_to_create)
                self.stdout.write(self.style.SUCCESS(f"Created {vote_records_created} vote records"))
            
            if vote_records_to_update:
                VoteRecord.objects.bulk_update(
                    vote_records_to_update,
                    fields=[
                        'vote', 'person', 'party', 'is_proxy_vote', 'is_split_party_vote',
                        'position', 'contribution'
                    ],
                    batch_size=500
                )
                vote_records_updated = len(vote_records_to_update)
                self.stdout.write(f"Updated {vote_records_updated} vote records")
        
        self.stdout.write(self.style.SUCCESS(f"\nVote records: Created {vote_records_created}, Updated {vote_records_updated}, Skipped {vote_records_skipped}"))
        self.stdout.write(self.style.SUCCESS(f"\nDone. Processed {votes_created + votes_updated} votes and {vote_records_created + vote_records_updated} vote records."))

