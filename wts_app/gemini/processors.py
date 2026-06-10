"""Gemini batch processors."""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
import base64
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import List, Optional, Sequence

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from google.genai import types

from wts_app.gemini.client import GeminiClient
from wts_app.ingestion.orchestrator import complete_async
from wts_app.ingestion.recipes.credit_card import CREDIT_CARD_GEMINI_RESPONSE_SCHEMA
from wts_app.ingestion.recipes.registry import get_recipe
from wts_app.models.credit_card_expenses import (
    CreditCardExpense,
    CreditCardReconciliation,
)
from wts_app.models.gemini import GeminiBatchItem
from wts_app.models.workbook_pipeline import WorkbookStep
from django.conf import settings


@dataclass
class PreparedRequest:
    item: GeminiBatchItem
    request: types.InlinedRequest
    request_payload: dict


class GeminiBatchProcessor:
    """Base processor for Gemini batch jobs."""

    name = "base"

    def __init__(self, client: GeminiClient):
        self.client = client

    def get_queryset(self, *, ids: Optional[Sequence[str]] = None, include_failed: bool = False):
        raise NotImplementedError

    def build_request(
        self,
        *,
        item: GeminiBatchItem,
        requested_model: str,
    ) -> PreparedRequest:
        raise NotImplementedError

    def handle_response(
        self,
        *,
        item: GeminiBatchItem,
        response: Optional[types.GenerateContentResponse],
        error: Optional[types.JobError],
        raw_payload: dict,
    ) -> int:
        raise NotImplementedError

    def _exclude_previously_submitted(
        self,
        queryset,
        *,
        include_failed: bool,
    ):
        content_type = ContentType.objects.get_for_model(queryset.model)
        blocking_statuses = [
            GeminiBatchItem.Status.SUBMITTED,
            GeminiBatchItem.Status.PROCESSED,
        ]
        if not include_failed:
            blocking_statuses.append(GeminiBatchItem.Status.FAILED)

        blocking_ids = set(
            GeminiBatchItem.objects.filter(
                content_type=content_type,
                status__in=blocking_statuses,
            ).values_list("object_id", flat=True)
        )
        # Only block in-flight pending items once a Gemini batch_name exists.
        blocking_ids.update(
            GeminiBatchItem.objects.filter(
                content_type=content_type,
                status=GeminiBatchItem.Status.PENDING,
                job__batch_name__isnull=False,
            )
            .exclude(job__batch_name="")
            .values_list("object_id", flat=True)
        )
        if not blocking_ids:
            return queryset
        return queryset.exclude(id__in=blocking_ids)

    @staticmethod
    def _serialize_json_safe(value):
        def _default(obj):
            if isinstance(obj, (bytes, bytearray)):
                return base64.b64encode(obj).decode("ascii")
            return str(obj)

        try:
            return json.loads(json.dumps(value, default=_default))
        except TypeError:
            return json.loads(json.dumps(str(value)))


