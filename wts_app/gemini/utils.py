"""Utility helpers for Gemini batch processing."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Optional, Tuple

from django.utils import timezone
from google.genai import types

from wts_app.models.gemini import GeminiBatchItem, GeminiBatchJob

# Grace period before failing jobs that never received a Gemini batch_name.
UNSUBMITTED_BATCH_GRACE_PERIOD = timedelta(minutes=2)


JOB_STATE_TO_STATUS = {
    types.JobState.JOB_STATE_PENDING: GeminiBatchJob.Status.PENDING,
    types.JobState.JOB_STATE_QUEUED: GeminiBatchJob.Status.QUEUED,
    types.JobState.JOB_STATE_RUNNING: GeminiBatchJob.Status.RUNNING,
    types.JobState.JOB_STATE_SUCCEEDED: GeminiBatchJob.Status.SUCCEEDED,
    types.JobState.JOB_STATE_PARTIALLY_SUCCEEDED: GeminiBatchJob.Status.PARTIAL,
    types.JobState.JOB_STATE_FAILED: GeminiBatchJob.Status.FAILED,
    types.JobState.JOB_STATE_CANCELLED: GeminiBatchJob.Status.CANCELLED,
    types.JobState.JOB_STATE_CANCELLING: GeminiBatchJob.Status.CANCELLING,
    types.JobState.JOB_STATE_PAUSED: GeminiBatchJob.Status.PAUSED,
    types.JobState.JOB_STATE_EXPIRED: GeminiBatchJob.Status.EXPIRED,
}


def map_job_state(state: Optional[types.JobState]) -> str:
    if state is None:
        return GeminiBatchJob.Status.UNKNOWN
    return JOB_STATE_TO_STATUS.get(state, GeminiBatchJob.Status.UNKNOWN)


def normalize_inlined_response(
    response: types.InlinedResponse,
) -> Tuple[Optional[types.GenerateContentResponse], Optional[types.JobError], dict]:
    raw_payload = response.model_dump() if hasattr(response, "model_dump") else {}
    return response.response, response.error, raw_payload


def parse_jsonl_response(
    line: str,
) -> Tuple[Optional[types.GenerateContentResponse], Optional[types.JobError], dict]:
    payload = json.loads(line)
    if "error" in payload and "response" not in payload:
        error = types.JobError.model_validate(payload["error"])
        return None, error, payload
    response = types.GenerateContentResponse.model_validate(payload)
    return response, None, payload


def fail_gemini_batch_submission(
    job: GeminiBatchJob,
    *,
    error_message: str,
    item: GeminiBatchItem | None = None,
) -> None:
    """Mark pending batch items and the parent job failed."""
    now = timezone.now()
    items = job.items.all()
    if item is not None:
        items = items.filter(pk=item.pk)
    items.filter(status=GeminiBatchItem.Status.PENDING).update(
        status=GeminiBatchItem.Status.FAILED,
        error_message=error_message,
        processed_at=now,
    )
    job.status = GeminiBatchJob.Status.FAILED
    job.error_message = error_message
    job.completed_at = now
    job.save(update_fields=["status", "error_message", "completed_at", "updated_at"])


def release_workbook_step_after_failed_gemini(step, error_message: str) -> None:
    """Return a workbook step to draft so the operator can retry submission."""
    from wts_app.models.workbook_pipeline import WorkbookStep

    if step.status != WorkbookStep.Status.RUNNING:
        return
    step.status = WorkbookStep.Status.DRAFT
    step.error_message = error_message
    step.save(update_fields=["status", "error_message", "updated_at"])


def fail_stale_unsubmitted_batch_job(job: GeminiBatchJob) -> bool:
    """Fail jobs that were created locally but never sent to Gemini."""
    if job.batch_name:
        return False
    if job.created_at > timezone.now() - UNSUBMITTED_BATCH_GRACE_PERIOD:
        return False

    error = job.error_message or "Batch was never submitted to Gemini."
    pending_items = list(job.items.filter(status=GeminiBatchItem.Status.PENDING))
    workbook_steps = []
    for item in pending_items:
        step = item.content_object
        from wts_app.models.workbook_pipeline import WorkbookStep

        if isinstance(step, WorkbookStep):
            workbook_steps.append(step)

    fail_gemini_batch_submission(job, error_message=error)
    for step in workbook_steps:
        release_workbook_step_after_failed_gemini(step, error)
    return True
