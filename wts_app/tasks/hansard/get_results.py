"""Celery task for fetching Hansard search results."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="wts_app.hansard.get_results", queue="hansard")
def get_results() -> None:
    """Fetch Hansard search results."""
    pass
