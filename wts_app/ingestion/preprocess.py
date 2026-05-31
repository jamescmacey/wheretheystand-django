"""System event preprocessing via step orchestrator."""

from __future__ import annotations

from django.utils import timezone

from wts_app.ingestion.orchestrator import advance_workbook, ensure_steps
from wts_app.ingestion.recipes.registry import get_recipe
from wts_app.ingestion.sources.registry import get_source_handler
from wts_app.models import SystemEvent, WorkbookStep


def process_system_event(event_id: str) -> None:
    event = SystemEvent.objects.select_related("source").get(pk=event_id)
    if event.status == SystemEvent.Status.PREPROCESSED:
        return

    source = event.source
    handler = get_source_handler(source.handler)
    event.status = SystemEvent.Status.PROCESSING
    event.save(update_fields=["status", "updated_at"])

    try:
        if event.workbook_id:
            workbook = event.workbook
        else:
            from wts_app.ingestion.sources.base import DetectedItem

            detected = DetectedItem(
                external_id=event.external_id,
                payload=event.payload,
                source_url=event.payload.get("source_url", ""),
            )

            handler.process_event(source, detected)
            event.status = SystemEvent.Status.SUCCESS
            event.save(update_fields=["status", "updated_at"])

        recipe_key = workbook.recipe_key
        recipe = get_recipe(recipe_key)
        config = source.config or {}
        auto = config.get("auto_advance", {})

        if auto.get("link_entities", True):
            for step in WorkbookStep.objects.filter(
                workbook=workbook, step_key="link_entities"
            ):
                if step.status == WorkbookStep.Status.DRAFT:
                    step.status = WorkbookStep.Status.AWAITING_REVIEW
                    step.save(update_fields=["status", "updated_at"])

        if auto.get("gemini_extract", False) and recipe_key == "credit_card_reconciliation":
            from wts_app.ingestion.gemini import submit_gemini_for_step

            for step in WorkbookStep.objects.filter(
                workbook=workbook, step_key="gemini_extract", status=WorkbookStep.Status.DRAFT
            ):
                link_ready = WorkbookStep.objects.filter(
                    workbook=workbook,
                    step_key="link_entities",
                    workbook_file=step.workbook_file,
                    status=WorkbookStep.Status.COMMITTED,
                ).exists()
                if link_ready:
                    submit_gemini_for_step(step)

        advance_workbook(workbook, auto_commit=config.get("auto_commit", False))

        event.status = SystemEvent.Status.PREPROCESSED
        event.error_message = None
        event.save(update_fields=["status", "error_message", "updated_at"])
    except Exception as exc:
        event.status = SystemEvent.Status.FAILED
        event.error_message = str(exc)
        event.save(update_fields=["status", "error_message", "updated_at"])
        raise
