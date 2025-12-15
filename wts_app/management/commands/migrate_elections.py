import csv
from datetime import datetime, time
from django.core.management.base import BaseCommand
from wts_app.models.elections import Election

CSV_FILE = "migration/elections.csv"

class Command(BaseCommand):
    help = "Migrate elections from legacy CSV file"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default=CSV_FILE,
            help="Path to elections CSV file (default: migration/elections.csv)"
        )

    def handle(self, *args, **options):
        from zoneinfo import ZoneInfo  # only works in Python 3.9+
        csv_path = options["csv"]

        with open(csv_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            created = 0
            skipped = 0
            for row in reader:
                slug = (row.get("slug") or "").strip()
                if not slug:
                    self.stdout.write(self.style.WARNING("Skipping row with empty slug"))
                    skipped += 1
                    continue

                # Check if already exists
                if Election.objects.filter(slug=slug).exists():
                    self.stdout.write(f"Election with slug '{slug}' already exists, skipping.")
                    skipped += 1
                    continue

                name = (row.get("name") or "").strip()
                election_type = (row.get("election_type") or "g").strip()
                polling_date_str = (row.get("polling_date") or "").strip()
                if not polling_date_str:
                    self.stdout.write(self.style.WARNING(f"Skipping row with empty polling_date (slug={slug})"))
                    skipped += 1
                    continue
                try:
                    polling_date = datetime.strptime(polling_date_str, "%Y-%m-%d").date()
                except Exception as e:
                    self.stdout.write(self.style.WARNING(
                        f"Skipping row with invalid polling_date {polling_date_str!r} (slug={slug}): {e}"))
                    skipped += 1
                    continue

                # Set 7pm Pacific/Auckland for polls close
                polls_close_naive = datetime.combine(polling_date, time(hour=19, minute=0))
                try:
                    auckland_tz = ZoneInfo("Pacific/Auckland")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f"Could not get Pacific/Auckland timezone: {e}"))
                    return
                polls_close = polls_close_naive.replace(tzinfo=auckland_tz)

                election = Election(
                    polling_date=polling_date,
                    polls_close=polls_close,
                    election_type=election_type,
                    name=name,
                    slug=slug,
                )
                election.save()
                created += 1
                self.stdout.write(self.style.SUCCESS(f"Created Election: {name} ({slug})"))

            self.stdout.write(self.style.SUCCESS(
                f"Done. Created {created} elections, skipped {skipped}."
            ))
