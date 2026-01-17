"""Utility helpers for Gemini batch processing."""

from __future__ import annotations

import json
from typing import Optional, Tuple

from google.genai import types

from wts_app.models.gemini import GeminiBatchJob


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
