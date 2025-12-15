import csv
from datetime import datetime
from django.core.management.base import BaseCommand
from wts_app.models.people import FinancialInterestSnapshot, Person

CSV_FILE = "migration/financial_interest_snapshots.csv"


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


class Command(BaseCommand):
    help = "Migrate financial interest snapshots from legacy CSV"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default=CSV_FILE,
            help="Path to CSV file to use (default: migration/financial_interest_snapshots.csv)",
        )

    def handle(self, *args, **options):
        path = options["csv"]
        created = 0
        skipped = 0

        with open(path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                legacy_id = row.get("legacy_id")
                if not legacy_id:
                    self.stdout.write(self.style.WARNING("Skipping row without legacy_id"))
                    skipped += 1
                    continue

                try:
                    legacy_id_int = int(legacy_id)
                except Exception:
                    self.stdout.write(self.style.WARNING(f"Skipping row with invalid legacy_id: {legacy_id!r}"))
                    skipped += 1
                    continue

                # Skip if already migrated
                if FinancialInterestSnapshot.objects.filter(legacy_id=legacy_id_int).exists():
                    skipped += 1
                    continue

                person = None
                person_legacy_id = row.get("legacy_person_id")
                if person_legacy_id:
                    try:
                        person = Person.objects.get(legacy_id=int(person_legacy_id))
                    except Person.DoesNotExist:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Could not find Person with legacy_id={person_legacy_id} for snapshot {legacy_id_int}, skipping."
                            )
                        )
                        skipped += 1
                        continue

                snapshot = FinancialInterestSnapshot(
                    legacy_id=legacy_id_int,
                    as_at=parse_date(row.get("as_at")),
                    person=person,
                    document=None,  # document not available in source CSV
                )
                snapshot.save()
                created += 1
                self.stdout.write(self.style.SUCCESS(f"Created FinancialInterestSnapshot {legacy_id_int} ({person})"))

        self.stdout.write(self.style.SUCCESS(f"Done. Created {created} snapshots, skipped {skipped}."))

