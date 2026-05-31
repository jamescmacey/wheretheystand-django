"""Ministerial list workbook pipeline recipe."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from wts_app.ingestion.promote import promote_workbook_file
from wts_app.ingestion.schemas import validate_payload
from wts_app.ingestion.staging_files import workbook_file_mime_type
from wts_app.models import (
    MinisterialAffiliation,
    MinisterialPortfolio,
    Person,
    WorkbookStep,
)
from wts_app.models.workbook_pipeline import WorkbookStep as WorkbookStepModel

from .base import StepDefinition

GEMINI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "people": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "positions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "position": {"type": "string"},
                                "category": {"type": "string", "enum": ["p", "r"]},
                            },
                            "required": ["position", "category"],
                        },
                    },
                },
                "required": ["name", "positions"],
            },
        },
    },
    "required": ["people"],
}

_CONJUNCTION_PATTERN = r"(of the|for the|of|for)"

_POSITION_WITH_CONJUNCTION = re.compile(
    r"^(Associate Minister|Minister|Parliamentary Under-Secretary|Parliamentary Under Secretary)"
    rf"\s+{_CONJUNCTION_PATTERN}\s+(.+)$",
    re.IGNORECASE,
)
_TITLE_CONJUNCTION_PORTFOLIO = re.compile(
    rf"^(?P<title>.+?)\s+(?P<conjunction>{_CONJUNCTION_PATTERN})\s+(?P<portfolio>.+)$",
    re.IGNORECASE,
)

# Standalone portfolios: stored on MinisterialPortfolio with no title or conjunction.
_PORTFOLIOS_WITHOUT_TITLE = frozenset(
    {
        "prime minister",
        "deputy prime minister",
        "attorney-general",
        "leader of the house",
        "deputy leader of the house"
    }
)


def _normalize_conjunction(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def parse_position(raw: str) -> dict:
    """
    Split a ministerial position string into title, conjunction, and portfolio name.

    Examples:
      - Minister of Foreign Affairs -> Minister / of / Foreign Affairs
      - Minister Responsible for the GCSB -> Minister Responsible / for the / GCSB
      - Prime Minister -> (no title) / (no conjunction) / Prime Minister
    """
    text = (raw or "").strip()
    if not text:
        return {
            "raw": raw or "",
            "title": None,
            "conjunction": None,
            "portfolio_name": None,
        }

    if text.casefold() in _PORTFOLIOS_WITHOUT_TITLE:
        return {
            "raw": text,
            "title": None,
            "conjunction": None,
            "portfolio_name": text,
        }

    match = _POSITION_WITH_CONJUNCTION.match(text)
    if match:
        title = match.group(1)
        conjunction_raw = match.group(2)
        if title.lower().startswith("parliamentary under"):
            title = "Parliamentary Under-Secretary"
        return {
            "raw": text,
            "title": title,
            "conjunction": _normalize_conjunction(conjunction_raw),
            "portfolio_name": match.group(3).strip(),
        }

    match = _TITLE_CONJUNCTION_PORTFOLIO.match(text)
    if match:
        return {
            "raw": text,
            "title": match.group("title").strip(),
            "conjunction": _normalize_conjunction(match.group("conjunction")),
            "portfolio_name": match.group("portfolio").strip(),
        }

    return {
        "raw": text,
        "title": None,
        "conjunction": None,
        "portfolio_name": text,
    }


def suggest_portfolio_id(portfolio_name: str | None) -> str | None:
    if not portfolio_name:
        return None
    exact = MinisterialPortfolio.objects.filter(name__iexact=portfolio_name).first()
    if exact:
        return str(exact.id)
    contains = (
        MinisterialPortfolio.objects.filter(name__icontains=portfolio_name)
        .order_by("name")
        .first()
    )
    if contains:
        return str(contains.id)
    return None


_PREFIX_TITLES_PATTERN = re.compile(
    r"^(?:(?:Rt\s+Hon\s+Dr|Rt\s+Hon|Hon\s+Dr|Hon)\.?\s+)+",
    re.IGNORECASE,
)
_POSTNOMINALS_PATTERN = re.compile(
    r"(?:[,\s]+(?:KC|MP|PC)\.?)*\s*$",
    re.IGNORECASE,
)


def normalize_extracted_person_name(name: str) -> str:
    """
    Strip honorific prefixes and postnominal suffixes from a ministerial list name
    so it can be matched to Person.display_name.
    """
    text = re.sub(r"\s+", " ", (name or "").strip())
    if not text:
        return ""

    text = _PREFIX_TITLES_PATTERN.sub("", text).strip()
    while True:
        stripped = _POSTNOMINALS_PATTERN.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    return text


def _person_match_key(name: str) -> str:
    return normalize_extracted_person_name(name).casefold()


def suggest_person_id(display_name: str | None) -> str | None:
    if not display_name:
        return None

    raw = display_name.strip()
    normalized = normalize_extracted_person_name(raw)
    candidates = [c for c in (raw, normalized) if c]

    for candidate in candidates:
        exact = Person.objects.filter(display_name__iexact=candidate).first()
        if exact:
            return str(exact.id)

    if not normalized:
        return None

    target_key = normalized.casefold()
    parts = normalized.split()
    if parts:
        by_last_name = Person.objects.filter(last_name__iexact=parts[-1])
        for person in by_last_name:
            if _person_match_key(person.display_name) == target_key:
                return str(person.id)

    fuzzy = Person.objects.filter(display_name__icontains=normalized).order_by(
        "display_name"
    )[:50]
    key_matches = [p for p in fuzzy if _person_match_key(p.display_name) == target_key]
    if len(key_matches) == 1:
        return str(key_matches[0].id)

    if len(parts) >= 2 and len(key_matches) == 0:
        sole = (
            Person.objects.filter(
                last_name__iexact=parts[-1],
                first_name__istartswith=parts[0],
            )
            .order_by("display_name")
            .first()
        )
        if sole and _person_match_key(sole.display_name) == target_key:
            return str(sole.id)

    return None


def enrich_position(raw: str, *, category: str | None = None) -> dict:
    parsed = parse_position(raw)
    portfolio_name = parsed.get("portfolio_name")
    return {
        **parsed,
        "category": normalize_category(category),
        "portfolio_id": suggest_portfolio_id(portfolio_name),
    }


def normalize_category(value: str | None) -> str:
    """Normalize Gemini/list category to MinisterialAffiliation.type ('p' or 'r')."""
    if value is None or str(value).strip() == "":
        return "p"
    text = str(value).strip().lower()
    if text in ("p", "portfolio"):
        return "p"
    if text in ("r", "responsibility"):
        return "r"
    raise ValueError(f"Invalid category '{value}', expected 'p' or 'r'.")


def _normalize_affiliation_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def affiliation_signature(
    *,
    person_id: UUID | str,
    portfolio_id: UUID | str,
    title: str | None,
    conjunction: str | None,
    affiliation_type: str,
) -> tuple[str, str, str | None, str | None, str]:
    return (
        str(person_id),
        str(portfolio_id),
        _normalize_affiliation_text(title),
        _normalize_affiliation_text(conjunction),
        normalize_category(affiliation_type),
    )


@dataclass(frozen=True)
class DesiredAffiliation:
    person_id: str
    portfolio_id: str
    title: str | None
    conjunction: str | None
    type: str
    specialisation: str | None

    @property
    def signature(self) -> tuple[str, str, str | None, str | None, str]:
        return affiliation_signature(
            person_id=self.person_id,
            portfolio_id=self.portfolio_id,
            title=self.title,
            conjunction=self.conjunction,
            affiliation_type=self.type,
        )


def ministerial_list_file_name(*, effective_date: date | str) -> str:
    if isinstance(effective_date, str):
        effective_date = date.fromisoformat(effective_date[:10])
    return f"Ministerial list as at {effective_date.strftime('%d %B %Y')}"


MINISTERIAL_LIST_DOCUMENT_CATEGORY = "Ministerial lists"


class MinisterialListRecipe:
    key = "ministerial_list"
    batch_per_file = True

    def steps(self) -> list[StepDefinition]:
        return [
            StepDefinition("upload", 0, requires_review=False, commit_writes_production=False),
            StepDefinition("gemini_extract", 1, requires_review=True, commit_writes_production=False),
            StepDefinition("link_entities", 2, requires_review=True, commit_writes_production=False),
            StepDefinition(
                "publish_ministerial_list",
                3,
                requires_review=True,
                commit_writes_production=True,
            ),
        ]

    def initial_payload(self, *, workbook_file_id: str | None) -> dict:
        if workbook_file_id:
            return {"workbook_file_id": workbook_file_id}
        return {}

    def gemini_response_schema(self) -> dict:
        return GEMINI_RESPONSE_SCHEMA

    def validate_draft(self, step: WorkbookStep, payload: dict) -> dict:
        workbook = step.workbook
        recipe_key = workbook.recipe_key or self.key
        merged = {**(step.payload or {}), **payload}
        if step.step_key == "link_entities":
            merged = {**(step.payload or {}), **payload}
            self._normalize_link_entries(merged.get("entries") or [])
            validate_payload(recipe_key, "link_entities", merged)
        if step.step_key == "publish_ministerial_list":
            if not merged.get("effective_date"):
                raise ValueError("effective_date is required for publication.")
            date.fromisoformat(str(merged["effective_date"])[:10])
        return merged

    @staticmethod
    def _normalize_link_entries(entries: list[dict]) -> None:
        """Coerce empty picker values to null so draft JSON schema validation passes."""
        for entry in entries:
            if entry.get("person_id") == "":
                entry["person_id"] = None
            for position in entry.get("positions") or []:
                if position.get("portfolio_id") == "":
                    position["portfolio_id"] = None
                position["category"] = normalize_category(position.get("category"))

    def _validate_link_entities_for_commit(self, payload: dict) -> None:
        entries = payload.get("entries") or []
        if not entries:
            raise ValueError("link_entities must include at least one person.")
        for entry in entries:
            person_id = entry.get("person_id")
            if not person_id:
                name = entry.get("extracted_name") or "Unknown"
                raise ValueError(f"Each person row must have person_id ({name}).")
            if not Person.objects.filter(pk=person_id).exists():
                raise ValueError(f"person_id does not exist ({entry.get('extracted_name')}).")
            for position in entry.get("positions") or []:
                if not position.get("portfolio_id"):
                    raise ValueError(
                        f"Each position must have portfolio_id ({entry.get('extracted_name')})."
                    )
                normalize_category(position.get("category"))

    def can_start(self, step: WorkbookStep) -> None:
        if step.step_key != "gemini_extract":
            return
        upload = self._get_step(step, "upload")
        if upload.status != WorkbookStepModel.Status.COMMITTED:
            raise ValueError("upload must be committed before gemini_extract.")

    def commit_step(self, step: WorkbookStep, *, actor) -> None:
        if step.step_key == "upload":
            return
        if step.step_key == "link_entities":
            merged = self.validate_draft(step, step.payload or {})
            self._validate_link_entities_for_commit(merged)
            step.payload = merged
            return
        if step.step_key == "publish_ministerial_list":
            merged = self.validate_draft(step, step.payload or {})
            step.payload = merged
            self._commit_publish(step)
            return

    def on_step_committed(self, step: WorkbookStep) -> None:
        return

    def ui_schema(self, step_key: str) -> dict:
        schemas = {
            "upload": {"type": "upload", "title": "Upload"},
            "gemini_extract": {
                "type": "gemini",
                "title": "Extract ministerial list",
                "note": "Reads the staged file from private GCS.",
            },
            "link_entities": {
                "type": "ministerial_link",
                "title": "Link people and portfolios",
            },
            "publish_ministerial_list": {
                "type": "ministerial_publish",
                "title": "Review and publish",
                "note": "Set the appointment date, promote the file, and update affiliations.",
            },
        }
        return schemas.get(step_key, {"type": "generic", "title": step_key})

    def build_gemini_prompt(self, step: WorkbookStep) -> str:
        return (
            "Extract every person named in the attached ministerial list document "
            "together with each ministerial position or title held by that person. "
            "Return JSON with a single key `people`: an array of objects, each with "
            "`name` (full name as shown) and `positions` (array of objects with "
            "`position` (string exactly as written, e.g. 'Minister of Foreign Affairs') "
            "and `category` ('p' for portfolio column, 'r' for responsibility column)). "
            "Include all roles listed for each person."
        )

    def apply_gemini_response(self, step: WorkbookStep, raw: dict) -> None:
        data = raw
        if "parsed" in raw and isinstance(raw["parsed"], dict):
            data = raw["parsed"]
        people = data.get("people")
        if people is None and isinstance(data, list):
            people = data

        proposal_entries = []
        for person in people or []:
            name = (person.get("name") or "").strip()
            positions = []
            for raw_position in person.get("positions") or []:
                if isinstance(raw_position, str) and raw_position.strip():
                    positions.append(enrich_position(raw_position.strip()))
                elif isinstance(raw_position, dict):
                    pos_text = (
                        raw_position.get("position")
                        or raw_position.get("raw")
                        or ""
                    ).strip()
                    if pos_text:
                        positions.append(
                            enrich_position(
                                pos_text,
                                category=raw_position.get("category"),
                            )
                        )
            proposal_entries.append(
                {
                    "extracted_name": name,
                    "person_id": suggest_person_id(name),
                    "positions": positions,
                }
            )

        payload = dict(step.payload or {})
        payload["proposal"] = {"people": proposal_entries}
        payload["raw_response"] = raw
        step.payload = payload
        step.save(update_fields=["payload", "updated_at"])

        self._seed_link_entities_from_proposal(step, proposal_entries)

    def rewind_to_step_key(self, rejected_step: WorkbookStep) -> str | None:
        if rejected_step.step_key == "publish_ministerial_list":
            return "link_entities"
        if rejected_step.step_key == "link_entities":
            return "gemini_extract"
        if rejected_step.step_key == "gemini_extract":
            return "upload"
        return None

    def _seed_link_entities_from_proposal(
        self,
        gemini_step: WorkbookStep,
        proposal_entries: list[dict],
    ) -> None:
        try:
            link = self._get_step(gemini_step, "link_entities")
        except WorkbookStep.DoesNotExist:
            return

        existing = link.payload or {}
        if existing.get("entries") and link.status == WorkbookStepModel.Status.COMMITTED:
            return

        link.payload = {
            **existing,
            "workbook_file_id": str(gemini_step.workbook_file_id or ""),
            "entries": proposal_entries,
        }
        if link.status == WorkbookStepModel.Status.PENDING:
            link.status = WorkbookStepModel.Status.DRAFT
        link.save(update_fields=["payload", "status", "updated_at"])

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
            raise ValueError("publish_ministerial_list requires a workbook file.")

        publish_payload = step.payload or {}
        effective_date = date.fromisoformat(str(publish_payload["effective_date"])[:10])

        link = self._get_step(step, "link_entities")
        link_payload = link.payload or {}
        entries = link_payload.get("entries") or []
        if not entries:
            raise ValueError("link_entities must include at least one person.")

        file_metadata = self._file_metadata_for_publish(step)
        display_name = ministerial_list_file_name(effective_date=effective_date)
        file_metadata["file_name"] = display_name
        file_metadata["file_description"] = ""
        file_metadata["published_date"] = effective_date.isoformat()
        file_metadata["document_name"] = display_name
        file_metadata["document_category_name"] = MINISTERIAL_LIST_DOCUMENT_CATEGORY
        file_metadata["file_type"] = workbook_file_mime_type(workbook_file)

        file_obj = promote_workbook_file(
            workbook_file,
            file_metadata=file_metadata,
        )

        day_before = effective_date - timedelta(days=1)
        desired_rows = self._desired_affiliations_from_entries(entries)
        if not desired_rows:
            raise ValueError("link_entities must include at least one position.")

        desired_signatures = {row.signature for row in desired_rows}
        portfolio_ids = {row.portfolio_id for row in desired_rows}

        with transaction.atomic():
            active_on_list_portfolios = self._active_affiliations_as_of(
                effective_date,
            ).filter(portfolio_id__in=portfolio_ids)

            continued_ids: set[UUID | str] = set()
            matched_desired_signatures: set[
                tuple[str, str, str | None, str | None, str]
            ] = set()
            for affiliation in active_on_list_portfolios:
                signature = affiliation_signature(
                    person_id=affiliation.person_id,
                    portfolio_id=affiliation.portfolio_id,
                    title=affiliation.title,
                    conjunction=affiliation.conjunction,
                    affiliation_type=affiliation.type,
                )
                if signature in desired_signatures:
                    continued_ids.add(affiliation.id)
                    matched_desired_signatures.add(signature)

            ended_count = active_on_list_portfolios.exclude(
                id__in=continued_ids,
            ).update(end_date=day_before)

            created_count = 0
            skipped_count = 0
            for desired in desired_rows:
                if desired.signature in matched_desired_signatures:
                    skipped_count += 1
                    continue

                MinisterialAffiliation.objects.create(
                    person_id=desired.person_id,
                    portfolio_id=desired.portfolio_id,
                    title=desired.title,
                    conjunction=desired.conjunction,
                    type=desired.type,
                    specialisation=desired.specialisation,
                    start_date=effective_date,
                )
                created_count += 1

            publish_payload = dict(step.payload or {})
            publish_payload["file_id"] = str(file_obj.id)
            if file_obj.document_id:
                publish_payload["document_id"] = str(file_obj.document_id)
            publish_payload["effective_date"] = effective_date.isoformat()
            publish_payload["affiliations_created"] = created_count
            publish_payload["affiliations_unchanged"] = skipped_count
            publish_payload["affiliations_skipped_incumbent"] = skipped_count
            publish_payload["affiliations_ended"] = ended_count
            step.payload = publish_payload

    @staticmethod
    def _desired_affiliations_from_entries(entries: list[dict]) -> list[DesiredAffiliation]:
        desired: list[DesiredAffiliation] = []
        for entry in entries:
            person_id = entry["person_id"]
            for position in entry.get("positions") or []:
                desired.append(
                    DesiredAffiliation(
                        person_id=str(person_id),
                        portfolio_id=str(position["portfolio_id"]),
                        title=_normalize_affiliation_text(position.get("title")),
                        conjunction=_normalize_affiliation_text(
                            position.get("conjunction"),
                        ),
                        type=normalize_category(position.get("category")),
                        specialisation=_normalize_affiliation_text(
                            position.get("specialisation"),
                        ),
                    )
                )
        return desired

    @staticmethod
    def _active_affiliations_as_of(as_of: date):
        return MinisterialAffiliation.objects.filter(
            start_date__lte=as_of,
        ).filter(Q(end_date__isnull=True) | Q(end_date__gte=as_of))
