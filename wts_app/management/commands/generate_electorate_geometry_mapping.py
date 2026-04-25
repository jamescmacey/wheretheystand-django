import csv
import json
import os

from django.core.management.base import BaseCommand, CommandError

from wts_app.models import Electorate


class Command(BaseCommand):
    help = (
        "Generate a mapping worksheet CSV for geometry index -> electorate slug "
        "from a GeometryCollection file."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--json-file",
            default="migration/general-electorates-2020.json",
            help="Path to GeometryCollection JSON.",
        )
        parser.add_argument(
            "--electorates-csv",
            default="migration/electorates.csv",
            help="Path to electorates CSV fallback for suggested slugs when DB is unavailable.",
        )
        parser.add_argument(
            "--output-csv",
            default="migration/electorate_geometry_mapping.csv",
            help="Path to output worksheet CSV.",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite output CSV if it already exists.",
        )

    def handle(self, *args, **options):
        json_file = options["json_file"]
        electorates_csv = options["electorates_csv"]
        output_csv = options["output_csv"]
        overwrite = options["overwrite"]

        if not os.path.exists(json_file):
            raise CommandError(f"JSON file does not exist: {json_file}")
        if not os.path.exists(electorates_csv):
            raise CommandError(f"Electorates CSV does not exist: {electorates_csv}")
        if os.path.exists(output_csv) and not overwrite:
            raise CommandError(
                f"Output CSV already exists: {output_csv}. Use --overwrite to replace it."
            )

        geometry_count = self._load_geometry_count(json_file)
        suggested_slugs = self._load_current_electorate_slugs_from_db()
        if not suggested_slugs:
            self.stdout.write(
                self.style.WARNING(
                    "No current electorates found in DB, falling back to electorates CSV."
                )
            )
            suggested_slugs = self._load_general_electorate_slugs(electorates_csv)

        output_dir = os.path.dirname(output_csv)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(output_csv, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "geometry_index",
                    "electorate_slug",
                    "suggested_slug",
                    "notes",
                ],
            )
            writer.writeheader()

            for index in range(geometry_count):
                suggested_slug = suggested_slugs[index] if index < len(suggested_slugs) else ""
                writer.writerow(
                    {
                        "geometry_index": index,
                        "electorate_slug": "",
                        "suggested_slug": suggested_slug,
                        "notes": "",
                    }
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Created worksheet CSV: {output_csv} (rows: {geometry_count})"
            )
        )
        self.stdout.write(
            "Fill in electorate_slug values, then run migrate_electorate_boundaries "
            f"with --mapping-csv {output_csv}"
        )

    def _load_geometry_count(self, json_file):
        with open(json_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or data.get("type") != "GeometryCollection":
            raise CommandError(f"{json_file} is not a GeometryCollection JSON file.")
        geometries = data.get("geometries") or []
        if not geometries:
            raise CommandError(f"{json_file} has no geometries.")
        return len(geometries)

    def _load_general_electorate_slugs(self, electorates_csv):
        slugs = []
        with open(electorates_csv, "r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if (row.get("type") or "").strip().lower() != "general":
                    continue
                slug = (row.get("slug") or "").strip()
                if slug:
                    slugs.append(slug)
        return slugs

    def _load_current_electorate_slugs_from_db(self):
        rows = (
            Electorate.objects.filter(status="current", electorate_type="general")
            .exclude(slug__isnull=True)
            .exclude(slug="")
            .order_by("name")
            .values_list("slug", flat=True)
        )
        return list(rows)
