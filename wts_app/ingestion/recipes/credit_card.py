"""Credit card reconciliation pipeline recipe."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from wts_app.ingestion.promote import promote_workbook_file
from wts_app.ingestion.schemas import validate_payload
from wts_app.models import (
    CreditCardExpense,
    CreditCardReconciliation,
    Person,
    WorkbookStep,
)
from wts_app.models.workbook_pipeline import WorkbookStep as WorkbookStepModel

from .base import StepDefinition


def credit_card_statement_file_name(
    *,
    person_display_name: str,
    start_date: date | str,
    end_date: date | str,
) -> str:
    """Site-facing File.file_name for a ministerial credit card statement."""
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date[:10])
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date[:10])

    def month_year(value: date) -> str:
        return value.strftime("%B %Y")

    if start_date.year == end_date.year and start_date.month == end_date.month:
        period = month_year(start_date)
    else:
        period = f"{month_year(start_date)} to {month_year(end_date)}"

    return (
        "Ministerial credit card reconciliations and statements for "
        f"{person_display_name} for {period}"
    )


class CreditCardReconciliationRecipe:
    key = "credit_card_reconciliation"
    batch_per_file = True

    def steps(self) -> list[StepDefinition]:
        return [
            StepDefinition("upload", 0, requires_review=False, commit_writes_production=False),
            StepDefinition("link_entities", 1, requires_review=True, commit_writes_production=False),
            StepDefinition("gemini_extract", 2, requires_review=True, commit_writes_production=False),
            StepDefinition(
                "publish_reconciliation",
                3,
                requires_review=True,
                commit_writes_production=True,
            ),
        ]

    def initial_payload(self, *, workbook_file_id: str | None) -> dict:
        if workbook_file_id:
            return {"workbook_file_id": workbook_file_id}
        return {}

    def validate_draft(self, step: WorkbookStep, payload: dict) -> dict:
        workbook = step.workbook
        recipe_key = workbook.recipe_key or self.key
        merged = {**(step.payload or {}), **payload}
        if step.step_key == "link_entities":
            validate_payload(recipe_key, "link_entities", merged)
            start = date.fromisoformat(merged["start_date"])
            end = date.fromisoformat(merged["end_date"])
            if start > end:
                raise ValueError("start_date must be on or before end_date.")
            if not Person.objects.filter(pk=merged["person_id"]).exists():
                raise ValueError("person_id does not exist.")
        return merged

    def can_start(self, step: WorkbookStep) -> None:
        if step.step_key != "gemini_extract":
            return
        link = self._get_step(step, "link_entities")
        if link.status not in (
            WorkbookStepModel.Status.COMMITTED,
            WorkbookStepModel.Status.AWAITING_REVIEW,
            WorkbookStepModel.Status.DRAFT,
        ):
            raise ValueError("link_entities must be completed before gemini_extract.")
        payload = link.payload or {}
        if not payload.get("person_id") or not payload.get("start_date"):
            raise ValueError("link_entities must include person_id and date range.")

    def commit_step(self, step: WorkbookStep, *, actor) -> None:
        if step.step_key == "upload":
            return
        if step.step_key == "link_entities":
            merged = self.validate_draft(step, step.payload or {})
            step.payload = merged
            return
        if step.step_key == "publish_reconciliation":
            self._commit_publish(step)
            return

    def on_step_committed(self, step: WorkbookStep) -> None:
        return

    def ui_schema(self, step_key: str) -> dict:
        schemas = {
            "upload": {"type": "upload", "title": "Upload"},
            "link_entities": {
                "type": "form",
                "title": "Link person and dates",
                "fields": [
                    {"name": "person_id", "type": "person_picker"},
                    {"name": "start_date", "type": "date"},
                    {"name": "end_date", "type": "date"},
                ],
            },
            "gemini_extract": {
                "type": "gemini",
                "title": "Extract transactions",
                "note": "Reads the staged file from private GCS (not public R2).",
            },
            "publish_reconciliation": {
                "type": "proposal_review",
                "title": "Review and publish",
                "proposal_step_key": "gemini_extract",
                "note": "Copies file to public storage and creates reconciliation records.",
            },
        }
        return schemas.get(step_key, {"type": "generic", "title": step_key})

    def build_gemini_prompt(self, step: WorkbookStep) -> str:
        link = self._get_step(step, "link_entities")
        link_payload = link.payload or {}
        person = Person.objects.get(pk=link_payload["person_id"])
        return (
            "Extract every credit card transaction from the attached statement. "
            "Explain any concerns with the data in a single sentence; if none, return null. "
            "Return a JSON object with keys: "
            "request_id (string), concerns (string or null), "
            "expenses (array of objects with date, merchant_name, description, "
            "amount_nzd, original_currency_code, original_amount). "
            "Use ISO dates (YYYY-MM-DD). "
            "Merchant name should be exactly as shown on the bank's credit card statement only."
            "Description should be human friendly and describe what was purchased based on the receipt, merchant information and reconciliation form."
            f"Statement period: {link_payload['start_date']} to {link_payload['end_date']}. "
            f"Cardholder: {person.display_name}."
        )

    def apply_gemini_response(self, step: WorkbookStep, raw: dict) -> None:
        data = raw
        if "parsed" in raw and isinstance(raw["parsed"], dict):
            data = raw["parsed"]
        proposal = {
            "concerns": data.get("concerns"),
            "expenses": data.get("expenses", []),
        }
        payload = dict(step.payload or {})
        payload["proposal"] = proposal
        payload["raw_response"] = raw
        step.payload = payload
        step.save(update_fields=["payload", "updated_at"])

    def rewind_to_step_key(self, rejected_step: WorkbookStep) -> str | None:
        if rejected_step.step_key == "publish_reconciliation":
            return "gemini_extract"
        if rejected_step.step_key == "gemini_extract":
            return "link_entities"
        return None

    def _get_step(self, step: WorkbookStep, step_key: str) -> WorkbookStep:
        qs = WorkbookStep.objects.filter(
            workbook=step.workbook,
            step_key=step_key,
        )
        if step.workbook_file_id:
            qs = qs.filter(workbook_file_id=step.workbook_file_id)
        return qs.get()

    def _file_metadata_for_publish(self, step: WorkbookStep) -> dict:
        payload_meta = (step.payload or {}).get("file_metadata") or {}
        workbook_meta = step.workbook.batch_defaults or {}
        merged = {}
        for key in (
            "licence_id",
            "copyright_owner_id",
            "licence_grantor_id",
            "published_date",
            "source_url",
        ):
            if payload_meta.get(key):
                merged[key] = payload_meta[key]
            elif workbook_meta.get(key):
                merged[key] = workbook_meta[key]
        return merged

    def _commit_publish(self, step: WorkbookStep) -> None:
        workbook_file = step.workbook_file
        if workbook_file is None:
            raise ValueError("publish_reconciliation requires a workbook file.")

        gemini_step = self._get_step(step, "gemini_extract")
        link = self._get_step(step, "link_entities")
        link_payload = link.payload or {}
        proposal = (gemini_step.payload or {}).get("proposal") or {}
        if step.payload and step.payload.get("proposal"):
            proposal = step.payload["proposal"]

        person = Person.objects.get(pk=link_payload["person_id"])
        file_metadata = self._file_metadata_for_publish(step)
        file_metadata["file_name"] = credit_card_statement_file_name(
            person_display_name=person.display_name,
            start_date=link_payload["start_date"],
            end_date=link_payload["end_date"],
        )
        file_metadata["file_description"] = ""

        file_obj = promote_workbook_file(
            workbook_file,
            file_metadata=file_metadata,
        )
        with transaction.atomic():
            reconciliation = CreditCardReconciliation.objects.create(
                person=person,
                file=file_obj,
                start_date=link_payload["start_date"],
                end_date=link_payload["end_date"],
                concerns=proposal.get("concerns"),
            )
            expenses = []
            for entry in proposal.get("expenses") or []:
                normalized = self._normalize_expense(entry)
                if normalized is None:
                    continue
                expenses.append(
                    CreditCardExpense(
                        reconciliation=reconciliation,
                        **normalized,
                    )
                )
            if expenses:
                CreditCardExpense.objects.bulk_create(expenses)

            publish_payload = dict(step.payload or {})
            publish_payload["file_id"] = str(file_obj.id)
            step.payload = publish_payload
            ct = ContentType.objects.get_for_model(reconciliation)
            step.production_content_type = ct
            step.production_object_id = str(reconciliation.id)

    def _normalize_expense(self, entry: dict) -> dict | None:
        try:
            date_value = date.fromisoformat(str(entry.get("date", ""))[:10])
        except ValueError:
            return None
        merchant = (entry.get("merchant_name") or "").strip()
        if not merchant:
            return None
        original_currency = (entry.get("original_currency_code") or "").strip().upper()
        original_amount = self._parse_decimal(entry.get("original_amount"))
        amount_nzd = self._parse_decimal(entry.get("amount_nzd"))
        if original_currency == "NZD" and original_amount is not None and amount_nzd is None:
            amount_nzd = original_amount
        if amount_nzd is None or original_amount is None or not original_currency:
            return None
        description = entry.get("description")
        if description:
            description = str(description).strip() or None
        return {
            "date": date_value,
            "merchant_name": merchant,
            "description": description,
            "amount_nzd": amount_nzd,
            "original_currency_code": original_currency,
            "original_amount": original_amount,
        }

    @staticmethod
    def _parse_decimal(value) -> Decimal | None:
        if value is None:
            return None
        try:
            if isinstance(value, str):
                value = value.replace(",", "")
            return Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            return None