class CreditCardReconciliationProcessor(GeminiBatchProcessor):
    """Gemini processor for credit card reconciliation files."""

    name = "credit_card_reconciliation"

    response_schema = CREDIT_CARD_GEMINI_RESPONSE_SCHEMA

    def get_queryset(self, *, ids: Optional[Sequence[str]] = None, include_failed: bool = False):
        queryset = CreditCardReconciliation.objects.select_related("person", "file").all()
        if ids:
            queryset = queryset.filter(id__in=ids)
        return self._exclude_previously_submitted(queryset, include_failed=include_failed)

    def build_request(
        self,
        *,
        item: GeminiBatchItem,
        requested_model: str,
    ) -> PreparedRequest:
        reconciliation: CreditCardReconciliation = item.content_object
        prompt = self._build_prompt(reconciliation, request_id=str(item.id))
        file_obj = reconciliation.file
        mime_type = self._resolve_mime_type(file_obj.file_name, file_obj.file_type)


        with file_obj.file.open("rb") as fh:
            file_bytes = fh.read()

        file_buffer = BytesIO(file_bytes)
        file_buffer.seek(0)
        upload = self.client.upload_file(
            file_buffer,
            mime_type=mime_type,
            display_name=file_obj.file_name,
        )

        config = types.GenerateContentConfig(
            temperature=0,
            system_instruction=(
                "Return only JSON."
            ),
            response_mime_type="application/json",
        )

        inlined_request = types.InlinedRequest(
            contents=[prompt, upload],
            metadata={
                "item_id": str(item.id),
                "reconciliation_id": str(reconciliation.id),
            },
            config=config,
        )

        request_payload = {
            "prompt": prompt,
            "file_name": upload.name,
            "file_uri": upload.uri,
            "metadata": inlined_request.metadata or {},
            "response_schema": self.response_schema,
            "model": requested_model,
        }

        return PreparedRequest(
            item=item,
            request=inlined_request,
            request_payload=request_payload,
        )

    def handle_response(
        self,
        *,
        item: GeminiBatchItem,
        response: Optional[types.GenerateContentResponse],
        error: Optional[types.JobError],
        raw_payload: dict,
    ) -> int:
        item.response_payload = self._serialize_json_safe(raw_payload)
        if error:
            item.status = GeminiBatchItem.Status.FAILED
            item.error_message = error.message or "Gemini response error."
            item.processed_at = timezone.now()
            item.save(update_fields=["status", "error_message", "processed_at", "response_payload", "updated_at"])
            return 0

        if response is None:
            item.status = GeminiBatchItem.Status.FAILED
            item.error_message = "Missing Gemini response payload."
            item.processed_at = timezone.now()
            item.save(update_fields=["status", "error_message", "processed_at", "response_payload", "updated_at"])
            return 0

        data = self._parse_response_payload(response)
        expenses = data.get("expenses", [])
        concerns = self._normalize_concerns(data.get("concerns"))
        reconciliation = item.content_object

        created_count = self._persist_expenses(reconciliation, expenses)
        if concerns is not None and concerns != reconciliation.concerns:
            reconciliation.concerns = concerns
            reconciliation.save(update_fields=["concerns", "updated_at"])
        item.status = GeminiBatchItem.Status.PROCESSED
        item.processed_at = timezone.now()
        item.error_message = None
        item.save(update_fields=["status", "processed_at", "error_message", "response_payload", "updated_at"])
        return created_count

    def _build_prompt(self, reconciliation: CreditCardReconciliation, request_id: str) -> str:
        return (
            "Extract every credit card transaction from the attached statement. "
            "Explain any concerns with the data in a single sentence; if none, return null. "
            "Return a JSON object with keys: "
            "request_id (string), concerns (string or null), "
            "expenses (array of objects with date, merchant_name, description, "
            "amount_nzd, original_currency_code, original_amount). "
            "Use ISO dates (YYYY-MM-DD). "
            "If the original currency is NZD, set amount_nzd equal to original_amount. "
            "If amounts are missing, return null. "
            f"Request ID: {request_id}. "
            f"Statement period: {reconciliation.start_date} to {reconciliation.end_date}. "
            f"Cardholder: {reconciliation.person.display_name}."
        )

    def _normalize_concerns(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = value.strip()
        return cleaned or None

    def _resolve_mime_type(self, file_name: str, file_type: Optional[str]) -> str:
        if file_type:
            if "/" in file_type:
                return file_type
            guessed = mimetypes.guess_type(f"file.{file_type}")[0]
            if guessed:
                return guessed
        guessed = mimetypes.guess_type(file_name)[0]
        return guessed or "application/octet-stream"

    def _parse_response_payload(self, response: types.GenerateContentResponse) -> dict:
        if response.parsed is not None:
            if isinstance(response.parsed, dict):
                return response.parsed
        text = response.text
        if not text:
            raise ValueError("Gemini response text is empty.")
        return json.loads(text)

    def _persist_expenses(self, reconciliation: CreditCardReconciliation, expenses: List[dict]) -> int:
        to_create: List[CreditCardExpense] = []
        for entry in expenses:
            parsed = self._normalize_expense(entry)
            if parsed is None:
                continue
            to_create.append(
                CreditCardExpense(
                    reconciliation=reconciliation,
                    date=parsed["date"],
                    merchant_name=parsed["merchant_name"],
                    description=parsed.get("description"),
                    amount_nzd=parsed["amount_nzd"],
                    original_currency_code=parsed["original_currency_code"],
                    original_amount=parsed["original_amount"],
                )
            )
        if not to_create:
            return 0
        with transaction.atomic():
            CreditCardExpense.objects.bulk_create(to_create)
        return len(to_create)

    def _normalize_expense(self, entry: dict) -> Optional[dict]:
        date_value = self._parse_date(entry.get("date"))
        merchant = (entry.get("merchant_name") or "").strip()
        if not date_value or not merchant:
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
            description = description.strip()

        return {
            "date": date_value,
            "merchant_name": merchant,
            "description": description or None,
            "amount_nzd": amount_nzd,
            "original_currency_code": original_currency,
            "original_amount": original_amount,
        }

    def _parse_date(self, value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    def _parse_decimal(self, value: Optional[object]) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            if isinstance(value, str):
                value = value.replace(",", "")
            return Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            return None


class WorkbookStepGeminiProcessor(GeminiBatchProcessor):
    """Gemini processor targeting WorkbookStep (staging-only persist)."""

    name = "workbook_step_gemini"

    def get_queryset(self, *, ids: Optional[Sequence[str]] = None, include_failed: bool = False):
        queryset = WorkbookStep.objects.filter(step_key="gemini_extract").select_related(
            "workbook", "workbook_file"
        )
        if ids:
            queryset = queryset.filter(id__in=ids)
        return self._exclude_previously_submitted(queryset, include_failed=include_failed)

    def build_request(
        self,
        *,
        item: GeminiBatchItem,
        requested_model: str,
    ) -> PreparedRequest:
        step: WorkbookStep = item.content_object
        workbook = step.workbook
        recipe = get_recipe(workbook.recipe_key)
        prompt = recipe.build_gemini_prompt(step)
        response_schema = (
            recipe.gemini_response_schema()
            if hasattr(recipe, "gemini_response_schema")
            else CreditCardReconciliationProcessor.response_schema
        )

        workbook_file = step.workbook_file
        if workbook_file is None or not workbook_file.file:
            raise ValueError("gemini_extract requires a staged workbook file on GCS.")

        from wts_app.ingestion.staging_files import (
            workbook_file_gemini_display_name,
            workbook_file_mime_type,
            workbook_file_gcs_uri,
        )
        mime_type = workbook_file_mime_type(workbook_file)
        display_name = workbook_file_gemini_display_name(workbook_file)
        gcs_uri = workbook_file_gcs_uri(workbook_file)

        registered_files = self.client.register_files(uris=[gcs_uri])
        file_part = registered_files[0]
        input_strategy = "files_api_registered"
        file_ref_name = file_part.name
        file_ref_uri = file_part.uri

        config = types.GenerateContentConfig(
            temperature=0,
            system_instruction="Return only JSON.",
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        inlined_request = types.InlinedRequest(
            contents=[prompt, file_part],
            metadata={"item_id": str(item.id), "step_id": str(step.id)},
            config=config,
        )
        request_payload = {
            "prompt": prompt,
            "file_name": file_ref_name,
            "file_uri": file_ref_uri,
            "input_strategy": input_strategy,
            "metadata": inlined_request.metadata or {},
            "response_schema": response_schema,
            "model": requested_model,
        }
        return PreparedRequest(
            item=item,
            request=inlined_request,
            request_payload=request_payload,
        )

    def handle_response(
        self,
        *,
        item: GeminiBatchItem,
        response: Optional[types.GenerateContentResponse],
        error: Optional[types.JobError],
        raw_payload: dict,
    ) -> int:
        item.response_payload = self._serialize_json_safe(raw_payload)
        step: WorkbookStep = item.content_object
        if error:
            item.status = GeminiBatchItem.Status.FAILED
            item.error_message = error.message or "Gemini response error."
            item.processed_at = timezone.now()
            item.save(
                update_fields=[
                    "status",
                    "error_message",
                    "processed_at",
                    "response_payload",
                    "updated_at",
                ]
            )
            step.status = WorkbookStep.Status.FAILED
            step.error_message = item.error_message
            step.save(update_fields=["status", "error_message", "updated_at"])
            return 0

        if response is None:
            item.status = GeminiBatchItem.Status.FAILED
            item.error_message = "Missing Gemini response payload."
            item.processed_at = timezone.now()
            item.save(
                update_fields=[
                    "status",
                    "error_message",
                    "processed_at",
                    "response_payload",
                    "updated_at",
                ]
            )
            step.status = WorkbookStep.Status.FAILED
            step.error_message = item.error_message
            step.save(update_fields=["status", "error_message", "updated_at"])
            return 0

        data = self._parse_response_payload(response)
        recipe = get_recipe(step.workbook.recipe_key)
        recipe.apply_gemini_response(step, data)
        complete_async(step, awaiting_review=True)

        item.status = GeminiBatchItem.Status.PROCESSED
        item.processed_at = timezone.now()
        item.error_message = None
        item.save(
            update_fields=[
                "status",
                "processed_at",
                "error_message",
                "response_payload",
                "updated_at",
            ]
        )
        return 1

    def _resolve_mime_type(self, file_name: str, file_type: Optional[str]) -> str:
        if file_type:
            if "/" in file_type:
                return file_type
            guessed = mimetypes.guess_type(f"file.{file_type}")[0]
            if guessed:
                return guessed
        guessed = mimetypes.guess_type(file_name)[0]
        return guessed or "application/octet-stream"

    def _parse_response_payload(self, response: types.GenerateContentResponse) -> dict:
        if response.parsed is not None and isinstance(response.parsed, dict):
            return response.parsed
        text = response.text
        if not text:
            raise ValueError("Gemini response text is empty.")
        return json.loads(text)


PROCESSOR_REGISTRY = {
    CreditCardReconciliationProcessor.name: CreditCardReconciliationProcessor,
    WorkbookStepGeminiProcessor.name: WorkbookStepGeminiProcessor,
}


def get_processor(name: str, *, client: GeminiClient) -> GeminiBatchProcessor:
    try:
        processor_cls = PROCESSOR_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown processor '{name}'.") from exc
    return processor_cls(client)
