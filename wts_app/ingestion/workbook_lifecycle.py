"""Workbook pipeline completion and cleanup."""

from __future__ import annotations

from django.db import transaction

from wts_app.models import Workbook, WorkbookStep


def is_workbook_fully_committed(workbook: Workbook) -> bool:
    """True when every pipeline step is committed or skipped."""
    if not workbook.recipe_key:
        return False
    steps = WorkbookStep.objects.filter(workbook=workbook)
    if not steps.exists():
        return False
    return not steps.exclude(
        status__in=[
            WorkbookStep.Status.COMMITTED,
            WorkbookStep.Status.SKIPPED,
        ]
    ).exists()


def schedule_workbook_close_if_complete(workbook_id) -> None:
    """Enqueue async close/cleanup after the DB transaction commits."""
    from wts_app.tasks.workbooks import close_completed_workbook

    transaction.on_commit(
        lambda: close_completed_workbook.delay(str(workbook_id))
    )
