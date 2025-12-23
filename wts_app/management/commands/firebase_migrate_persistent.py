import firebase_admin
from firebase_admin import credentials, firestore
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
import json


class Command(BaseCommand):
    help = 'Firebase migration command for persistent_voting_places, persistent_candidates, and persistent_parties - Schema inspection'

    def add_arguments(self, parser):
        parser.add_argument(
            '--inspect-only',
            action='store_true',
            help='Only inspect schema, do not migrate',
        )
        parser.add_argument(
            '--migrate',
            action='store_true',
            help='Perform the actual migration',
        )

    def handle(self, *args, **options):
        # Initialize Firebase Admin SDK
        if not firebase_admin._apps:
            cred = credentials.Certificate(settings.FIREBASE_CONFIG)
            firebase_admin.initialize_app(cred)
        
        # Get Firestore client
        db = firestore.client()
        
        self.stdout.write(self.style.SUCCESS('Firebase client initialized successfully'))
        
        # Default to inspect-only unless --migrate flag is explicitly set
        migrate = options.get('migrate', False)
        
        if migrate:
            self.perform_migration(db)
        else:
            self.inspect_schemas(db)

    def inspect_schemas(self, db):
        """Inspect the schema of Firebase collections."""
        self.stdout.write(self.style.SUCCESS('\n=== Inspecting Firebase Collection Schemas ===\n'))
        
        # Inspect persistent_voting_places
        self.stdout.write(self.style.WARNING('--- persistent_voting_places Collection ---'))
        try:
            voting_places_ref = db.collection('persistent_voting_places')
            voting_places = list(voting_places_ref.limit(3).stream())
            
            if not voting_places:
                self.stdout.write(self.style.ERROR('No documents found in persistent_voting_places'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Found {len(voting_places)} example document(s):\n'))
                for idx, doc in enumerate(voting_places, 1):
                    data = doc.to_dict()
                    self.stdout.write(f'Example {idx} (ID: {doc.id}):')
                    self.stdout.write(json.dumps(data, indent=2, default=str))
                    self.stdout.write('\n')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error querying persistent_voting_places: {e}'))
        
        # Inspect persistent_candidates
        self.stdout.write(self.style.WARNING('\n--- persistent_candidates Collection ---'))
        try:
            candidates_ref = db.collection('persistent_candidates')
            candidates = list(candidates_ref.limit(3).stream())
            
            if not candidates:
                self.stdout.write(self.style.ERROR('No documents found in persistent_candidates'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Found {len(candidates)} example document(s):\n'))
                for idx, doc in enumerate(candidates, 1):
                    data = doc.to_dict()
                    self.stdout.write(f'Example {idx} (ID: {doc.id}):')
                    self.stdout.write(json.dumps(data, indent=2, default=str))
                    self.stdout.write('\n')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error querying persistent_candidates: {e}'))
        
        # Inspect persistent_parties
        self.stdout.write(self.style.WARNING('\n--- persistent_parties Collection ---'))
        try:
            parties_ref = db.collection('persistent_parties')
            parties = list(parties_ref.limit(3).stream())
            
            if not parties:
                self.stdout.write(self.style.ERROR('No documents found in persistent_parties'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Found {len(parties)} example document(s):\n'))
                for idx, doc in enumerate(parties, 1):
                    data = doc.to_dict()
                    self.stdout.write(f'Example {idx} (ID: {doc.id}):')
                    self.stdout.write(json.dumps(data, indent=2, default=str))
                    self.stdout.write('\n')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error querying persistent_parties: {e}'))
        
        self.stdout.write(self.style.SUCCESS('\n=== Schema Inspection Complete ==='))
        self.stdout.write(self.style.WARNING('\nTo perform the migration, run with --migrate flag'))

    def perform_migration(self, db):
        """Perform the actual migration."""
        from wts_app.models import PersistentVotingPlace, PersistentCandidate, PersistentParty
        
        self.stdout.write(self.style.SUCCESS('\n=== Starting Migration ===\n'))
        
        # Migrate persistent_voting_places
        self.stdout.write(self.style.WARNING('--- Migrating persistent_voting_places ---'))
        try:
            voting_places_ref = db.collection('persistent_voting_places')
            voting_places = list(voting_places_ref.stream())
            
            self.stdout.write(f'Found {len(voting_places)} voting places to migrate')
            
            # Fetch existing voting places by firebase_id for efficient lookup
            existing_firebase_ids = set(
                PersistentVotingPlace.objects.exclude(firebase_id__isnull=True)
                .exclude(firebase_id='')
                .values_list('firebase_id', flat=True)
            )
            existing_voting_places = {
                vp.firebase_id: vp
                for vp in PersistentVotingPlace.objects.exclude(firebase_id__isnull=True)
                .exclude(firebase_id='')
            }
            
            # Prepare data for bulk operations
            voting_places_to_create = []
            voting_places_to_update = []
            skipped_count = 0
            batch_size = 500
            
            self.stdout.write('Processing voting places...')
            for doc in voting_places:
                data = doc.to_dict()
                firebase_id = doc.id
                
                # Validate required fields
                latitude = data.get('latitude')
                longitude = data.get('longitude')
                address = data.get('address', '')
                
                if latitude is None or longitude is None:
                    skipped_count += 1
                    continue
                
                if firebase_id in existing_firebase_ids:
                    # Update existing
                    vp = existing_voting_places[firebase_id]
                    vp.latitude = latitude
                    vp.longitude = longitude
                    vp.address = address
                    voting_places_to_update.append(vp)
                else:
                    # Create new
                    vp = PersistentVotingPlace(
                        firebase_id=firebase_id,
                        latitude=latitude,
                        longitude=longitude,
                        address=address,
                    )
                    voting_places_to_create.append(vp)
            
            # Perform bulk operations in batches
            created_count = 0
            updated_count = 0
            
            # Bulk create in batches
            if voting_places_to_create:
                self.stdout.write(f'Creating {len(voting_places_to_create)} new voting places in batches of {batch_size}...')
                for i in range(0, len(voting_places_to_create), batch_size):
                    batch = voting_places_to_create[i:i + batch_size]
                    with transaction.atomic():
                        PersistentVotingPlace.objects.bulk_create(batch, batch_size=batch_size)
                    created_count += len(batch)
                    self.stdout.write(f'  Created batch: {len(batch)} voting places (total: {created_count}/{len(voting_places_to_create)})')
            
            # Bulk update in batches
            if voting_places_to_update:
                self.stdout.write(f'Updating {len(voting_places_to_update)} existing voting places in batches of {batch_size}...')
                for i in range(0, len(voting_places_to_update), batch_size):
                    batch = voting_places_to_update[i:i + batch_size]
                    with transaction.atomic():
                        PersistentVotingPlace.objects.bulk_update(
                            batch,
                            fields=['latitude', 'longitude', 'address'],
                            batch_size=batch_size
                        )
                    updated_count += len(batch)
                    self.stdout.write(f'  Updated batch: {len(batch)} voting places (total: {updated_count}/{len(voting_places_to_update)})')
            
            self.stdout.write(self.style.SUCCESS(
                f'\nVoting Places: {created_count} created, {updated_count} updated, {skipped_count} skipped\n'
            ))
        except Exception as e:
            raise CommandError(f'Error migrating persistent_voting_places: {e}')
        
        # Migrate persistent_candidates
        self.stdout.write(self.style.WARNING('--- Migrating persistent_candidates ---'))
        try:
            candidates_ref = db.collection('persistent_candidates')
            candidates = list(candidates_ref.stream())
            
            self.stdout.write(f'Found {len(candidates)} candidates to migrate')
            
            # Fetch existing candidates by firebase_id for efficient lookup
            existing_firebase_ids = set(
                PersistentCandidate.objects.exclude(firebase_id__isnull=True)
                .exclude(firebase_id='')
                .values_list('firebase_id', flat=True)
            )
            existing_candidates = {
                c.firebase_id: c
                for c in PersistentCandidate.objects.exclude(firebase_id__isnull=True)
                .exclude(firebase_id='')
            }
            
            # Prepare data for bulk operations
            candidates_to_create = []
            candidates_to_update = []
            skipped_count = 0
            batch_size = 500
            
            self.stdout.write('Processing candidates...')
            for doc in candidates:
                data = doc.to_dict()
                firebase_id = doc.id
                
                # Map Firebase fields to Django model
                # Fields: display_name, wts_id (optional, nullable)
                display_name = data.get('display_name', '')
                
                if not display_name:
                    skipped_count += 1
                    continue
                
                # Note: wts_id could potentially link to Person.id, but we're not matching here
                # Person field will be left as None - can be linked manually later if needed
                
                if firebase_id in existing_firebase_ids:
                    # Update existing
                    candidate = existing_candidates[firebase_id]
                    candidate.display_name = display_name
                    candidate.person = None  # Not matching to Person, per user request
                    candidates_to_update.append(candidate)
                else:
                    # Create new
                    candidate = PersistentCandidate(
                        firebase_id=firebase_id,
                        display_name=display_name,
                        person=None,  # Not matching to Person, per user request
                    )
                    candidates_to_create.append(candidate)
            
            # Perform bulk operations in batches
            created_count = 0
            updated_count = 0
            
            # Bulk create in batches
            if candidates_to_create:
                self.stdout.write(f'Creating {len(candidates_to_create)} new candidates in batches of {batch_size}...')
                for i in range(0, len(candidates_to_create), batch_size):
                    batch = candidates_to_create[i:i + batch_size]
                    with transaction.atomic():
                        PersistentCandidate.objects.bulk_create(batch, batch_size=batch_size)
                    created_count += len(batch)
                    self.stdout.write(f'  Created batch: {len(batch)} candidates (total: {created_count}/{len(candidates_to_create)})')
            
            # Bulk update in batches
            if candidates_to_update:
                self.stdout.write(f'Updating {len(candidates_to_update)} existing candidates in batches of {batch_size}...')
                for i in range(0, len(candidates_to_update), batch_size):
                    batch = candidates_to_update[i:i + batch_size]
                    with transaction.atomic():
                        PersistentCandidate.objects.bulk_update(
                            batch,
                            fields=['display_name', 'person'],
                            batch_size=batch_size
                        )
                    updated_count += len(batch)
                    self.stdout.write(f'  Updated batch: {len(batch)} candidates (total: {updated_count}/{len(candidates_to_update)})')
            
            self.stdout.write(self.style.SUCCESS(
                f'\nCandidates: {created_count} created, {updated_count} updated, {skipped_count} skipped\n'
            ))
        except Exception as e:
            raise CommandError(f'Error migrating persistent_candidates: {e}')
        
        # Migrate persistent_parties
        self.stdout.write(self.style.WARNING('--- Migrating persistent_parties ---'))
        try:
            parties_ref = db.collection('persistent_parties')
            parties = list(parties_ref.stream())
            
            self.stdout.write(f'Found {len(parties)} parties to migrate')
            
            # Fetch existing parties by firebase_id for efficient lookup
            existing_firebase_ids = set(
                PersistentParty.objects.exclude(firebase_id__isnull=True)
                .exclude(firebase_id='')
                .values_list('firebase_id', flat=True)
            )
            existing_parties = {
                p.firebase_id: p
                for p in PersistentParty.objects.exclude(firebase_id__isnull=True)
                .exclude(firebase_id='')
            }
            
            # Prepare data for bulk operations
            parties_to_create = []
            parties_to_update = []
            skipped_count = 0
            batch_size = 500
            
            self.stdout.write('Processing parties...')
            for doc in parties:
                data = doc.to_dict()
                firebase_id = doc.id
                
                # Map Firebase fields to Django model
                # Fields: abbreviation, colour, display_name, short_name, wts_id (optional, nullable)
                abbreviation = data.get('abbreviation')
                # Handle both 'colour' and 'color' spellings
                colour = data.get('colour') or data.get('color')
                display_name = data.get('display_name')
                short_name = data.get('short_name')
                
                # Note: wts_id could potentially link to Party.id, but we're not matching here
                # Party field will be left as None - can be linked manually later if needed
                
                if firebase_id in existing_firebase_ids:
                    # Update existing
                    party = existing_parties[firebase_id]
                    party.abbreviation = abbreviation
                    party.colour = colour
                    party.display_name = display_name
                    party.short_name = short_name
                    party.party = None  # Not matching to Party, per user request
                    parties_to_update.append(party)
                else:
                    # Create new
                    party = PersistentParty(
                        firebase_id=firebase_id,
                        abbreviation=abbreviation,
                        colour=colour,
                        display_name=display_name,
                        short_name=short_name,
                        party=None,  # Not matching to Party, per user request
                    )
                    parties_to_create.append(party)
            
            # Perform bulk operations in batches
            created_count = 0
            updated_count = 0
            
            # Bulk create in batches
            if parties_to_create:
                self.stdout.write(f'Creating {len(parties_to_create)} new parties in batches of {batch_size}...')
                for i in range(0, len(parties_to_create), batch_size):
                    batch = parties_to_create[i:i + batch_size]
                    with transaction.atomic():
                        PersistentParty.objects.bulk_create(batch, batch_size=batch_size)
                    created_count += len(batch)
                    self.stdout.write(f'  Created batch: {len(batch)} parties (total: {created_count}/{len(parties_to_create)})')
            
            # Bulk update in batches
            if parties_to_update:
                self.stdout.write(f'Updating {len(parties_to_update)} existing parties in batches of {batch_size}...')
                for i in range(0, len(parties_to_update), batch_size):
                    batch = parties_to_update[i:i + batch_size]
                    with transaction.atomic():
                        PersistentParty.objects.bulk_update(
                            batch,
                            fields=['abbreviation', 'colour', 'display_name', 'short_name', 'party'],
                            batch_size=batch_size
                        )
                    updated_count += len(batch)
                    self.stdout.write(f'  Updated batch: {len(batch)} parties (total: {updated_count}/{len(parties_to_update)})')
            
            self.stdout.write(self.style.SUCCESS(
                f'\nParties: {created_count} created, {updated_count} updated, {skipped_count} skipped\n'
            ))
        except Exception as e:
            raise CommandError(f'Error migrating persistent_parties: {e}')
        
        self.stdout.write(self.style.SUCCESS('=== Migration Complete ==='))

