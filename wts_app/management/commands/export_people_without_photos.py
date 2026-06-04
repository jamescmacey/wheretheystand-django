"""
Management command to export people who have no profile picture to a CSV file.
"""

import csv
import os

from django.core.management.base import BaseCommand, CommandError

from wts_app.models import Person

DEFAULT_OUTPUT_CSV = "migration/people_without_photos.csv"

FIELDNAMES = [
    "id",
    "first_name",
    "last_name",
    "display_name",
    "slug",
    "legacy_id",
    "parliament_api_id",
    "cached_description",
]


class Command(BaseCommand):
    help = "Export a CSV list of people who have no profile picture (photo is null)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-csv",
            default=DEFAULT_OUTPUT_CSV,
            help=f"Path to output CSV (default: {DEFAULT_OUTPUT_CSV}).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite output CSV if it already exists.",
        )

    def handle(self, *args, **options):
        output_csv = options["output_csv"]
        overwrite = options["overwrite"]

        if os.path.exists(output_csv) and not overwrite:
            raise CommandError(
                f"Output CSV already exists: {output_csv}. Use --overwrite to replace it."
            )

        people = Person.objects.filter(photo__isnull=True).order_by(
            "last_name", "first_name"
        )
        count = people.count()

        output_dir = os.path.dirname(output_csv)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(output_csv, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
            writer.writeheader()
            for person in people:
                writer.writerow(
                    {
                        "id": str(person.id),
                        "first_name": person.first_name,
                        "last_name": person.last_name,
                        "display_name": person.display_name,
                        "slug": person.slug or "",
                        "legacy_id": person.legacy_id if person.legacy_id is not None else "",
                        "parliament_api_id": person.parliament_api_id or "",
                        "cached_description": person.cached_description or "",
                    }
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Created CSV: {output_csv} ({count} people without a profile picture)"
            )
        )
