"""Celery tasks for workbook lifecycle."""

from __future__ import annotations

from celery import shared_task

from wts_app.ingestion.workbook_lifecycle import is_workbook_fully_committed
from wts_app.models import Workbook


@shared_task(name="wts_app.workbooks.close_completed_workbook")
def close_completed_workbook(workbook_id: str) -> None:
    """
    Mark a fully committed workbook as closed and remove staged WorkbookFile rows
    (including private storage blobs).
    """
    try:
        workbook = Workbook.objects.get(pk=workbook_id)
    except Workbook.DoesNotExist:
        return

    if workbook.status == Workbook.Status.CLOSED:
        return
    if not is_workbook_fully_committed(workbook):
        return

    for workbook_file in list(workbook.files.all()):
        workbook_file.delete()

    workbook.status = Workbook.Status.CLOSED
    workbook.save(update_fields=["status", "updated_at"])
