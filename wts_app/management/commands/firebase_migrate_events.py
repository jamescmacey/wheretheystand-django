import firebase_admin
from firebase_admin import credentials, firestore
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from wts_app.models import Election, ElectionResultVersion


class Command(BaseCommand):
    help = 'Firebase migration command'

    def handle(self, *args, **options):
        # Initialize Firebase Admin SDK
        if not firebase_admin._apps:
            cred = credentials.Certificate(settings.FIREBASE_CONFIG)
            firebase_admin.initialize_app(cred)
        
        # Get Firestore client
        db = firestore.client()
        
        self.stdout.write(self.style.SUCCESS('Firebase client initialized successfully'))
        
        # List available elections
        elections = Election.objects.all().order_by('-polling_date')
        
        if not elections.exists():
            raise CommandError('No elections found in the database.')
        
        self.stdout.write(self.style.SUCCESS('\nAvailable elections:'))
        election_list = list(elections)
        for idx, election in enumerate(election_list, start=1):
            self.stdout.write(f"{idx}. {election.name} ({election.polling_date})")
        
        # Prompt user to select an election
        while True:
            try:
                choice = input('\nEnter the number of the election to link the event with: ')
                choice_num = int(choice)
                if 1 <= choice_num <= len(election_list):
                    selected_election = election_list[choice_num - 1]
                    break
                else:
                    self.stdout.write(self.style.ERROR(f'Please enter a number between 1 and {len(election_list)}'))
            except ValueError:
                self.stdout.write(self.style.ERROR('Please enter a valid number'))
            except (EOFError, KeyboardInterrupt):
                raise CommandError('\nOperation cancelled by user.')
        
        self.stdout.write(self.style.SUCCESS(f'\nSelected election: {selected_election.name} ({selected_election.polling_date})'))
        
        # Query Firebase for events
        try:
            events_ref = db.collection('events')
            events = list(events_ref.stream())
        except Exception as e:
            raise CommandError(f'Error querying Firebase events: {e}')
        
        if not events:
            raise CommandError('No events found in Firebase.')
        
        self.stdout.write(self.style.SUCCESS('\nAvailable Firebase events:'))
        event_list = []
        for idx, event_doc in enumerate(events, start=1):
            event_data = event_doc.to_dict()
            event_name = event_data.get('name', 'Unnamed Event')
            event_id = event_doc.id
            event_list.append((event_doc, event_data))
            self.stdout.write(f"{idx}. {event_name} (ID: {event_id})")
        
        # Prompt user to select a Firebase event
        while True:
            try:
                choice = input('\nEnter the number of the Firebase event to migrate: ')
                choice_num = int(choice)
                if 1 <= choice_num <= len(event_list):
                    selected_event_doc, selected_event_data = event_list[choice_num - 1]
                    break
                else:
                    self.stdout.write(self.style.ERROR(f'Please enter a number between 1 and {len(event_list)}'))
            except ValueError:
                self.stdout.write(self.style.ERROR('Please enter a valid number'))
            except (EOFError, KeyboardInterrupt):
                raise CommandError('\nOperation cancelled by user.')
        
        event_name = selected_event_data.get('name', 'Unnamed Event')
        self.stdout.write(self.style.SUCCESS(f'\nSelected Firebase event: {event_name} (ID: {selected_event_doc.id})'))
        
        # Map Firebase event fields to Django ElectionResultVersion fields
        self.stdout.write(self.style.SUCCESS('\n=== Mapping Fields ==='))
        
        # Direct field mappings
        name = selected_event_data.get('name', '')
        description = selected_event_data.get('description', '')
        slug = selected_event_data.get('slug', '')
        firebase_id = selected_event_doc.id
        is_primary = False  # Default to False
        access_mode = 'firebase'  # Always 'firebase' for migrated events
        
        self.stdout.write(f'  name: "{name}"')
        if description:
            desc_preview = description[:50] + '...' if len(description) > 50 else description
        else:
            desc_preview = ''
        self.stdout.write(f'  description: "{desc_preview}"')
        self.stdout.write(f'  slug: "{slug}"')
        self.stdout.write(f'  firebase_id: "{firebase_id}"')
        self.stdout.write(f'  is_primary: {is_primary}')
        self.stdout.write(f'  access_mode: "{access_mode}"')
        
        # Create the ElectionResultVersion
        self.stdout.write('\n' + self.style.SUCCESS('=== Creating ElectionResultVersion ==='))
        
        try:
            result_version, created = ElectionResultVersion.objects.update_or_create(
                election=selected_election,
                firebase_id=firebase_id,
                defaults={
                    'name': name,
                    'description': description,
                    'slug': slug,
                    'is_primary': is_primary,
                    'access_mode': access_mode,
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'✓ Created ElectionResultVersion: {result_version.name}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'✓ Updated ElectionResultVersion: {result_version.name}'))
            
            self.stdout.write(self.style.SUCCESS(f'\nMigration complete!'))
            self.stdout.write(f'  - ID: {result_version.id}')
            self.stdout.write(f'  - Name: {result_version.name}')
            self.stdout.write(f'  - Slug: {result_version.slug}')
            self.stdout.write(f'  - Firebase ID: {result_version.firebase_id}')
            self.stdout.write(f'  - Is Primary: {result_version.is_primary}')
            self.stdout.write(f'  - Access Mode: {result_version.access_mode}')
            
        except Exception as e:
            raise CommandError(f'Error creating ElectionResultVersion: {e}')

        