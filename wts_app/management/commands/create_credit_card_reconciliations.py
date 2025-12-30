import csv
import os
import re
from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from wts_app.models.credit_card_expenses import CreditCardReconciliation
from wts_app.models.people import Person
from wts_app.models.documents import File


class Command(BaseCommand):
    help = "Create CreditCardReconciliation objects from a CSV file with file IDs, dates, and person names"

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to CSV file with columns: file_id, start_date, end_date, file_name",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run without actually creating records (for testing)",
        )

    def extract_person_name(self, file_name):
        """
        Extract person name from file_name.
        Pattern: "... for [Person Name] for [Date Range]"
        Returns the person name between the two 'for' occurrences.
        """
        # Find all occurrences of " for " (with spaces)
        pattern = r'\s+for\s+'
        matches = list(re.finditer(pattern, file_name, re.IGNORECASE))
        
        if len(matches) < 2:
            return None
        
        # Get text between first and second " for "
        start_pos = matches[0].end()
        end_pos = matches[1].start()
        person_name = file_name[start_pos:end_pos].strip()
        
        return person_name

    def find_person_by_name(self, name):
        """
        Find a Person by name, trying multiple matching strategies.
        Returns Person object or None if not found.
        """
        if not name:
            return None
        
        # Try exact match on display_name
        person = Person.objects.filter(display_name__iexact=name).first()
        if person:
            return person
        
        # Try matching by first and last name
        # Split name into parts
        name_parts = name.split()
        if len(name_parts) >= 2:
            # Try "First Last" format
            first_name = name_parts[0]
            last_name = " ".join(name_parts[1:])
            person = Person.objects.filter(
                first_name__iexact=first_name,
                last_name__iexact=last_name
            ).first()
            if person:
                return person
            
            # Try "Last, First" format
            if "," in name:
                parts = [p.strip() for p in name.split(",")]
                if len(parts) == 2:
                    last_name = parts[0]
                    first_name = parts[1]
                    person = Person.objects.filter(
                        first_name__iexact=first_name,
                        last_name__iexact=last_name
                    ).first()
                    if person:
                        return person
        
        # Try case-insensitive contains match on display_name
        person = Person.objects.filter(display_name__icontains=name).first()
        if person:
            return person
        
        # Try matching last name only
        if len(name_parts) > 0:
            last_name = name_parts[-1]
            person = Person.objects.filter(last_name__iexact=last_name).first()
            if person:
                return person
        
        return None

    def handle(self, *args, **options):
        csv_path = options["csv_file"]
        dry_run = options["dry_run"]

        if not os.path.exists(csv_path):
            raise CommandError(f"CSV file does not exist at {csv_path}")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No records will be created"))

        processed = 0
        created = 0
        skipped = 0
        errors = 0
        not_found_persons = []
        not_found_files = []

        # Read the CSV and process each row
        with open(csv_path, mode="r", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            
            for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                file_id = row.get("file_id", "").strip()
                start_date_str = row.get("start_date", "").strip()
                end_date_str = row.get("end_date", "").strip()
                file_name = row.get("file_name", "").strip()

                # Skip if required fields are missing
                if not file_id or not start_date_str or not end_date_str or not file_name:
                    skipped += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Row {row_num}: Skipping - missing required fields (file_id, start_date, end_date, or file_name)"
                        )
                    )
                    continue

                processed += 1

                try:
                    # Parse dates
                    try:
                        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                    except ValueError as e:
                        errors += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f"Row {row_num}: Invalid date format - {e}"
                            )
                        )
                        continue

                    # Get File object
                    try:
                        file_obj = File.objects.get(id=file_id)
                    except File.DoesNotExist:
                        errors += 1
                        not_found_files.append((row_num, file_id, file_name))
                        self.stdout.write(
                            self.style.ERROR(
                                f"Row {row_num}: File not found with ID {file_id}"
                            )
                        )
                        continue

                    # Extract person name from file_name
                    person_name = self.extract_person_name(file_name)
                    if not person_name:
                        errors += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f"Row {row_num}: Could not extract person name from file_name: {file_name}"
                            )
                        )
                        continue

                    # Find Person
                    person = self.find_person_by_name(person_name)
                    if not person:
                        errors += 1
                        not_found_persons.append((row_num, person_name, file_name))
                        self.stdout.write(
                            self.style.ERROR(
                                f"Row {row_num}: Person not found for name '{person_name}' (from file: {file_name})"
                            )
                        )
                        continue

                    # Check if reconciliation already exists
                    existing = CreditCardReconciliation.objects.filter(
                        person=person,
                        file=file_obj,
                        start_date=start_date,
                        end_date=end_date
                    ).first()

                    if existing:
                        skipped += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"Row {row_num}: Reconciliation already exists (ID: {existing.id})"
                            )
                        )
                        continue

                    # Create CreditCardReconciliation
                    if not dry_run:
                        reconciliation = CreditCardReconciliation.objects.create(
                            person=person,
                            file=file_obj,
                            start_date=start_date,
                            end_date=end_date
                        )
                        created += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Row {row_num}: Created reconciliation for {person.display_name} "
                                f"({start_date} to {end_date}) - ID: {reconciliation.id}"
                            )
                        )
                    else:
                        created += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Row {row_num}: [DRY RUN] Would create reconciliation for {person.display_name} "
                                f"({start_date} to {end_date})"
                            )
                        )

                except Exception as e:
                    errors += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"Row {row_num}: Error processing row - {e}"
                        )
                    )

        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*80}\n"
                f"SUMMARY\n"
                f"{'='*80}\n"
                f"Total rows processed: {processed}\n"
                f"Reconciliations created: {created}\n"
                f"Rows skipped: {skipped}\n"
                f"Errors: {errors}\n"
            )
        )

        # Report persons not found
        if not_found_persons:
            self.stdout.write(
                self.style.WARNING(
                    f"\nPersons not found ({len(not_found_persons)}):"
                )
            )
            for row_num, person_name, file_name in not_found_persons:
                self.stdout.write(
                    f"  Row {row_num}: '{person_name}' (from: {file_name})"
                )

        # Report files not found
        if not_found_files:
            self.stdout.write(
                self.style.WARNING(
                    f"\nFiles not found ({len(not_found_files)}):"
                )
            )
            for row_num, file_id, file_name in not_found_files:
                self.stdout.write(
                    f"  Row {row_num}: File ID {file_id} (file_name: {file_name})"
                )

