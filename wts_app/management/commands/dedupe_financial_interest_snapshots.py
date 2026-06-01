"""
Remove duplicate financial-interest snapshots that share the same person and as_at date.

Legacy migration imported two parallel batches for 2021-01-31 (legacy column 83 vs 85).
For each duplicate group, keeps the snapshot with the highest legacy_id and deletes the rest
(cascades to FinancialInterest rows).

Usage:
  python manage.py dedupe_financial_interest_snapshots              # dry-run
  python manage.py dedupe_financial_interest_snapshots --execute    # apply
  python manage.py dedupe_financial_interest_snapshots --as-at 2021-01-31 --person-slug james-shaw
"""

from collections import defaultdict
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from wts_app.models.people import FinancialInterestSnapshot


def parse_date(value):
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid date {value!r}; use YYYY-MM-DD") from exc


class Command(BaseCommand):
    help = (
        "Delete duplicate financial interest snapshots for the same person and as_at, "
        "keeping the snapshot with the highest legacy_id."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--as-at",
            type=str,
            default="2021-01-31",
            help="Only dedupe snapshots on this date (YYYY-MM-DD). Default: 2021-01-31.",
        )
        parser.add_argument(
            "--person-slug",
            type=str,
            help="Limit to a single person slug (for testing).",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Actually delete snapshots. Without this flag, only reports what would be deleted.",
        )
        parser.add_argument(
            "--min-legacy-id",
            type=int,
            default=None,
            help=(
                "Only consider snapshots with legacy_id >= this value when choosing what to keep. "
                "Use with care; default keeps the highest legacy_id in each group."
            ),
        )

    def handle(self, *args, **options):
        as_at = parse_date(options["as_at"])
        person_slug = options.get("person_slug")
        execute = options["execute"]
        min_legacy_id = options.get("min_legacy_id")

        qs = FinancialInterestSnapshot.objects.filter(as_at=as_at).select_related("person")
        if person_slug:
            qs = qs.filter(person__slug=person_slug)

        duplicate_person_ids = (
            qs.values("person_id")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
            .values_list("person_id", flat=True)
        )

        groups = defaultdict(list)
        for snapshot in (
            FinancialInterestSnapshot.objects.filter(
                person_id__in=duplicate_person_ids, as_at=as_at
            )
            .select_related("person")
            .order_by("person_id", "legacy_id", "created_at")
        ):
            groups[snapshot.person_id].append(snapshot)

        if not groups:
            self.stdout.write(
                self.style.SUCCESS(f"No duplicate snapshots on {as_at}.")
            )
            return

        to_delete = []
        warnings = []

        for person_id, snapshots in sorted(
            groups.items(), key=lambda item: item[1][0].person.display_name
        ):
            person = snapshots[0].person
            if len(snapshots) < 2:
                continue

            with_legacy = [s for s in snapshots if s.legacy_id is not None]
            without_legacy = [s for s in snapshots if s.legacy_id is None]

            if without_legacy:
                warnings.append(
                    f"{person.slug}: {len(without_legacy)} snapshot(s) missing legacy_id; "
                    "manual review required."
                )
                if not with_legacy:
                    continue

            if min_legacy_id is not None:
                keep_candidates = [s for s in with_legacy if s.legacy_id >= min_legacy_id]
                if not keep_candidates:
                    warnings.append(
                        f"{person.slug}: no snapshot with legacy_id >= {min_legacy_id}; skipped."
                    )
                    continue
                keep = max(keep_candidates, key=lambda s: s.legacy_id)
            else:
                keep = max(with_legacy, key=lambda s: s.legacy_id)

            delete = [s for s in snapshots if s.id != keep.id]

            for s in delete:
                if s.document_id and s.document_id != keep.document_id:
                    warnings.append(
                        f"{person.slug}: deleting snapshot legacy_id={s.legacy_id} "
                        f"has document {s.document_id}; kept snapshot has document {keep.document_id}."
                    )

            interest_counts = {
                s.legacy_id: s.financialinterest_set.count() for s in snapshots
            }
            self.stdout.write(
                f"{person.display_name} ({person.slug}): "
                f"keep legacy_id={keep.legacy_id} ({interest_counts.get(keep.legacy_id, 0)} interests), "
                f"delete {[s.legacy_id for s in delete]} "
                f"({', '.join(str(interest_counts.get(s.legacy_id, 0)) for s in delete)} interests)"
            )
            to_delete.extend(delete)

        if warnings:
            self.stdout.write(self.style.WARNING("\nWarnings:"))
            for w in warnings:
                self.stdout.write(self.style.WARNING(f"  {w}"))

        self.stdout.write(
            f"\nSummary: {len(groups)} people with duplicates, "
            f"{len(to_delete)} snapshot(s) to delete."
        )

        if not execute:
            self.stdout.write(
                self.style.NOTICE("Dry run only. Re-run with --execute to apply.")
            )
            return

        if not to_delete:
            return

        with transaction.atomic():
            deleted_count, deleted_details = FinancialInterestSnapshot.objects.filter(
                id__in=[s.id for s in to_delete]
            ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {len(to_delete)} snapshot(s). "
                f"Cascade totals: {deleted_count} rows ({deleted_details})."
            )
        )
