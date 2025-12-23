import firebase_admin
from firebase_admin import credentials, firestore
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
import json


class Command(BaseCommand):
    help = 'Firebase migration command for election_electorates, election_voting_places, election_parties, and election_candidates'

    def add_arguments(self, parser):
        parser.add_argument(
            '--event-id',
            type=str,
            help='Firebase event_id (firebase_id of ElectionResultVersion) to migrate',
        )
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
            event_id = options.get('event_id')
            if not event_id:
                raise CommandError('--event-id is required when using --migrate')
            self.perform_migration(db, event_id)
        else:
            self.inspect_schemas(db)

    def inspect_schemas(self, db):
        """Inspect the schema of Firebase collections."""
        self.stdout.write(self.style.SUCCESS('\n=== Inspecting Firebase Collection Schemas ===\n'))
        
        collections = [
            'election_electorates',
            'election_voting_places',
            'election_parties',
            'election_candidates',
        ]
        
        for collection_name in collections:
            self.stdout.write(self.style.WARNING(f'\n--- {collection_name} Collection ---'))
            try:
                ref = db.collection(collection_name)
                docs = list(ref.limit(3).stream())
                
                if not docs:
                    self.stdout.write(self.style.ERROR(f'No documents found in {collection_name}'))
                else:
                    self.stdout.write(self.style.SUCCESS(f'Found {len(docs)} example document(s):\n'))
                    for idx, doc in enumerate(docs, 1):
                        data = doc.to_dict()
                        self.stdout.write(f'Example {idx} (ID: {doc.id}):')
                        self.stdout.write(json.dumps(data, indent=2, default=str))
                        self.stdout.write('\n')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error querying {collection_name}: {e}'))
        
        self.stdout.write(self.style.SUCCESS('\n=== Schema Inspection Complete ==='))
        self.stdout.write(self.style.WARNING('\nTo perform the migration, run with --migrate --event-id <event_id>'))

    def perform_migration(self, db, event_id):
        """Perform the actual migration."""
        from wts_app.models import (
            ElectionResultVersion, ElectionElectorate, ElectionVotingPlace,
            ElectionParty, ElectionCandidate, Electorate, PersistentParty, PersistentCandidate, PersistentVotingPlace
        )
        
        # Get the results version
        try:
            results_version = ElectionResultVersion.objects.get(firebase_id=event_id)
        except ElectionResultVersion.DoesNotExist:
            raise CommandError(f'ElectionResultVersion with firebase_id="{event_id}" not found. Please migrate the event first using firebase_migrate_events.')
        
        self.stdout.write(self.style.SUCCESS(f'\n=== Starting Migration for Event: {results_version.name} ({event_id}) ===\n'))
        
        batch_size = 500
        
        # Step 1: Migrate Election Electorates
        self.migrate_election_electorates(db, results_version, event_id, batch_size)
        
        # Step 2: Migrate Election Voting Places (depends on electorates)
        self.migrate_election_voting_places(db, results_version, event_id, batch_size)
        
        # Step 3: Migrate Election Parties (depends on persistent parties)
        self.migrate_election_parties(db, results_version, event_id, batch_size)
        
        # Step 4: Migrate Election Candidates (depends on electorates and parties)
        self.migrate_election_candidates(db, results_version, event_id, batch_size)
        
        self.stdout.write(self.style.SUCCESS('\n=== Migration Complete ==='))

    def migrate_election_electorates(self, db, results_version, event_id, batch_size):
        """Migrate election electorates."""
        from wts_app.models import ElectionElectorate, Electorate
        
        self.stdout.write(self.style.WARNING('--- Migrating Election Electorates ---'))
        try:
            ref = db.collection('election_electorates')
            # Filter by event_id
            docs = [doc for doc in ref.stream() if doc.to_dict().get('event_id') == event_id]
            
            self.stdout.write(f'Found {len(docs)} election electorates to migrate')
            
            if not docs:
                self.stdout.write(self.style.WARNING('No election electorates found for this event'))
                return
            
            # Fetch existing electorates by results_version and number
            existing_electorates = {
                (ee.results_version_id, ee.number): ee
                for ee in ElectionElectorate.objects.filter(results_version=results_version)
            }
            
            # Fetch all electorates by legacy_id for linking
            electorate_by_legacy_id = {
                e.legacy_id: e
                for e in Electorate.objects.exclude(legacy_id__isnull=True)
            }
            
            # Prepare data
            electorates_to_create = []
            electorates_to_update = []
            skipped_count = 0
            
            self.stdout.write('Processing election electorates...')
            for doc in docs:
                data = doc.to_dict()
                firebase_id = doc.id
                
                # Map fields
                number = data.get('electorate_id')
                name = data.get('name', '')
                persistent_electorate_id = data.get('persistent_electorate_id')
                
                if not number or not name:
                    skipped_count += 1
                    continue
                
                # Link to Electorate if persistent_electorate_id provided
                electorate = None
                if persistent_electorate_id:
                    electorate = electorate_by_legacy_id.get(persistent_electorate_id)
                
                key = (results_version.id, number)
                if key in existing_electorates:
                    # Update existing
                    ee = existing_electorates[key]
                    ee.firebase_id = firebase_id
                    ee.name = name
                    ee.electorate = electorate
                    electorates_to_update.append(ee)
                else:
                    # Create new
                    ee = ElectionElectorate(
                        results_version=results_version,
                        firebase_id=firebase_id,
                        number=number,
                        name=name,
                        electorate=electorate,
                    )
                    electorates_to_create.append(ee)
            
            # Bulk operations
            created_count = 0
            updated_count = 0
            
            if electorates_to_create:
                self.stdout.write(f'Creating {len(electorates_to_create)} new election electorates...')
                for i in range(0, len(electorates_to_create), batch_size):
                    batch = electorates_to_create[i:i + batch_size]
                    with transaction.atomic():
                        ElectionElectorate.objects.bulk_create(batch, batch_size=batch_size)
                    created_count += len(batch)
                    self.stdout.write(f'  Created batch: {len(batch)} (total: {created_count}/{len(electorates_to_create)})')
            
            if electorates_to_update:
                self.stdout.write(f'Updating {len(electorates_to_update)} existing election electorates...')
                for i in range(0, len(electorates_to_update), batch_size):
                    batch = electorates_to_update[i:i + batch_size]
                    with transaction.atomic():
                        ElectionElectorate.objects.bulk_update(
                            batch,
                            fields=['firebase_id', 'name', 'electorate'],
                            batch_size=batch_size
                        )
                    updated_count += len(batch)
                    self.stdout.write(f'  Updated batch: {len(batch)} (total: {updated_count}/{len(electorates_to_update)})')
            
            self.stdout.write(self.style.SUCCESS(
                f'\nElection Electorates: {created_count} created, {updated_count} updated, {skipped_count} skipped\n'
            ))
            
            # Cache updated electorates for next steps
            self.election_electorate_cache = {
                ee.number: ee
                for ee in ElectionElectorate.objects.filter(results_version=results_version)
            }
            
        except Exception as e:
            raise CommandError(f'Error migrating election_electorates: {e}')

    def migrate_election_voting_places(self, db, results_version, event_id, batch_size):
        """Migrate election voting places."""
        from wts_app.models import ElectionVotingPlace, ElectionElectorate, PersistentVotingPlace
        
        self.stdout.write(self.style.WARNING('--- Migrating Election Voting Places ---'))
        try:
            ref = db.collection('election_voting_places')
            docs = [doc for doc in ref.stream() if doc.to_dict().get('event_id') == event_id]
            
            self.stdout.write(f'Found {len(docs)} election voting places to migrate')
            
            if not docs:
                self.stdout.write(self.style.WARNING('No election voting places found for this event'))
                return
            
            # Get election electorate cache (created in previous step)
            if not hasattr(self, 'election_electorate_cache'):
                self.election_electorate_cache = {
                    ee.number: ee
                    for ee in ElectionElectorate.objects.filter(results_version=results_version)
                }
            
            # Fetch existing voting places
            existing_voting_places = {
                (evp.results_version_id, evp.number): evp
                for evp in ElectionVotingPlace.objects.filter(results_version=results_version)
            }
            
            # Fetch persistent voting places by firebase_id
            persistent_voting_places_by_firebase_id = {
                pvp.firebase_id: pvp
                for pvp in PersistentVotingPlace.objects.exclude(firebase_id__isnull=True).exclude(firebase_id='')
            }
            
            # Prepare data
            voting_places_to_create = []
            voting_places_to_update = []
            skipped_count = 0
            
            self.stdout.write('Processing election voting places...')
            for doc in docs:
                data = doc.to_dict()
                firebase_id = doc.id
                
                # Map fields
                number = data.get('voting_place_id')
                physical_electorate_id = data.get('physical_electorate_id')
                address = data.get('address', '')
                latitude = data.get('latitude')
                longitude = data.get('longitude')
                persistent_voting_place_id = data.get('persistent_voting_place_id')
                
                if not number or physical_electorate_id is None or latitude is None or longitude is None:
                    skipped_count += 1
                    continue
                
                # Link to ElectionElectorate
                physical_electorate = self.election_electorate_cache.get(physical_electorate_id)
                if not physical_electorate:
                    skipped_count += 1
                    self.stdout.write(self.style.WARNING(
                        f'  ⚠ Skipping voting place {number}: ElectionElectorate with number {physical_electorate_id} not found'
                    ))
                    continue
                
                # Link to PersistentVotingPlace if provided
                persistent_voting_place = None
                if persistent_voting_place_id:
                    persistent_voting_place = persistent_voting_places_by_firebase_id.get(persistent_voting_place_id)
                    if not persistent_voting_place:
                        self.stdout.write(self.style.WARNING(
                            f'  ⚠ ElectionVotingPlace {number}: PersistentVotingPlace with firebase_id {persistent_voting_place_id} not found'
                        ))
                
                key = (results_version.id, number)
                if key in existing_voting_places:
                    # Update existing
                    evp = existing_voting_places[key]
                    evp.firebase_id = firebase_id
                    evp.physical_electorate = physical_electorate
                    evp.address = address
                    evp.latitude = latitude
                    evp.longitude = longitude
                    evp.persistent_voting_place = persistent_voting_place
                    voting_places_to_update.append(evp)
                else:
                    # Create new
                    evp = ElectionVotingPlace(
                        results_version=results_version,
                        firebase_id=firebase_id,
                        number=number,
                        physical_electorate=physical_electorate,
                        address=address,
                        latitude=latitude,
                        longitude=longitude,
                        persistent_voting_place=persistent_voting_place,
                    )
                    voting_places_to_create.append(evp)
            
            # Bulk operations
            created_count = 0
            updated_count = 0
            
            if voting_places_to_create:
                self.stdout.write(f'Creating {len(voting_places_to_create)} new election voting places...')
                for i in range(0, len(voting_places_to_create), batch_size):
                    batch = voting_places_to_create[i:i + batch_size]
                    with transaction.atomic():
                        ElectionVotingPlace.objects.bulk_create(batch, batch_size=batch_size)
                    created_count += len(batch)
                    self.stdout.write(f'  Created batch: {len(batch)} (total: {created_count}/{len(voting_places_to_create)})')
            
            if voting_places_to_update:
                self.stdout.write(f'Updating {len(voting_places_to_update)} existing election voting places...')
                for i in range(0, len(voting_places_to_update), batch_size):
                    batch = voting_places_to_update[i:i + batch_size]
                    with transaction.atomic():
                        ElectionVotingPlace.objects.bulk_update(
                            batch,
                            fields=['firebase_id', 'physical_electorate', 'address', 'latitude', 'longitude', 'persistent_voting_place'],
                            batch_size=batch_size
                        )
                    updated_count += len(batch)
                    self.stdout.write(f'  Updated batch: {len(batch)} (total: {updated_count}/{len(voting_places_to_update)})')
            
            self.stdout.write(self.style.SUCCESS(
                f'\nElection Voting Places: {created_count} created, {updated_count} updated, {skipped_count} skipped\n'
            ))
            
        except Exception as e:
            raise CommandError(f'Error migrating election_voting_places: {e}')

    def migrate_election_parties(self, db, results_version, event_id, batch_size):
        """Migrate election parties."""
        from wts_app.models import ElectionParty, PersistentParty
        
        self.stdout.write(self.style.WARNING('--- Migrating Election Parties ---'))
        try:
            ref = db.collection('election_parties')
            docs = [doc for doc in ref.stream() if doc.to_dict().get('event_id') == event_id]
            
            self.stdout.write(f'Found {len(docs)} election parties to migrate')
            
            if not docs:
                self.stdout.write(self.style.WARNING('No election parties found for this event'))
                return
            
            # Fetch existing parties
            existing_parties = {
                (ep.results_version_id, ep.number): ep
                for ep in ElectionParty.objects.filter(results_version=results_version)
            }
            
            # Fetch persistent parties by firebase_id
            persistent_parties_by_firebase_id = {
                pp.firebase_id: pp
                for pp in PersistentParty.objects.exclude(firebase_id__isnull=True).exclude(firebase_id='')
            }
            
            # Prepare data
            parties_to_create = []
            parties_to_update = []
            skipped_count = 0
            
            self.stdout.write('Processing election parties...')
            for doc in docs:
                data = doc.to_dict()
                firebase_id = doc.id
                
                # Map fields
                number = data.get('party_id')
                name = data.get('name', '')
                short_name = data.get('short_name')
                abbreviation = data.get('abbreviation')
                registered = data.get('registered', False)
                persistent_party_id = data.get('persistent_party_id')
                
                if not number or not name:
                    skipped_count += 1
                    continue
                
                # Link to PersistentParty if provided
                persistent_party = None
                if persistent_party_id:
                    persistent_party = persistent_parties_by_firebase_id.get(persistent_party_id)
                    if not persistent_party:
                        self.stdout.write(self.style.WARNING(
                            f'  ⚠ ElectionParty {number}: PersistentParty with firebase_id {persistent_party_id} not found'
                        ))
                
                key = (results_version.id, number)
                if key in existing_parties:
                    # Update existing
                    ep = existing_parties[key]
                    ep.firebase_id = firebase_id
                    ep.name = name
                    ep.short_name = short_name
                    ep.abbreviation = abbreviation
                    ep.registered = registered
                    ep.persistent_party = persistent_party
                    parties_to_update.append(ep)
                else:
                    # Create new
                    ep = ElectionParty(
                        results_version=results_version,
                        firebase_id=firebase_id,
                        number=number,
                        name=name,
                        short_name=short_name,
                        abbreviation=abbreviation,
                        registered=registered,
                        persistent_party=persistent_party,
                    )
                    parties_to_create.append(ep)
            
            # Bulk operations
            created_count = 0
            updated_count = 0
            
            if parties_to_create:
                self.stdout.write(f'Creating {len(parties_to_create)} new election parties...')
                for i in range(0, len(parties_to_create), batch_size):
                    batch = parties_to_create[i:i + batch_size]
                    with transaction.atomic():
                        ElectionParty.objects.bulk_create(batch, batch_size=batch_size)
                    created_count += len(batch)
                    self.stdout.write(f'  Created batch: {len(batch)} (total: {created_count}/{len(parties_to_create)})')
            
            if parties_to_update:
                self.stdout.write(f'Updating {len(parties_to_update)} existing election parties...')
                for i in range(0, len(parties_to_update), batch_size):
                    batch = parties_to_update[i:i + batch_size]
                    with transaction.atomic():
                        ElectionParty.objects.bulk_update(
                            batch,
                            fields=['firebase_id', 'name', 'short_name', 'abbreviation', 'registered', 'persistent_party'],
                            batch_size=batch_size
                        )
                    updated_count += len(batch)
                    self.stdout.write(f'  Updated batch: {len(batch)} (total: {updated_count}/{len(parties_to_update)})')
            
            self.stdout.write(self.style.SUCCESS(
                f'\nElection Parties: {created_count} created, {updated_count} updated, {skipped_count} skipped\n'
            ))
            
            # Cache for next step
            self.election_party_cache = {
                ep.number: ep
                for ep in ElectionParty.objects.filter(results_version=results_version)
            }
            
        except Exception as e:
            raise CommandError(f'Error migrating election_parties: {e}')

    def migrate_election_candidates(self, db, results_version, event_id, batch_size):
        """Migrate election candidates."""
        from wts_app.models import ElectionCandidate, PersistentCandidate, ElectionElectorate, ElectionParty
        
        self.stdout.write(self.style.WARNING('--- Migrating Election Candidates ---'))
        try:
            ref = db.collection('election_candidates')
            docs = [doc for doc in ref.stream() if doc.to_dict().get('event_id') == event_id]
            
            self.stdout.write(f'Found {len(docs)} election candidates to migrate')
            
            if not docs:
                self.stdout.write(self.style.WARNING('No election candidates found for this event'))
                return
            
            # Get caches (created in previous steps)
            if not hasattr(self, 'election_electorate_cache'):
                self.election_electorate_cache = {
                    ee.number: ee
                    for ee in ElectionElectorate.objects.filter(results_version=results_version)
                }
            if not hasattr(self, 'election_party_cache'):
                self.election_party_cache = {
                    ep.number: ep
                    for ep in ElectionParty.objects.filter(results_version=results_version)
                }
            
            # Fetch existing candidates
            existing_candidates = {
                (ec.results_version_id, ec.number): ec
                for ec in ElectionCandidate.objects.filter(results_version=results_version)
            }
            
            # Fetch persistent candidates by firebase_id
            persistent_candidates_by_firebase_id = {
                pc.firebase_id: pc
                for pc in PersistentCandidate.objects.exclude(firebase_id__isnull=True).exclude(firebase_id='')
            }
            
            # Prepare data
            candidates_to_create = []
            candidates_to_update = []
            skipped_count = 0
            
            self.stdout.write('Processing election candidates...')
            for doc in docs:
                data = doc.to_dict()
                firebase_id = doc.id
                
                # Map fields
                number = data.get('candidate_id')
                name = data.get('name', '')
                electorate_id = data.get('electorate_id')
                party_id = data.get('party_id')
                list_pos = data.get('list_pos')
                persistent_candidate_id = data.get('persistent_candidate_id')
                
                if not number or not name:
                    skipped_count += 1
                    continue
                
                # Link to ElectionElectorate if provided
                electorate = None
                if electorate_id is not None:
                    electorate = self.election_electorate_cache.get(electorate_id)
                
                # Link to ElectionParty if provided
                party = None
                if party_id is not None:
                    party = self.election_party_cache.get(party_id)
                
                # Link to PersistentCandidate if provided
                persistent_candidate = None
                if persistent_candidate_id:
                    persistent_candidate = persistent_candidates_by_firebase_id.get(persistent_candidate_id)
                    if not persistent_candidate:
                        self.stdout.write(self.style.WARNING(
                            f'  ⚠ ElectionCandidate {number}: PersistentCandidate with firebase_id {persistent_candidate_id} not found'
                        ))
                
                key = (results_version.id, number)
                if key in existing_candidates:
                    # Update existing
                    ec = existing_candidates[key]
                    ec.firebase_id = firebase_id
                    ec.name = name
                    ec.electorate = electorate
                    ec.party = party
                    ec.list_pos = list_pos
                    ec.persistent_candidate = persistent_candidate
                    candidates_to_update.append(ec)
                else:
                    # Create new
                    ec = ElectionCandidate(
                        results_version=results_version,
                        firebase_id=firebase_id,
                        number=number,
                        name=name,
                        electorate=electorate,
                        party=party,
                        list_pos=list_pos,
                        persistent_candidate=persistent_candidate,
                    )
                    candidates_to_create.append(ec)
            
            # Bulk operations
            created_count = 0
            updated_count = 0
            
            if candidates_to_create:
                self.stdout.write(f'Creating {len(candidates_to_create)} new election candidates...')
                for i in range(0, len(candidates_to_create), batch_size):
                    batch = candidates_to_create[i:i + batch_size]
                    with transaction.atomic():
                        ElectionCandidate.objects.bulk_create(batch, batch_size=batch_size)
                    created_count += len(batch)
                    self.stdout.write(f'  Created batch: {len(batch)} (total: {created_count}/{len(candidates_to_create)})')
            
            if candidates_to_update:
                self.stdout.write(f'Updating {len(candidates_to_update)} existing election candidates...')
                for i in range(0, len(candidates_to_update), batch_size):
                    batch = candidates_to_update[i:i + batch_size]
                    with transaction.atomic():
                        ElectionCandidate.objects.bulk_update(
                            batch,
                            fields=['firebase_id', 'name', 'electorate', 'party', 'list_pos', 'persistent_candidate'],
                            batch_size=batch_size
                        )
                    updated_count += len(batch)
                    self.stdout.write(f'  Updated batch: {len(batch)} (total: {updated_count}/{len(candidates_to_update)})')
            
            self.stdout.write(self.style.SUCCESS(
                f'\nElection Candidates: {created_count} created, {updated_count} updated, {skipped_count} skipped\n'
            ))
            
        except Exception as e:
            raise CommandError(f'Error migrating election_candidates: {e}')

