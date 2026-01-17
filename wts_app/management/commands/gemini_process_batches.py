from typing import List

from django.core.management.base import BaseCommand
from django.utils import timezone

from wts_app.gemini.client import GeminiClient
from wts_app.gemini.processors import PROCESSOR_REGISTRY, get_processor
from wts_app.gemini.utils import map_job_state, normalize_inlined_response, parse_jsonl_response
from wts_app.models.gemini import GeminiBatchItem, GeminiBatchJob


class Command(BaseCommand):
    help = "Check Gemini batch jobs and process completed responses."

    def add_arguments(self, parser):
        parser.add_argument(
            "--processor",
            choices=sorted(PROCESSOR_REGISTRY.keys()),
            default=None,
            help="Optional processor name to filter jobs.",
        )
        parser.add_argument(
            "--job-ids",
            nargs="*",
            help="Optional GeminiBatchJob IDs (space or comma separated).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of jobs to check.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be processed without updating records.",
        )

    def handle(self, *args, **options):
        processor_name = options.get("processor")
        raw_job_ids = options.get("job_ids") or []
        limit = options.get("limit")
        dry_run = options.get("dry_run")

        job_ids = self._parse_ids(raw_job_ids)
        jobs = GeminiBatchJob.objects.all()
        if processor_name:
            jobs = jobs.filter(processor=processor_name)
        if job_ids:
            jobs = jobs.filter(id__in=job_ids)
        jobs = jobs.exclude(
            status__in=[
                GeminiBatchJob.Status.FAILED,
                GeminiBatchJob.Status.CANCELLED,
                GeminiBatchJob.Status.EXPIRED,
            ]
        )
        if limit:
            jobs = jobs[:limit]

        jobs = list(jobs)
        if not jobs:
            self.stdout.write(self.style.WARNING("No Gemini batch jobs found to process."))
            return

        client = GeminiClient()

        for job in jobs:
            if not job.batch_name:
                self.stdout.write(
                    self.style.WARNING(f"Skipping job {job.id}: missing batch_name.")
                )
                continue

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(f"[Dry run] Would check job {job.id}.")
                )
                continue

            try:
                batch_job = client.get_batch_job(name=job.batch_name)
            except Exception as exc:  # pylint: disable=broad-except
                job.error_message = str(exc)
                job.last_checked_at = timezone.now()
                job.save(update_fields=["error_message", "last_checked_at", "updated_at"])
                self.stdout.write(
                    self.style.ERROR(f"Failed to fetch batch job {job.id}: {exc}")
                )
                continue
            job.status = map_job_state(batch_job.state)
            job.resolved_model = batch_job.model or job.resolved_model
            job.last_checked_at = timezone.now()
            job.completed_at = batch_job.end_time or job.completed_at
            job.raw_response = batch_job.model_dump()
            if batch_job.error:
                job.error_message = batch_job.error.message
            if batch_job.dest and batch_job.dest.file_name:
                job.output_file_name = batch_job.dest.file_name
            job.save(
                update_fields=[
                    "status",
                    "resolved_model",
                    "last_checked_at",
                    "completed_at",
                    "raw_response",
                    "error_message",
                    "output_file_name",
                    "updated_at",
                ]
            )

            if job.status not in [
                GeminiBatchJob.Status.SUCCEEDED,
                GeminiBatchJob.Status.PARTIAL,
            ]:
                self.stdout.write(
                    self.style.WARNING(
                        f"Job {job.id} is not complete (status: {job.status})."
                    )
                )
                continue

            processor = get_processor(job.processor, client=client)
            responses = self._get_responses(batch_job, client)
            if responses is None:
                self.stdout.write(
                    self.style.ERROR(f"Job {job.id} has no response payload yet.")
                )
                continue

            model_versions = {
                response.model_version
                for response, _, _ in responses
                if response is not None and response.model_version
            }
            if len(model_versions) == 1:
                job.resolved_model = model_versions.pop()
                job.save(update_fields=["resolved_model", "updated_at"])

            items = list(
                GeminiBatchItem.objects.filter(
                    job=job, status=GeminiBatchItem.Status.SUBMITTED
                ).order_by("output_index")
            )
            if not items:
                self.stdout.write(self.style.WARNING(f"Job {job.id} has no pending items."))
                continue

            if len(responses) != len(items):
                self.stdout.write(
                    self.style.WARNING(
                        f"Job {job.id} response count ({len(responses)}) does not match "
                        f"items ({len(items)}). Processing the minimum."
                    )
                )

            processed = 0
            for item, response_data in zip(items, responses):
                response, error, raw_payload = response_data
                try:
                    processor.handle_response(
                        item=item,
                        response=response,
                        error=error,
                        raw_payload=raw_payload,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    item.status = GeminiBatchItem.Status.FAILED
                    item.error_message = str(exc)
                    item.processed_at = timezone.now()
                    item.response_payload = raw_payload
                    item.save(
                        update_fields=[
                            "status",
                            "error_message",
                            "processed_at",
                            "response_payload",
                            "updated_at",
                        ]
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f"Item {item.id} failed to process: {item.error_message}"
                        )
                    )
                processed += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Processed {processed} responses for job {job.id}."
                )
            )

    def _get_responses(self, batch_job, client: GeminiClient):
        if batch_job.dest and batch_job.dest.inlined_responses is not None:
            return [normalize_inlined_response(resp) for resp in batch_job.dest.inlined_responses]
        if batch_job.dest and batch_job.dest.file_name:
            raw_bytes = client.download_file(file_name=batch_job.dest.file_name)
            lines = raw_bytes.decode("utf-8").splitlines()
            return [
                parse_jsonl_response(line) for line in lines if line.strip()
            ]
        return None

    def _parse_ids(self, raw_ids: List[str]) -> List[str]:
        if not raw_ids:
            return []
        ids: List[str] = []
        for raw in raw_ids:
            ids.extend([part.strip() for part in raw.split(",") if part.strip()])
        return ids
