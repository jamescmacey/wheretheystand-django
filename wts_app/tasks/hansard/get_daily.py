"""Celery task for fetching daily Hansard."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="wts_app.hansard.get_daily", queue="hansard")
def get_daily() -> None:
    """Fetch daily Hansard."""
    pass
