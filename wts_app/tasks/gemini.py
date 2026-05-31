"""Celery tasks for processing Gemini batch jobs."""

from __future__ import annotations

from celery import shared_task
from django.core.management import call_command


@shared_task(name="wts_app.gemini.process_completed_gemini_batches")
def process_completed_gemini_batches(limit: int = 100) -> None:
    """
    Poll Gemini batch jobs and apply completed responses.

    This wraps the `gemini_process_batches` management command so Gemini can
    advance workbooks without a manual cron/manual invocation.
    """

    call_command("gemini_process_batches", "--limit", str(limit))

