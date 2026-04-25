import csv
import json
import os
from datetime import datetime

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from wts_app.models import Electorate, ElectorateBoundary, ElectorateBoundarySet
from wts_app.models.documents import CopyrightParty, Document, File, Licence


class Command(BaseCommand):
    help = (
        "Create electorate boundary records from full and simplified GeometryCollection "
        "GeoJSON files in the migration folder."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--full-json",
            default="migration/general-electorates-2020.json",
            help="Path to full-resolution GeometryCollection JSON.",
        )
        parser.add_argument(
            "--simplified-json",
            default="migration/general-electorates-2020-simplified.json",
            help="Path to simplified GeometryCollection JSON.",
        )
        parser.add_argument(
            "--mapping-csv",
            default="",
            help=(
                "Optional path to mapping CSV with columns: geometry_index,electorate_slug. "
                "If omitted, use --use-order-mapping."
            ),
        )
        parser.add_argument(
            "--use-order-mapping",
            action="store_true",
            help=(
                "Map geometries to electorates by order of rows in migration/electorates.csv "
                "where type=general. Only use when file ordering is known to match."
            ),
        )
        parser.add_argument(
            "--electorates-csv",
            default="migration/electorates.csv",
            help="Path to electorates CSV used for --use-order-mapping.",
        )
        parser.add_argument(
            "--valid-from",
            required=True,
            help="Boundary set valid-from date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--document-name",
            default="General electorates boundary data",
            help="Document name for uploaded boundary files.",
        )
        parser.add_argument(
            "--document-description",
            default="Generated electorate boundary files (full and simplified) for map rendering.",
            help="Document description.",
        )
        parser.add_argument(
            "--copyright-owner",
            default="",
            help="Optional copyright owner name.",
        )
        parser.add_argument(
            "--licence-name",
            default="",
            help="Optional licence name.",
        )
        parser.add_argument(
            "--licence-grantor",
            default="",
            help="Optional licence grantor name.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate mapping and report actions without writing records.",
        )

    def handle(self, *args, **options):
        full_path = options["full_json"]
        simplified_path = options["simplified_json"]
        mapping_csv = options["mapping_csv"]
        use_order_mapping = options["use_order_mapping"]
        electorates_csv = options["electorates_csv"]
        valid_from = self._parse_date(options["valid_from"])
        dry_run = options["dry_run"]

        if not os.path.exists(full_path):
            raise CommandError(f"Full JSON file does not exist: {full_path}")
        if not os.path.exists(simplified_path):
            raise CommandError(f"Simplified JSON file does not exist: {simplified_path}")
        if mapping_csv and not os.path.exists(mapping_csv):
            raise CommandError(f"Mapping CSV does not exist: {mapping_csv}")
        if not mapping_csv and not use_order_mapping:
            raise CommandError(
                "Provide --mapping-csv or pass --use-order-mapping."
            )

        full_geometries = self._load_geometries(full_path)
        simplified_geometries = self._load_geometries(simplified_path)
        if len(full_geometries) != len(simplified_geometries):
            raise CommandError(
                "Full and simplified files have different geometry counts: "
                f"{len(full_geometries)} vs {len(simplified_geometries)}"
            )

        mapping_rows = (
            self._load_mapping_csv(mapping_csv)
            if mapping_csv
            else self._build_order_mapping(electorates_csv, len(full_geometries))
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Running in dry-run mode. No changes will be saved."))

        document = self._get_or_create_document(
            options["document_name"],
            options["document_description"],
            dry_run=dry_run,
        )
        boundary_set = self._get_or_create_boundary_set(document, valid_from, dry_run=dry_run)

        copyright_owner = self._get_or_create_copyright_party(options["copyright_owner"], dry_run=dry_run)
        licence = self._get_or_create_licence(options["licence_name"], dry_run=dry_run)
        licence_grantor = self._get_or_create_copyright_party(options["licence_grantor"], dry_run=dry_run)

        created = 0
        updated = 0

        for mapping in mapping_rows:
            geometry_index = mapping["geometry_index"]
            electorate_slug = mapping["electorate_slug"]

            electorate = Electorate.objects.filter(slug=electorate_slug).first()
            if not electorate:
                raise CommandError(f"Electorate not found for slug: {electorate_slug}")

            full_geometry = full_geometries[geometry_index]
            simplified_geometry = simplified_geometries[geometry_index]

            full_geojson = self._to_feature_collection(full_geometry, electorate)
            simplified_geojson = self._to_feature_collection(simplified_geometry, electorate)

            if dry_run:
                self.stdout.write(
                    f"[DRY RUN] Would create/update boundary for {electorate.slug} "
                    f"(geometry index {geometry_index})"
                )
                continue

            full_file = self._create_geojson_file(
                document=document,
                filename=f"{electorate.slug}-full.geojson",
                display_name=f"{electorate.name} boundary (full)",
                payload=full_geojson,
                copyright_owner=copyright_owner,
                licence=licence,
                licence_grantor=licence_grantor,
            )
            simplified_file = self._create_geojson_file(
                document=document,
                filename=f"{electorate.slug}-simplified.geojson",
                display_name=f"{electorate.name} boundary (simplified)",
                payload=simplified_geojson,
                copyright_owner=copyright_owner,
                licence=licence,
                licence_grantor=licence_grantor,
            )

            boundary, was_created = ElectorateBoundary.objects.update_or_create(
                electorate=electorate,
                boundary_set=boundary_set,
                defaults={
                    "shape": full_file,
                    "simplified_shape": simplified_file,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"{'Created' if was_created else 'Updated'} boundary: {electorate.slug}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Processed {len(mapping_rows)} records. "
                f"Created: {created}, Updated: {updated}."
            )
        )

    def _load_geometries(self, path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        if not isinstance(data, dict) or data.get("type") != "GeometryCollection":
            raise CommandError(f"{path} is not a GeometryCollection JSON file.")

        geometries = data.get("geometries") or []
        if not geometries:
            raise CommandError(f"{path} contains no geometries.")
        return geometries

    def _load_mapping_csv(self, path):
        rows = []
        with open(path, "r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                rows.append(
                    {
                        "geometry_index": int(row["geometry_index"]),
                        "electorate_slug": row["electorate_slug"].strip(),
                    }
                )
        self._validate_mapping(rows)
        return rows

    def _build_order_mapping(self, electorates_csv, geometry_count):
        if not os.path.exists(electorates_csv):
            raise CommandError(f"Electorates CSV does not exist: {electorates_csv}")

        rows = []
        with open(electorates_csv, "r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            general_rows = [r for r in reader if r.get("type", "").strip().lower() == "general"]

        if len(general_rows) != geometry_count:
            raise CommandError(
                "General electorate row count does not match geometry count. "
                f"general_rows={len(general_rows)}, geometries={geometry_count}. "
                "Provide --mapping-csv for explicit mapping."
            )

        for idx, row in enumerate(general_rows):
            slug = (row.get("slug") or "").strip()
            if not slug:
                raise CommandError(f"Missing slug in electorates CSV at general row index {idx}.")
            rows.append({"geometry_index": idx, "electorate_slug": slug})
        return rows

    def _validate_mapping(self, rows):
        seen_indices = set()
        for row in rows:
            idx = row["geometry_index"]
            slug = row["electorate_slug"]
            if idx in seen_indices:
                raise CommandError(f"Duplicate geometry_index in mapping: {idx}")
            seen_indices.add(idx)
            if not slug:
                raise CommandError("Mapping row has empty electorate_slug.")

    def _to_feature_collection(self, geometry, electorate):
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "electorate_slug": electorate.slug,
                        "electorate_name": electorate.name,
                    },
                    "geometry": geometry,
                }
            ],
        }

    def _create_geojson_file(
        self,
        document,
        filename,
        display_name,
        payload,
        copyright_owner,
        licence,
        licence_grantor,
    ):
        content_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        file_obj = File(
            document=document,
            file_name=display_name,
            file_type="application/geo+json",
            source_url=None,
            copyright_owner=copyright_owner,
            licence=licence,
            licence_grantor=licence_grantor,
        )
        file_obj._file_content_for_hash = content_bytes
        file_obj.file.save(filename, ContentFile(content_bytes), save=False)
        file_obj.save()
        return file_obj

    def _get_or_create_document(self, name, description, dry_run=False):
        if dry_run:
            return Document(name=name, description=description)
        document, _ = Document.objects.get_or_create(
            name=name,
            defaults={"description": description},
        )
        return document

    def _get_or_create_boundary_set(self, document, valid_from, dry_run=False):
        if dry_run:
            return ElectorateBoundarySet(document=document, valid_from=valid_from)
        boundary_set, _ = ElectorateBoundarySet.objects.get_or_create(
            document=document,
            valid_from=valid_from,
        )
        return boundary_set

    def _get_or_create_copyright_party(self, name, dry_run=False):
        name = (name or "").strip()
        if not name:
            return None
        if dry_run:
            return CopyrightParty(name=name)
        party, _ = CopyrightParty.objects.get_or_create(name=name)
        return party

    def _get_or_create_licence(self, name, dry_run=False):
        name = (name or "").strip()
        if not name:
            return None
        if dry_run:
            return Licence(name=name)
        licence, _ = Licence.objects.get_or_create(name=name)
        return licence

    def _parse_date(self, value):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError(f"Invalid --valid-from date '{value}'. Use YYYY-MM-DD.") from exc
