import itertools
from typing import Iterable, List

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from wts_app.gemini.client import GeminiClient
from wts_app.gemini.processors import PROCESSOR_REGISTRY, get_processor
from wts_app.gemini.utils import map_job_state
from wts_app.models.gemini import GeminiBatchItem, GeminiBatchJob


def _chunked(items: List, size: int) -> Iterable[List]:
    iterator = iter(items)
    while True:
        chunk = list(itertools.islice(iterator, size))
        if not chunk:
            break
        yield chunk


def _parse_ids(raw_ids: List[str]) -> List[str]:
    if not raw_ids:
        return []
    ids: List[str] = []
    for raw in raw_ids:
        ids.extend([part.strip() for part in raw.split(",") if part.strip()])
    return ids


class Command(BaseCommand):
    help = "Submit Gemini batch jobs for supported processors."

    def add_arguments(self, parser):
        parser.add_argument(
            "processor",
            choices=sorted(PROCESSOR_REGISTRY.keys()),
            help="Processor name to submit.",
        )
        parser.add_argument(
            "--ids",
            nargs="*",
            help="Optional IDs (space or comma separated).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of records to submit.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=10,
            help="Number of requests per batch job.",
        )
        parser.add_argument(
            "--model",
            type=str,
            default=None,
            help="Override GEMINI_MODEL for this submission.",
        )
        parser.add_argument(
            "--display-name",
            type=str,
            default=None,
            help="Optional display name for the batch job.",
        )
        parser.add_argument(
            "--include-failed",
            action="store_true",
            help="Include records that previously failed Gemini processing.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be submitted without calling Gemini.",
        )

    def handle(self, *args, **options):
        processor_name = options["processor"]
        requested_model = options["model"] or getattr(settings, "GEMINI_MODEL", None)
        if not requested_model:
            raise CommandError("GEMINI_MODEL is not configured.")

        ids = _parse_ids(options.get("ids") or [])
        limit = options.get("limit")
        batch_size = options["batch_size"]
        include_failed = options["include_failed"]
        dry_run = options["dry_run"]
        display_name = options["display_name"]

        client = GeminiClient()
        processor = get_processor(processor_name, client=client)

        queryset = processor.get_queryset(ids=ids or None, include_failed=include_failed)
        if limit:
            queryset = queryset[:limit]
        objects = list(queryset)
        if not objects:
            self.stdout.write(self.style.WARNING("No records found to submit."))
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Submitting {len(objects)} records using processor '{processor_name}'"
            )
        )

        for chunk_index, chunk in enumerate(_chunked(objects, batch_size), start=1):
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"[Dry run] Would submit batch {chunk_index} with {len(chunk)} records."
                    )
                )
                continue

            job = GeminiBatchJob.objects.create(
                processor=processor_name,
                requested_model=requested_model,
                status=GeminiBatchJob.Status.PENDING,
                display_name=display_name,
                raw_request={
                    "model": requested_model,
                    "display_name": display_name,
                    "item_count": len(chunk),
                },
            )

            prepared_requests = []
            for obj in chunk:
                item = GeminiBatchItem.objects.create(
                    job=job,
                    content_object=obj,
                    status=GeminiBatchItem.Status.PENDING,
                )
                try:
                    prepared = processor.build_request(item=item, requested_model=requested_model)
                except Exception as exc:  # pylint: disable=broad-except
                    item.status = GeminiBatchItem.Status.FAILED
                    item.error_message = str(exc)
                    item.processed_at = timezone.now()
                    item.save(update_fields=["status", "error_message", "processed_at", "updated_at"])
                    self.stdout.write(
                        self.style.ERROR(
                            f"Skipping item {item.id} due to error: {item.error_message}"
                        )
                    )
                    continue

                item.output_index = len(prepared_requests)
                item.request_payload = prepared.request_payload
                item.save(update_fields=["output_index", "request_payload", "updated_at"])
                prepared_requests.append(prepared)

            if not prepared_requests:
                job.status = GeminiBatchJob.Status.FAILED
                job.error_message = "No valid requests to submit."
                job.save(update_fields=["status", "error_message", "updated_at"])
                self.stdout.write(
                    self.style.ERROR(
                        f"Batch {chunk_index}: no valid requests, skipping submission."
                    )
                )
                continue

            try:
                batch_job = client.create_batch_job(
                    model=requested_model,
                    requests=[entry.request for entry in prepared_requests],
                    display_name=display_name,
                )
            except Exception as exc:  # pylint: disable=broad-except
                job.status = GeminiBatchJob.Status.FAILED
                job.error_message = str(exc)
                job.save(update_fields=["status", "error_message", "updated_at"])
                self.stdout.write(
                    self.style.ERROR(f"Batch {chunk_index} submission failed: {exc}")
                )
                continue

            job.batch_name = batch_job.name
            job.resolved_model = batch_job.model or job.resolved_model
            job.status = map_job_state(batch_job.state)
            job.raw_response = batch_job.model_dump()
            job.submitted_at = timezone.now()
            if batch_job.dest and batch_job.dest.file_name:
                job.output_file_name = batch_job.dest.file_name
            job.save(
                update_fields=[
                    "batch_name",
                    "resolved_model",
                    "status",
                    "raw_response",
                    "submitted_at",
                    "output_file_name",
                    "updated_at",
                ]
            )

            GeminiBatchItem.objects.filter(
                id__in=[entry.item.id for entry in prepared_requests]
            ).update(
                status=GeminiBatchItem.Status.SUBMITTED,
                submitted_at=timezone.now(),
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Submitted batch {chunk_index} with {len(prepared_requests)} requests."
                )
            )
