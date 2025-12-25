import firebase_admin
from firebase_admin import credentials, firestore
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime
from dateutil import parser as date_parser


class Command(BaseCommand):
    help = 'Firebase migration command for results data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--event-id',
            type=str,
            help='Firebase event_id (firebase_id of ElectionResultVersion) to migrate',
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
        """Inspect the schema of Firebase results collection."""
        self.stdout.write(self.style.SUCCESS('\n=== Inspecting Firebase Results Collection Schema ===\n'))
        
        try:
            ref = db.collection('results')
            docs = list(ref.limit(3).stream())
            
            if not docs:
                self.stdout.write(self.style.ERROR('No documents found in results'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Found {len(docs)} example document(s):\n'))
                import json
                for idx, doc in enumerate(docs, 1):
                    data = doc.to_dict()
                    self.stdout.write(f'Example {idx} (ID: {doc.id}):')
                    self.stdout.write(json.dumps(data, indent=2, default=str))
                    self.stdout.write('\n')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error querying results: {e}'))
        
        self.stdout.write(self.style.SUCCESS('\n=== Schema Inspection Complete ==='))
        self.stdout.write(self.style.WARNING('\nTo perform the migration, run with --migrate --event-id <event_id>'))

    def parse_datetime_field(self, value):
        """Parse datetime field from various formats."""
        if value is None:
            return None
        if isinstance(value, str):
            try:
                # Try dateutil parser first (handles various formats including timezone offsets)
                return date_parser.parse(value)
            except (ValueError, TypeError):
                try:
                    # Fall back to Django's parse_datetime
                    return parse_datetime(value)
                except (ValueError, TypeError):
                    return None
        return value

    def perform_migration(self, db, event_id):
        """Perform the actual migration."""
        from wts_app.models import (
            ElectionResultVersion, ResultsSet, Result,
            ElectionElectorate, ElectionVotingPlace, ElectionParty, ElectionCandidate
        )
        
        # Get the results version
        try:
            results_version = ElectionResultVersion.objects.get(firebase_id=event_id)
        except ElectionResultVersion.DoesNotExist:
            raise CommandError(f'ElectionResultVersion with firebase_id="{event_id}" not found. Please migrate the event first using firebase_migrate_events.')
        
        self.stdout.write(self.style.SUCCESS(f'\n=== Starting Results Migration for Event: {results_version.name} ({event_id}) ===\n'))
        
        # Build caches for lookups
        self.build_caches(results_version)
        
        batch_size = 500
        
        # Migrate results sets
        self.migrate_results_sets(db, results_version, event_id, batch_size)
        
        self.stdout.write(self.style.SUCCESS('\n=== Migration Complete ==='))

    def build_caches(self, results_version):
        """Build caches for efficient lookups."""
        from wts_app.models import ElectionElectorate, ElectionVotingPlace, ElectionParty, ElectionCandidate
        
        # Cache electorates by number
        self.electorate_cache = {
            ee.number: ee
            for ee in ElectionElectorate.objects.filter(results_version=results_version)
        }
        
        # Cache voting places by number
        self.voting_place_cache = {
            evp.number: evp
            for evp in ElectionVotingPlace.objects.filter(results_version=results_version)
        }
        
        # Cache parties by number
        self.party_cache = {
            ep.number: ep
            for ep in ElectionParty.objects.filter(results_version=results_version)
        }
        
        # Cache candidates by number
        self.candidate_cache = {
            ec.number: ec
            for ec in ElectionCandidate.objects.filter(results_version=results_version)
        }

    def migrate_results_sets(self, db, results_version, event_id, batch_size):
        """Migrate results sets and their results."""
        from wts_app.models import ResultsSet, Result
        
        self.stdout.write(self.style.WARNING('--- Migrating Results Sets ---'))
        try:
            ref = db.collection('results')
            # Filter by event_id
            docs = [doc for doc in ref.stream() if doc.to_dict().get('event_id') == event_id]
            
            self.stdout.write(f'Found {len(docs)} results sets to migrate')
            
            if not docs:
                self.stdout.write(self.style.WARNING('No results sets found for this event'))
                return
            
            # Fetch existing results sets by firebase_id
            existing_results_sets = {
                rs.firebase_id: rs
                for rs in ResultsSet.objects.filter(results_version=results_version).exclude(firebase_id__isnull=True).exclude(firebase_id='')
            }
            
            # Prepare data
            results_sets_to_create = []
            results_sets_to_update = []
            results_data_to_create = []  # Store (results_set_data, results_list) tuples
            results_data_to_update = []  # Store (results_set, results_list) tuples
            skipped_count = 0
            
            self.stdout.write('Processing results sets...')
            for doc in docs:
                data = doc.to_dict()
                firebase_id = doc.id
                
                # Map fields
                results_level = data.get('results_level')
                results_category = data.get('results_category')
                electorate_id = data.get('electorate_id')
                voting_place_id = data.get('voting_place_id') or data.get('voting_place_no')
                informals = data.get('informals')
                unknowns = data.get('unknowns')
                refused = data.get('refused')
                sample_size = data.get('sample_size')
                updated = self.parse_datetime_field(data.get('updated'))
                parsed = self.parse_datetime_field(data.get('parsed'))
                received = self.parse_datetime_field(data.get('received'))
                is_final = data.get('is_final', False)
                statistics = data.get('statistics')
                
                # Extract statistics fields
                total_voting_places_counted = statistics.get('total_voting_places_counted') if statistics else None
                percent_voting_places_counted = statistics.get('percent_voting_places_counted') if statistics else None
                total_votes_cast = statistics.get('total_votes_cast') if statistics else None
                percent_votes_cast = statistics.get('percent_votes_cast') if statistics else None
                total_electorates_final = statistics.get('total_electorates_final') if statistics else None
                percent_electorates_final = statistics.get('percent_electorates_final') if statistics else None
                total_minimal_votes = statistics.get('total_minimal_votes') if statistics else None
                total_special_votes = statistics.get('total_special_votes') if statistics else None
                total_registered_parties = statistics.get('total_registered_parties') if statistics else None
                total_voting_places = statistics.get('total_voting_places') if statistics else None
                total_party_informals = statistics.get('total_party_informals') if statistics else None
                total_candidate_informals = statistics.get('total_candidate_informals') if statistics else None
                total_candidates = statistics.get('total_candidates') if statistics else None
                total_issued_ballot_papers = statistics.get('total_issued_ballot_papers') if statistics else None
                
                if not results_level or not results_category or not updated:
                    skipped_count += 1
                    self.stdout.write(self.style.WARNING(f'  ⚠ Skipping results set {firebase_id}: missing required fields'))
                    continue
                
                # Link to ElectionElectorate if provided
                electorate = None
                if electorate_id is not None:
                    electorate = self.electorate_cache.get(electorate_id)
                    if not electorate:
                        self.stdout.write(self.style.WARNING(
                            f'  ⚠ Results set {firebase_id}: ElectionElectorate with number {electorate_id} not found'
                        ))
                
                # Link to ElectionVotingPlace if provided
                voting_place = None
                if voting_place_id is not None:
                    voting_place = self.voting_place_cache.get(voting_place_id)
                    if not voting_place:
                        self.stdout.write(self.style.WARNING(
                            f'  ⚠ Results set {firebase_id}: ElectionVotingPlace with number {voting_place_id} not found'
                        ))
                
                # Store results set data for later processing
                rs_data = {
                    'results_version': results_version,
                    'firebase_id': firebase_id,
                    'results_level': results_level,
                    'results_category': results_category,
                    'electorate': electorate,
                    'voting_place': voting_place,
                    'informals': informals,
                    'unknowns': unknowns,
                    'refused': refused,
                    'sample_size': sample_size,
                    'updated': updated,
                    'parsed': parsed,
                    'received': received,
                    'is_final': is_final,
                    'statistics': statistics,
                    'total_voting_places_counted': total_voting_places_counted,
                    'percent_voting_places_counted': percent_voting_places_counted,
                    'total_votes_cast': total_votes_cast,
                    'percent_votes_cast': percent_votes_cast,
                    'total_electorates_final': total_electorates_final,
                    'percent_electorates_final': percent_electorates_final,
                    'total_minimal_votes': total_minimal_votes,
                    'total_special_votes': total_special_votes,
                    'total_registered_parties': total_registered_parties,
                    'total_voting_places': total_voting_places,
                    'total_party_informals': total_party_informals,
                    'total_candidate_informals': total_candidate_informals,
                    'total_candidates': total_candidates,
                    'total_issued_ballot_papers': total_issued_ballot_papers,
                }
                
                # Create or update ResultsSet
                if firebase_id in existing_results_sets:
                    rs = existing_results_sets[firebase_id]
                    rs.results_level = results_level
                    rs.results_category = results_category
                    rs.electorate = electorate
                    rs.voting_place = voting_place
                    rs.informals = informals
                    rs.unknowns = unknowns
                    rs.refused = refused
                    rs.sample_size = sample_size
                    rs.updated = updated
                    rs.parsed = parsed
                    rs.received = received
                    rs.is_final = is_final
                    rs.statistics = statistics
                    rs.total_voting_places_counted = total_voting_places_counted
                    rs.percent_voting_places_counted = percent_voting_places_counted
                    rs.total_votes_cast = total_votes_cast
                    rs.percent_votes_cast = percent_votes_cast
                    rs.total_electorates_final = total_electorates_final
                    rs.percent_electorates_final = percent_electorates_final
                    rs.total_minimal_votes = total_minimal_votes
                    rs.total_special_votes = total_special_votes
                    rs.total_registered_parties = total_registered_parties
                    rs.total_voting_places = total_voting_places
                    rs.total_party_informals = total_party_informals
                    rs.total_candidate_informals = total_candidate_informals
                    rs.total_candidates = total_candidates
                    rs.total_issued_ballot_papers = total_issued_ballot_papers
                    results_sets_to_update.append(rs)
                    # Initialize results list for this results set
                    results_data_to_update.append((rs, []))
                else:
                    # Store results set data for later creation
                    results_data_to_create.append((rs_data, []))
                
                # Process results array
                results_array = data.get('results', [])
                for result_item in results_array:
                    candidate_id = result_item.get('candidate_id')
                    party_id = result_item.get('party_id')
                    count = result_item.get('count')
                    per_cent = result_item.get('per_cent')
                    list_seats = result_item.get('list_seats')
                    electorate_seats = result_item.get('electorate_seats')
                    total_seats = result_item.get('total_seats')
                    
                    # Convert party_id to int if it's a string
                    if party_id is not None and isinstance(party_id, str):
                        try:
                            party_id = int(party_id)
                        except (ValueError, TypeError):
                            party_id = None
                    
                    # Link to ElectionCandidate if provided
                    candidate = None
                    if candidate_id is not None:
                        candidate = self.candidate_cache.get(candidate_id)
                        if not candidate:
                            self.stdout.write(self.style.WARNING(
                                f'  ⚠ Results set {firebase_id}: ElectionCandidate with number {candidate_id} not found'
                            ))
                    
                    # Link to ElectionParty if provided
                    party = None
                    if party_id is not None:
                        party = self.party_cache.get(party_id)
                        if not party:
                            self.stdout.write(self.style.WARNING(
                                f'  ⚠ Results set {firebase_id}: ElectionParty with number {party_id} not found'
                            ))
                    
                    # Store result data (we'll create Result objects after ResultsSet is saved)
                    result_data = {
                        'candidate': candidate,
                        'party': party,
                        'count': count,
                        'per_cent': per_cent,
                        'list_seats': list_seats,
                        'electorate_seats': electorate_seats,
                        'total_seats': total_seats,
                    }
                    
                    if firebase_id in existing_results_sets:
                        # Find the tuple and append
                        found = False
                        for idx, (rss, results_list) in enumerate(results_data_to_update):
                            if rss.id == rs.id:
                                results_data_to_update[idx][1].append(result_data)
                                found = True
                                break
                        if not found:
                            results_data_to_update.append((rs, [result_data]))
                    else:
                        # Find the tuple for this results set and append
                        found = False
                        for idx, (rss_data, results_list) in enumerate(results_data_to_create):
                            if rss_data['firebase_id'] == firebase_id:
                                results_data_to_create[idx][1].append(result_data)
                                found = True
                                break
                        if not found:
                            # This shouldn't happen, but handle it
                            self.stdout.write(self.style.ERROR(
                                f'  ⚠ Results set {firebase_id}: Could not find results set data for result'
                            ))
            
            # Bulk create/update ResultsSets first
            created_count = 0
            updated_count = 0
            
            # Create ResultsSet objects from data
            if results_data_to_create:
                for rs_data, _ in results_data_to_create:
                    rs = ResultsSet(**rs_data)
                    results_sets_to_create.append(rs)
            
            if results_sets_to_create:
                self.stdout.write(f'Creating {len(results_sets_to_create)} new results sets...')
                for i in range(0, len(results_sets_to_create), batch_size):
                    batch = results_sets_to_create[i:i + batch_size]
                    with transaction.atomic():
                        ResultsSet.objects.bulk_create(batch, batch_size=batch_size)
                    created_count += len(batch)
                    self.stdout.write(f'  Created batch: {len(batch)} (total: {created_count}/{len(results_sets_to_create)})')
                
                # Refresh to get IDs for created results sets
                firebase_ids = [rs.firebase_id for rs in results_sets_to_create]
                created_results_sets = {
                    rs.firebase_id: rs
                    for rs in ResultsSet.objects.filter(firebase_id__in=firebase_ids)
                }
            
            if results_sets_to_update:
                self.stdout.write(f'Updating {len(results_sets_to_update)} existing results sets...')
                for i in range(0, len(results_sets_to_update), batch_size):
                    batch = results_sets_to_update[i:i + batch_size]
                    with transaction.atomic():
                        ResultsSet.objects.bulk_update(
                            batch,
                            fields=[
                                'results_level', 'results_category', 'electorate', 'voting_place',
                                'informals', 'unknowns', 'refused', 'sample_size', 'updated', 'parsed',
                                'received', 'is_final', 'statistics',
                                'total_voting_places_counted', 'percent_voting_places_counted',
                                'total_votes_cast', 'percent_votes_cast',
                                'total_electorates_final', 'percent_electorates_final',
                                'total_minimal_votes', 'total_special_votes',
                                'total_registered_parties', 'total_voting_places',
                                'total_party_informals', 'total_candidate_informals',
                                'total_candidates', 'total_issued_ballot_papers'
                            ],
                            batch_size=batch_size
                        )
                    updated_count += len(batch)
                    self.stdout.write(f'  Updated batch: {len(batch)} (total: {updated_count}/{len(results_sets_to_update)})')
            
            # Now handle Results - delete existing and recreate
            # First, delete existing results for updated results sets
            if results_sets_to_update:
                results_set_ids = [rs.id for rs in results_sets_to_update]
                Result.objects.filter(results_set_id__in=results_set_ids).delete()
            
            # Create all results
            all_results = []
            
            # Create results for newly created results sets
            if results_data_to_create:
                for rs_data, results_list in results_data_to_create:
                    rs = created_results_sets.get(rs_data['firebase_id'])
                    if rs:
                        for result_data in results_list:
                            result = Result(
                                results_set=rs,
                                **result_data
                            )
                            all_results.append(result)
            
            # Create results for updated results sets
            if results_data_to_update:
                for rs, results_list in results_data_to_update:
                    for result_data in results_list:
                        result = Result(
                            results_set=rs,
                            **result_data
                        )
                        all_results.append(result)
            
            if all_results:
                self.stdout.write(f'Creating {len(all_results)} results...')
                for i in range(0, len(all_results), batch_size):
                    batch = all_results[i:i + batch_size]
                    with transaction.atomic():
                        Result.objects.bulk_create(batch, batch_size=batch_size)
                    self.stdout.write(f'  Created batch: {len(batch)} (total: {i + len(batch)}/{len(all_results)})')
            
            self.stdout.write(self.style.SUCCESS(
                f'\nResults Sets: {created_count} created, {updated_count} updated, {skipped_count} skipped'
            ))
            self.stdout.write(self.style.SUCCESS(
                f'Results: {len(all_results)} created\n'
            ))
            
        except Exception as e:
            raise CommandError(f'Error migrating results: {e}')

