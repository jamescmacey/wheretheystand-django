"""
Management command to cache people's descriptions and colours.

Updates cached_description and cached_colour for all people based on their
current or most recent ParliamentaryAffiliation and PartyAffiliation.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from wts_app.models import Person, ParliamentaryAffiliation, PartyAffiliation


class Command(BaseCommand):
    help = 'Updates cached_description and cached_colour for all people based on their current or most recent affiliations.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without actually updating the database.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.now().date()
        
        updated_count = 0
        skipped_count = 0
        
        # Get all people
        people = Person.objects.all()
        
        for person in people:
            # Find current or most recent ParliamentaryAffiliation
            # Current: end_date is None or >= today
            # Most recent: order by sworn_date or elected_date descending, take first
            current_parliamentary = ParliamentaryAffiliation.objects.filter(
                person=person
            ).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=today)
            ).order_by('-sworn_date', '-elected_date').first()
            
            # If no current, get most recent
            if not current_parliamentary:
                current_parliamentary = ParliamentaryAffiliation.objects.filter(
                    person=person
                ).order_by('-sworn_date', '-elected_date').first()
            
            if not current_parliamentary:
                # No parliamentary affiliation at all
                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(f"Would skip {person.display_name}: No parliamentary affiliation")
                    )
                skipped_count += 1
                continue
            
            # Determine if current or former
            is_current = current_parliamentary.end_date is None or current_parliamentary.end_date >= today
            
            # Determine if electorate or list MP
            is_electorate = current_parliamentary.electorate is not None
            
            # Find party affiliation that overlaps with the parliamentary affiliation
            # Use sworn_date or elected_date as the start, and end_date as the end
            par_start = current_parliamentary.sworn_date or current_parliamentary.elected_date
            par_end = current_parliamentary.end_date
            
            # Find party affiliation that overlaps with parliamentary affiliation period
            party_affiliation = None
            if par_start:
                # Party affiliation overlaps if:
                # - It starts before or on the parliamentary affiliation end (or before today if no end)
                # - It ends after or on the parliamentary affiliation end (or has no end)
                check_end = par_end if par_end else today
                
                party_affiliations = PartyAffiliation.objects.filter(
                    person=person,
                    start_date__lte=check_end,
                ).filter(
                    Q(end_date__isnull=True) | Q(end_date__gte=check_end)
                ).order_by('-start_date')
                
                # Take the one that starts closest to the parliamentary affiliation start
                party_affiliation = party_affiliations.first()
            
            
            # Build description
            description = None
            colour = None
            
            if party_affiliation:
                party_name = party_affiliation.party.display_name
                colour = party_affiliation.party.color
            else:
                party_name = "Independent"
                colour = None
            
            # Build description based on format examples:
            # - "Labour MP for Ilam"
            # - "Labour List MP"
            # - "Independent MP for Auckland"
            # - "Independent List MP"
            # - "Former National MP for Auckland"
            # - "Former National List MP"
            # - "Former Independent List MP"
            
            prefix = "Former " if not is_current else ""
            
            if is_electorate:
                electorate_name = current_parliamentary.electorate.name
                description = f"{prefix}{party_name} MP for {electorate_name}"
            else:
                description = f"{prefix}{party_name} List MP"
            
            # Update person
            if dry_run:
                old_desc = person.cached_description or "(none)"
                old_colour = person.cached_colour or "(none)"
                self.stdout.write(
                    f"Would update {person.display_name}:\n"
                    f"  Description: {old_desc} -> {description}\n"
                    f"  Colour: {old_colour} -> {colour or '(none)'}"
                )
            else:
                person.cached_description = description
                person.cached_colour = colour
                person.save(update_fields=['cached_description', 'cached_colour'])
                self.stdout.write(
                    self.style.SUCCESS(f"Updated {person.display_name}: {description}")
                )
            
            updated_count += 1
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run complete. Would update {updated_count} people, skipped {skipped_count}."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nDone. Updated {updated_count} people, skipped {skipped_count}."
                )
            )
