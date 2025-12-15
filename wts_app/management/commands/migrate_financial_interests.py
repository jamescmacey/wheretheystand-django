import csv
from django.core.management.base import BaseCommand
from django.db import transaction
from wts_app.models.people import FinancialInterest, FinancialInterestSnapshot

CSV_FILE = "migration/financial_interests.csv"
BATCH_SIZE = 1000  # Process in batches to avoid memory issues


class Command(BaseCommand):
    help = "Migrate financial interests from legacy CSV"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default=CSV_FILE,
            help="Path to CSV file to use (default: migration/financial_interests.csv)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=BATCH_SIZE,
            help=f"Number of records to process per batch (default: {BATCH_SIZE})",
        )

    def handle(self, *args, **options):
        path = options["csv"]
        batch_size = options["batch_size"]
        created = 0
        skipped = 0

        # Delete all existing financial interests
        self.stdout.write("Deleting all existing financial interests...")
        FinancialInterest.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Deleted all existing financial interests"))

        # Pre-load all snapshots into a dictionary for O(1) lookup
        self.stdout.write("Pre-loading snapshots...")
        snapshots = {
            s.legacy_id: s
            for s in FinancialInterestSnapshot.objects.all().select_related()
        }
        self.stdout.write(f"Loaded {len(snapshots)} snapshots")

        # Pre-load existing interests to check for duplicates
        # Create a set of (snapshot_id, interest_type, description) tuples
        self.stdout.write("Pre-loading existing interests...")
        existing_interests = set(
            FinancialInterest.objects.values_list(
                "snapshot_id", "interest_type", "description"
            )
        )
        self.stdout.write(f"Found {len(existing_interests)} existing interests")

        # Read all rows first to prepare for bulk operations
        self.stdout.write("Reading CSV file...")
        rows_to_process = []
        with open(path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                rows_to_process.append(row)

        self.stdout.write(f"Processing {len(rows_to_process)} rows in batches of {batch_size}...")

        # Process in batches
        for batch_start in range(0, len(rows_to_process), batch_size):
            batch_end = min(batch_start + batch_size, len(rows_to_process))
            batch = rows_to_process[batch_start:batch_end]
            
            self.stdout.write(f"Processing batch {batch_start // batch_size + 1} (rows {batch_start + 1}-{batch_end})...")
            
            interests_to_create = []
            batch_created = 0
            batch_skipped = 0

            for row in batch:
                legacy_snapshot_id = row.get("legacy_snapshot_id")
                if not legacy_snapshot_id:
                    batch_skipped += 1
                    self.stdout.write(self.style.WARNING(f"Skipping row {batch_start + batch_skipped}: missing legacy_snapshot_id"))
                    continue

                try:
                    legacy_snapshot_id = int(legacy_snapshot_id)
                except (ValueError, TypeError):
                    batch_skipped += 1
                    self.stdout.write(self.style.WARNING(f"Skipping row {batch_start + batch_skipped}: invalid legacy_snapshot_id={legacy_snapshot_id!r}"))
                    continue

                snapshot = snapshots.get(legacy_snapshot_id)
                if not snapshot:
                    batch_skipped += 1
                    self.stdout.write(self.style.WARNING(f"Skipping row {batch_start + batch_skipped}: snapshot legacy_id={legacy_snapshot_id} not found"))
                    continue

                interest_type = row.get("interest_type")
                description = row.get("description") or ""
                if not interest_type or not description:
                    batch_skipped += 1
                    self.stdout.write(self.style.WARNING(f"Skipping row {batch_start + batch_skipped}: missing interest_type/description (snapshot legacy_id={legacy_snapshot_id})"))
                    continue

                # Check if this interest already exists
                interest_key = (snapshot.id, interest_type, description)


                # Create the interest object (don't save yet)
                interest = FinancialInterest(
                    snapshot=snapshot,
                    interest_type=interest_type,
                    description=description,
                    nzbn=row.get("nzbn") or None,
                    nzbn_entity_classifications=row.get("nzbn_entity_classifications") or None,
                    nzbn_entity_name=row.get("nzbn_entity_name") or None,
                    nzbn_entity_type_code=row.get("nzbn_entity_type_code") or None,
                    nzbn_entity_type_desc=row.get("nzbn_entity_type_desc") or None,
                    nzbn_entity_classifications_descs=row.get("nzbn_entity_classifications_descs") or None,
                )
                interests_to_create.append(interest)
                # Add to existing set to avoid duplicates within the batch
                existing_interests.add(interest_key)

            # Bulk create the batch in a transaction
            if interests_to_create:
                with transaction.atomic():
                    FinancialInterest.objects.bulk_create(
                        interests_to_create,
                        ignore_conflicts=True  # In case of race conditions
                    )
                batch_created = len(interests_to_create)
                created += batch_created

            skipped += batch_skipped
            self.stdout.write(
                f"  Batch complete: {batch_created} created, {batch_skipped} skipped"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created {created} FinancialInterests, skipped {skipped}."
            )
        )

