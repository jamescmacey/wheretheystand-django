"""Submit Gemini batches for workbook steps."""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from wts_app.gemini.client import GeminiClient
from wts_app.gemini.processors import get_processor
from wts_app.gemini.utils import (
    fail_gemini_batch_submission,
    map_job_state,
    release_workbook_step_after_failed_gemini,
)
from wts_app.ingestion.orchestrator import start_step
from wts_app.ingestion.recipes.registry import get_recipe
from wts_app.models import GeminiBatchItem, GeminiBatchJob, WorkbookStep


def submit_gemini_for_step(step: WorkbookStep) -> GeminiBatchJob:
    """Submit a single workbook step to Gemini batch processing."""
    if step.step_key != "gemini_extract":
        raise ValueError("Only gemini_extract steps can be submitted to Gemini.")

    workbook = step.workbook
    recipe = get_recipe(workbook.recipe_key)
    recipe.can_start(step)
    start_step(step)

    client = GeminiClient()
    processor = get_processor("workbook_step_gemini", client=client)
    requested_model = getattr(settings, "GEMINI_MODEL", None)
    if not requested_model:
        raise ValueError("GEMINI_MODEL is not configured.")

    job = GeminiBatchJob.objects.create(
        processor=processor.name,
        requested_model=requested_model,
        status=GeminiBatchJob.Status.PENDING,
        raw_request={"model": requested_model, "step_id": str(step.id)},
    )
    item = GeminiBatchItem.objects.create(
        job=job,
        content_object=step,
        status=GeminiBatchItem.Status.PENDING,
        output_index=0,
    )

    try:
        prepared = processor.build_request(item=item, requested_model=requested_model)
    except Exception as exc:
        error = str(exc)
        fail_gemini_batch_submission(job, error_message=error, item=item)
        release_workbook_step_after_failed_gemini(step, error)
        raise

    item.request_payload = prepared.request_payload
    item.save(update_fields=["request_payload", "updated_at"])

    try:
        batch_job = client.create_batch_job(
            model=requested_model,
            requests=[prepared.request],
        )
    except Exception as exc:
        error = str(exc)
        fail_gemini_batch_submission(job, error_message=error, item=item)
        release_workbook_step_after_failed_gemini(step, error)
        raise

    job.batch_name = batch_job.name
    job.resolved_model = batch_job.model or job.resolved_model
    job.status = map_job_state(batch_job.state)
    job.submitted_at = timezone.now()
    job.save(
        update_fields=[
            "batch_name",
            "resolved_model",
            "status",
            "submitted_at",
            "updated_at",
        ]
    )
    item.status = GeminiBatchItem.Status.SUBMITTED
    item.submitted_at = timezone.now()
    item.save(update_fields=["status", "submitted_at", "updated_at"])

    payload = dict(step.payload or {})
    payload["gemini_batch_item_id"] = str(item.id)
    payload["gemini_job_id"] = str(job.id)
    step.payload = payload
    step.save(update_fields=["payload", "updated_at"])
    return job
