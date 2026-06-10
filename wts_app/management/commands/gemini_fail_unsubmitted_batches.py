from django.core.management.base import BaseCommand
from django.db.models import Q

from wts_app.gemini.utils import fail_stale_unsubmitted_batch_job
from wts_app.models.gemini import GeminiBatchJob


class Command(BaseCommand):
    help = (
        "Fail Gemini batch jobs that never received a batch_name from Gemini. "
        "Use this to clear orphaned pending jobs after a failed submission."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List jobs that would be failed without updating records.",
        )
        parser.add_argument(
            "--include-recent",
            action="store_true",
            help="Include jobs created within the normal grace period.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        include_recent = options["include_recent"]

        jobs = GeminiBatchJob.objects.filter(
            Q(batch_name__isnull=True) | Q(batch_name=""),
        ).exclude(
            status__in=[
                GeminiBatchJob.Status.FAILED,
                GeminiBatchJob.Status.CANCELLED,
                GeminiBatchJob.Status.EXPIRED,
                GeminiBatchJob.Status.PROCESSED,
            ],
        )

        if not jobs.exists():
            self.stdout.write(self.style.WARNING("No unsubmitted Gemini batch jobs found."))
            return

        failed_count = 0
        for job in jobs:
            if dry_run:
                self.stdout.write(f"[Dry run] Would fail job {job.id} ({job.processor})")
                continue

            if include_recent:
                from wts_app.gemini.utils import (
                    fail_gemini_batch_submission,
                    release_workbook_step_after_failed_gemini,
                )
                from wts_app.models.gemini import GeminiBatchItem
                from wts_app.models.workbook_pipeline import WorkbookStep

                error = job.error_message or "Batch was never submitted to Gemini."
                workbook_steps = []
                for item in job.items.filter(status=GeminiBatchItem.Status.PENDING):
                    step = item.content_object
                    if isinstance(step, WorkbookStep):
                        workbook_steps.append(step)
                fail_gemini_batch_submission(job, error_message=error)
                for step in workbook_steps:
                    release_workbook_step_after_failed_gemini(step, error)
                failed_count += 1
                self.stdout.write(self.style.ERROR(f"Failed unsubmitted job {job.id}"))
                continue

            if fail_stale_unsubmitted_batch_job(job):
                failed_count += 1
                self.stdout.write(self.style.ERROR(f"Failed unsubmitted job {job.id}"))
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipped recent job {job.id}; use --include-recent to fail immediately."
                    )
                )

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Failed {failed_count} unsubmitted job(s)."))
