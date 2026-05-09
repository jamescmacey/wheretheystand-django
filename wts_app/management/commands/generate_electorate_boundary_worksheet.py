import argparse
import csv
import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils.dateparse import parse_date

from wts_app.models import Electorate


def _parse_electorate_type_arg(value):
    t = value.strip().lower()
    if t == "all":
        return None
    if t == "general":
        return "general"
    if t in ("maori", "māori"):
        return "maori"
    raise argparse.ArgumentTypeError(
        "must be one of: all, general, māori (maori accepted without macron)"
    )


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
            "--electorate-type",
            type=_parse_electorate_type_arg,
            required=True,
            metavar="TYPE",
            help='Which electorates to suggest: "all", "general", or "māori" (DB value maori).',
        )
        parser.add_argument(
            "--date",
            required=True,
            help=(
                "Reference date (YYYY-MM-DD). Includes electorates with valid_from on or "
                "before this date that are not ended before this date (valid_to null or ≥ date)."
            ),
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
        electorate_type = options["electorate_type"]
        ref_date = parse_date(options["date"])
        if ref_date is None:
            raise CommandError(
                f"Invalid --date {options['date']!r}. Use YYYY-MM-DD."
            )
        output_csv = options["output_csv"]
        overwrite = options["overwrite"]

        if not os.path.exists(json_file):
            raise CommandError(f"JSON file does not exist: {json_file}")
        if os.path.exists(output_csv) and not overwrite:
            raise CommandError(
                f"Output CSV already exists: {output_csv}. Use --overwrite to replace it."
            )

        geometry_count = self._load_geometry_count(json_file)
        suggested_slugs = self._load_electorate_slugs_from_db(electorate_type, ref_date)
        if not suggested_slugs:
            type_label = "all types" if electorate_type is None else electorate_type
            raise CommandError(
                f"No electorates with slugs found for type={type_label!r} "
                f"valid on {ref_date.isoformat()}. Load or adjust data before generating the worksheet."
            )

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
            "Fill in electorate_slug values, then run upload_electorate_boundaries "
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

    def _load_electorate_slugs_from_db(self, electorate_type, ref_date):
        qs = Electorate.objects.filter(
            valid_from__lte=ref_date,
        ).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=ref_date))
        if electorate_type is not None:
            qs = qs.filter(electorate_type=electorate_type)
        qs = qs.exclude(slug__isnull=True).exclude(slug="").order_by("name")
        return list(qs.values_list("slug", flat=True))
