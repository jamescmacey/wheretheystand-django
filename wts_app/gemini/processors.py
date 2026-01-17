"""Gemini batch processors."""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import List, Optional, Sequence

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from google.genai import types

from wts_app.gemini.client import GeminiClient
from wts_app.models.credit_card_expenses import (
    CreditCardExpense,
    CreditCardReconciliation,
)
from wts_app.models.gemini import GeminiBatchItem


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
        statuses = [
            GeminiBatchItem.Status.PENDING,
            GeminiBatchItem.Status.SUBMITTED,
            GeminiBatchItem.Status.PROCESSED,
        ]
        if not include_failed:
            statuses.append(GeminiBatchItem.Status.FAILED)
        existing_ids = (
            GeminiBatchItem.objects.filter(
                content_type=content_type,
                status__in=statuses,
            )
            .values_list("object_id", flat=True)
        )
        return queryset.exclude(id__in=existing_ids)


class CreditCardReconciliationProcessor(GeminiBatchProcessor):
    """Gemini processor for credit card reconciliation files."""

    name = "credit_card_reconciliation"

    response_schema = {
        "type": "object",
        "properties": {
            "request_id": {"type": "string"},
            "expenses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "merchant_name": {"type": "string"},
                        "description": {"type": ["string", "null"]},
                        "amount_nzd": {"type": ["number", "null"]},
                        "original_currency_code": {"type": "string"},
                        "original_amount": {"type": ["number", "null"]},
                    },
                    "required": [
                        "date",
                        "merchant_name",
                        "original_currency_code",
                        "original_amount",
                        "amount_nzd",
                    ],
                },
            },
        },
        "required": ["request_id", "expenses"],
    }

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
                "Return only JSON that matches the provided response schema."
            ),
            response_mime_type="application/json",
            response_json_schema=self.response_schema,
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
        item.response_payload = raw_payload
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
        reconciliation = item.content_object

        created_count = self._persist_expenses(reconciliation, expenses)
        item.status = GeminiBatchItem.Status.PROCESSED
        item.processed_at = timezone.now()
        item.error_message = None
        item.save(update_fields=["status", "processed_at", "error_message", "response_payload", "updated_at"])
        return created_count

    def _build_prompt(self, reconciliation: CreditCardReconciliation, request_id: str) -> str:
        return (
            "Extract every credit card transaction from the attached statement. "
            "Return a JSON object that matches the response schema. "
            "Use ISO dates (YYYY-MM-DD). "
            "If the original currency is NZD, set amount_nzd equal to original_amount. "
            "If amounts are missing, return null. "
            f"Request ID: {request_id}. "
            f"Statement period: {reconciliation.start_date} to {reconciliation.end_date}. "
            f"Cardholder: {reconciliation.person.display_name}."
        )

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


PROCESSOR_REGISTRY = {
    CreditCardReconciliationProcessor.name: CreditCardReconciliationProcessor,
}


def get_processor(name: str, *, client: GeminiClient) -> GeminiBatchProcessor:
    try:
        processor_cls = PROCESSOR_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown processor '{name}'.") from exc
    return processor_cls(client)
