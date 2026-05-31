"""Workbook step orchestrator."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from wts_app.ingestion.workbook_lifecycle import (
    is_workbook_fully_committed,
    schedule_workbook_close_if_complete,
)
from wts_app.ingestion.recipes.registry import get_recipe
from wts_app.models import Workbook, WorkbookFile, WorkbookStep


def _recipe(workbook: Workbook):
    if not workbook.recipe_key:
        raise ValueError("Workbook has no recipe_key set.")
    if workbook.status == Workbook.Status.CLOSED:
        raise ValueError("Workbook is closed.")
    return get_recipe(workbook.recipe_key)


def ensure_steps(workbook: Workbook, *, workbook_file: WorkbookFile | None = None) -> list[WorkbookStep]:
    """Create step rows for a workbook file (or all files if batch recipe)."""
    recipe = _recipe(workbook)
    created: list[WorkbookStep] = []

    files: list[WorkbookFile]
    if workbook_file is not None:
        files = [workbook_file]
    elif recipe.batch_per_file:
        files = list(workbook.files.all())
        if not files:
            return created
    else:
        files = [None]  # type: ignore[list-item]

    for wf in files:
        file_id = str(wf.id) if wf else None
        for step_def in recipe.steps():
            defaults = {
                "sequence": step_def.sequence,
                "status": WorkbookStep.Status.PENDING,
                "payload": recipe.initial_payload(workbook_file_id=file_id),
            }
            if step_def.step_key == "upload" and wf:
                defaults["status"] = WorkbookStep.Status.COMMITTED
                defaults["payload"] = {
                    **defaults["payload"],
                    "workbook_file_id": file_id,
                }
                defaults["committed_at"] = timezone.now()

            step, was_created = WorkbookStep.objects.get_or_create(
                workbook=workbook,
                step_key=step_def.step_key,
                workbook_file=wf,
                defaults=defaults,
            )
            if was_created:
                created.append(step)
    _unlock_ready_steps(workbook)
    return created


def ensure_steps_for_new_file(workbook: Workbook, workbook_file: WorkbookFile) -> list[WorkbookStep]:
    """Called after file upload when workbook already has recipe_key."""
    if not workbook.recipe_key:
        return []
    return ensure_steps(workbook, workbook_file=workbook_file)


def save_draft(step: WorkbookStep, payload: dict) -> WorkbookStep:
    recipe = _recipe(step.workbook)
    merged = recipe.validate_draft(step, payload)
    step.payload = merged
    step.status = WorkbookStep.Status.DRAFT
    step.error_message = None
    step.save(update_fields=["payload", "status", "error_message", "updated_at"])
    return step


def start_step(step: WorkbookStep) -> WorkbookStep:
    recipe = _recipe(step.workbook)
    recipe.can_start(step)
    if not _prior_steps_committed(step):
        raise ValueError(f"Prior steps must be committed before starting {step.step_key}.")
    step.status = WorkbookStep.Status.RUNNING
    step.error_message = None
    step.save(update_fields=["status", "error_message", "updated_at"])
    return step


def complete_async(step: WorkbookStep, *, awaiting_review: bool = True) -> WorkbookStep:
    if awaiting_review:
        step.status = WorkbookStep.Status.AWAITING_REVIEW
    else:
        step.status = WorkbookStep.Status.DRAFT
    step.save(update_fields=["status", "updated_at"])
    return step


def commit_step(step: WorkbookStep, *, actor) -> WorkbookStep:
    if step.status == WorkbookStep.Status.COMMITTED:
        return step
    if step.status not in (
        WorkbookStep.Status.DRAFT,
        WorkbookStep.Status.AWAITING_REVIEW,
    ):
        raise ValueError(f"Cannot commit step in status {step.status}.")

    recipe = _recipe(step.workbook)
    if not _prior_steps_committed(step, exclude_self=True):
        raise ValueError("Prior steps must be committed first.")

    with transaction.atomic():
        recipe.commit_step(step, actor=actor)
        step.committed_at = timezone.now()
        step.committed_by = actor
        step.status = WorkbookStep.Status.COMMITTED
        step.error_message = None
        step.save(
            update_fields=[
                "payload",
                "status",
                "committed_at",
                "committed_by",
                "error_message",
                "production_content_type",
                "production_object_id",
                "updated_at",
            ]
        )
        recipe.on_step_committed(step)

    _unlock_ready_steps(step.workbook)
    if is_workbook_fully_committed(step.workbook):
        schedule_workbook_close_if_complete(step.workbook_id)
    return step


def reject_step(step: WorkbookStep, *, actor, reason: str = "") -> WorkbookStep:
    recipe = _recipe(step.workbook)
    step.status = WorkbookStep.Status.REJECTED
    step.error_message = reason or None
    step.save(update_fields=["status", "error_message", "updated_at"])
    rewind_key = recipe.rewind_to_step_key(step)
    if rewind_key:
        target = WorkbookStep.objects.filter(
            workbook=step.workbook,
            step_key=rewind_key,
            workbook_file=step.workbook_file,
        ).first()
        if target:
            target.status = WorkbookStep.Status.DRAFT
            target.committed_at = None
            target.committed_by = None
            target.save(
                update_fields=[
                    "status",
                    "committed_at",
                    "committed_by",
                    "updated_at",
                ]
            )
    return step


def advance_workbook(workbook: Workbook, *, auto_commit: bool = False, actor=None) -> None:
    """Automation: run draft/auto steps until next review gate."""
    recipe = _recipe(workbook)
    for step in WorkbookStep.objects.filter(workbook=workbook).order_by(
        "workbook_file_id", "sequence"
    ):
        step_def = next((s for s in recipe.steps() if s.step_key == step.step_key), None)
        if step_def is None:
            continue
        if step.status == WorkbookStep.Status.PENDING and _prior_steps_committed(step):
            if step_def.step_key == "upload":
                commit_step(step, actor=actor)
            else:
                step.status = WorkbookStep.Status.DRAFT
                step.save(update_fields=["status", "updated_at"])
        if step.status == WorkbookStep.Status.DRAFT and step_def.auto_advance:
            if auto_commit and not step_def.requires_review:
                commit_step(step, actor=actor)
        if step_def.requires_review and step.status == WorkbookStep.Status.AWAITING_REVIEW:
            break


def get_committed_payload(workbook: Workbook, step_key: str, *, workbook_file_id) -> dict:
    step = WorkbookStep.objects.get(
        workbook=workbook,
        step_key=step_key,
        workbook_file_id=workbook_file_id,
        status=WorkbookStep.Status.COMMITTED,
    )
    return step.payload or {}


def compute_progress(workbook: Workbook) -> dict:
    steps = WorkbookStep.objects.filter(workbook=workbook)
    by_status: dict[str, int] = {}
    by_step_key: dict[str, dict[str, int]] = {}
    awaiting_review = 0
    files = set()

    for step in steps:
        by_status[step.status] = by_status.get(step.status, 0) + 1
        if step.workbook_file_id:
            files.add(step.workbook_file_id)
        bucket = by_step_key.setdefault(step.step_key, {})
        bucket[step.status] = bucket.get(step.status, 0) + 1
        if step.status == WorkbookStep.Status.AWAITING_REVIEW:
            awaiting_review += 1

    file_count = len(files) or workbook.files.count()
    return {
        "file_count": file_count,
        "total_steps": steps.count(),
        "by_status": by_status,
        "by_step_key": by_step_key,
        "awaiting_review": awaiting_review,
    }


def _prior_steps_committed(step: WorkbookStep, *, exclude_self: bool = False) -> bool:
    recipe = _recipe(step.workbook)
    defs = {s.step_key: s for s in recipe.steps()}
    current_seq = defs[step.step_key].sequence
    qs = WorkbookStep.objects.filter(workbook=step.workbook, workbook_file=step.workbook_file)
    if exclude_self:
        qs = qs.exclude(pk=step.pk)
    for other in qs:
        other_def = defs.get(other.step_key)
        if other_def is None or other_def.sequence >= current_seq:
            continue
        if other.status not in (
            WorkbookStep.Status.COMMITTED,
            WorkbookStep.Status.SKIPPED,
        ):
            return False
    return True


def _unlock_ready_steps(workbook: Workbook) -> None:
    for step in WorkbookStep.objects.filter(
        workbook=workbook,
        status=WorkbookStep.Status.PENDING,
    ):
        if _prior_steps_committed(step):
            if step.step_key != "upload":
                step.status = WorkbookStep.Status.DRAFT
                step.save(update_fields=["status", "updated_at"])


def apply_batch_defaults(workbook: Workbook) -> int:
    """Merge workbook.batch_defaults into step drafts (dates, copyright metadata)."""
    defaults = workbook.batch_defaults or {}
    if not defaults:
        return 0

    updated = 0
    link_patch = {}
    if defaults.get("start_date"):
        link_patch["start_date"] = defaults["start_date"]
    if defaults.get("end_date"):
        link_patch["end_date"] = defaults["end_date"]

    copyright_patch = {}
    for key in (
        "licence_id",
        "copyright_owner_id",
        "licence_grantor_id",
        "published_date",
        "source_url",
    ):
        if defaults.get(key):
            copyright_patch[key] = defaults[key]

    if link_patch:
        for workbook_file in workbook.files.all():
            link_step = WorkbookStep.objects.filter(
                workbook=workbook,
                workbook_file=workbook_file,
                step_key="link_entities",
            ).first()
            if link_step and link_step.status != WorkbookStep.Status.COMMITTED:
                payload = {**(link_step.payload or {}), **link_patch}
                payload["workbook_file_id"] = str(workbook_file.id)
                link_step.payload = payload
                if link_step.status == WorkbookStep.Status.PENDING:
                    link_step.status = WorkbookStep.Status.DRAFT
                link_step.save(update_fields=["payload", "status", "updated_at"])
                updated += 1

    if copyright_patch:
        for workbook_file in workbook.files.all():
            for step_key in ("publish_reconciliation", "publish_ministerial_list"):
                publish_step = WorkbookStep.objects.filter(
                    workbook=workbook,
                    workbook_file=workbook_file,
                    step_key=step_key,
                ).first()
                if publish_step and publish_step.status != WorkbookStep.Status.COMMITTED:
                    payload = {**(publish_step.payload or {})}
                    file_metadata = {
                        **(payload.get("file_metadata") or {}),
                        **copyright_patch,
                    }
                    payload["file_metadata"] = file_metadata
                    payload["workbook_file_id"] = str(workbook_file.id)
                    publish_step.payload = payload
                    if publish_step.status == WorkbookStep.Status.PENDING:
                        publish_step.status = WorkbookStep.Status.DRAFT
                    publish_step.save(
                        update_fields=["payload", "status", "updated_at"]
                    )
                    updated += 1

    return updated
