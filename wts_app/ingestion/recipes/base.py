"""Pipeline recipe base types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

    from wts_app.models import Workbook, WorkbookStep


@dataclass(frozen=True)
class StepDefinition:
    step_key: str
    sequence: int
    requires_review: bool = True
    auto_advance: bool = False
    commit_writes_production: bool = True


class PipelineRecipe(Protocol):
    key: str
    batch_per_file: bool

    def steps(self) -> list[StepDefinition]: ...

    def initial_payload(self, *, workbook_file_id: str | None) -> dict: ...

    def validate_draft(self, step: WorkbookStep, payload: dict) -> dict: ...

    def commit_step(self, step: WorkbookStep, *, actor: AbstractUser) -> None: ...

    def on_step_committed(self, step: WorkbookStep) -> None: ...

    def can_start(self, step: WorkbookStep) -> None: ...

    def ui_schema(self, step_key: str) -> dict: ...

    def build_gemini_prompt(self, step: WorkbookStep) -> str: ...

    def apply_gemini_response(self, step: WorkbookStep, raw: dict) -> None: ...

    def rewind_to_step_key(self, rejected_step: WorkbookStep) -> str | None: ...
