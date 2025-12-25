from django.core.management.base import BaseCommand, CommandError
from wts_app.models import Person, PersistentCandidate


class Command(BaseCommand):
    help = 'Links People to PersistentCandidates based on last name matching'

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-linked',
            action='store_true',
            help='Skip PersistentCandidates that are already linked to a Person',
        )
        parser.add_argument(
            '--duplicates',
            action='store_true',
            help='List people who are not linked and have multiple matching PersistentCandidates',
        )

    def handle(self, *args, **options):
        duplicates_mode = options.get('duplicates', False)
        
        if duplicates_mode:
            self.list_duplicates()
            return
        
        skip_linked = options.get('skip_linked', False)
        
        people = Person.objects.all().order_by('last_name', 'first_name')
        total_people = people.count()
        
        self.stdout.write(self.style.SUCCESS(f'\n=== Linking People to PersistentCandidates ==='))
        self.stdout.write(f'Total People to process: {total_people}\n')
        
        linked_count = 0
        skipped_count = 0
        
        for idx, person in enumerate(people, start=1):
            self.stdout.write(f'\n[{idx}/{total_people}] Processing: {person.display_name} ({person.last_name}, {person.first_name})')
            
            # Find matching PersistentCandidates by last name
            # PersistentCandidate.display_name format is "LASTNAME, First Names"
            matches = self.find_matching_persistent_candidates(person, skip_linked)
            
            if not matches:
                self.stdout.write(self.style.WARNING('  No matching PersistentCandidates found.'))
                skipped_count += 1
                continue
            
            if len(matches) == 1:
                # Single match - ask for confirmation
                persistent_candidate = matches[0]
                if self.confirm_single_match(person, persistent_candidate):
                    self.link_person_to_candidate(person, persistent_candidate)
                    linked_count += 1
                else:
                    skipped_count += 1
            else:
                # Multiple matches - show list and ask which one
                selected = self.select_from_multiple_matches(person, matches)
                if selected:
                    self.link_person_to_candidate(person, selected)
                    linked_count += 1
                else:
                    skipped_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'\n=== Summary ==='))
        self.stdout.write(f'Linked: {linked_count}')
        self.stdout.write(f'Skipped: {skipped_count}')
        self.stdout.write(f'Total processed: {total_people}')

    def find_matching_persistent_candidates(self, person, skip_linked):
        """
        Find PersistentCandidates that match the person's last name.
        Returns a list of PersistentCandidate objects.
        """
        # Get all PersistentCandidates where display_name starts with the last name
        # Format is "LASTNAME, First Names"
        candidates = PersistentCandidate.objects.filter(
            display_name__istartswith=f"{person.last_name},"
        )
        
        if skip_linked:
            candidates = candidates.filter(person__isnull=True)
        
        return list(candidates)

    def confirm_single_match(self, person, persistent_candidate):
        """
        Ask user to confirm a single match.
        Returns True if confirmed, False otherwise.
        """
        self.stdout.write(f'\n  Found match:')
        self.stdout.write(f'    Person: {person.display_name} ({person.last_name}, {person.first_name})')
        self.stdout.write(f'    PersistentCandidate: {persistent_candidate.display_name}')
        
        if persistent_candidate.person:
            self.stdout.write(self.style.WARNING(
                f'    WARNING: This PersistentCandidate is already linked to: {persistent_candidate.person.display_name}'
            ))
        
        while True:
            try:
                response = input('\n  Link this Person to this PersistentCandidate? (y/n): ').strip().lower()
                if response in ('y', 'yes'):
                    return True
                elif response in ('n', 'no'):
                    return False
                else:
                    self.stdout.write(self.style.ERROR('  Please enter "y" or "n"'))
            except (EOFError, KeyboardInterrupt):
                raise CommandError('\nOperation cancelled by user.')

    def select_from_multiple_matches(self, person, matches):
        """
        Show list of multiple matches and ask user to select one.
        Returns the selected PersistentCandidate or None.
        """
        self.stdout.write(f'\n  Found {len(matches)} possible matches:')
        match_list = []
        for idx, candidate in enumerate(matches, start=1):
            status = ''
            if candidate.person:
                status = f' [ALREADY LINKED TO: {candidate.person.display_name}]'
            self.stdout.write(f'    {idx}. {candidate.display_name}{status}')
            match_list.append(candidate)
        
        self.stdout.write(f'    {len(matches) + 1}. None of the above')
        
        while True:
            try:
                choice = input(f'\n  Select a match (1-{len(matches) + 1}): ').strip()
                choice_num = int(choice)
                
                if 1 <= choice_num <= len(matches):
                    selected = match_list[choice_num - 1]
                    if selected.person:
                        self.stdout.write(self.style.WARNING(
                            f'  WARNING: This PersistentCandidate is already linked to: {selected.person.display_name}'
                        ))
                        confirm = input('  Overwrite existing link? (y/n): ').strip().lower()
                        if confirm not in ('y', 'yes'):
                            return None
                    return selected
                elif choice_num == len(matches) + 1:
                    return None
                else:
                    self.stdout.write(self.style.ERROR(
                        f'  Please enter a number between 1 and {len(matches) + 1}'
                    ))
            except ValueError:
                self.stdout.write(self.style.ERROR('  Please enter a valid number'))
            except (EOFError, KeyboardInterrupt):
                raise CommandError('\nOperation cancelled by user.')

    def link_person_to_candidate(self, person, persistent_candidate):
        """
        Link a Person to a PersistentCandidate.
        """
        if persistent_candidate.person and persistent_candidate.person != person:
            self.stdout.write(self.style.WARNING(
                f'  Overwriting existing link from {persistent_candidate.person.display_name} to {person.display_name}'
            ))
        
        persistent_candidate.person = person
        persistent_candidate.save()
        self.stdout.write(self.style.SUCCESS(
            f'  ✓ Linked {person.display_name} to {persistent_candidate.display_name}'
        ))

    def is_person_linked(self, person):
        """
        Check if a Person is already linked to any PersistentCandidate.
        Returns True if linked, False otherwise.
        """
        return PersistentCandidate.objects.filter(person=person).exists()

    def list_duplicates(self):
        """
        List people who are not linked and have multiple matching PersistentCandidates.
        """
        self.stdout.write(self.style.SUCCESS(f'\n=== Finding People with Multiple Matches ===\n'))
        
        people = Person.objects.all().order_by('last_name', 'first_name')
        duplicates = []
        
        for person in people:
            # Skip if person is already linked
            if self.is_person_linked(person):
                continue
            
            # Find matching PersistentCandidates
            matches = self.find_matching_persistent_candidates(person, skip_linked=False)
            
            # Only include if there are multiple matches
            if len(matches) > 1:
                duplicates.append((person, matches))
        
        if not duplicates:
            self.stdout.write(self.style.SUCCESS('No people found with multiple matches who are not already linked.'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'Found {len(duplicates)} people with multiple matches:\n'))
        
        for idx, (person, matches) in enumerate(duplicates, start=1):
            self.stdout.write(f'\n{idx}. {person.display_name} ({person.last_name}, {person.first_name})')
            self.stdout.write(f'   Matches ({len(matches)}):')
            for match in matches:
                status = ''
                if match.person:
                    status = f' [ALREADY LINKED TO: {match.person.display_name}]'
                self.stdout.write(f'     - {match.display_name}{status}')

