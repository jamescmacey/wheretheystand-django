"""Person profile picture workbook pipeline (site user photos)."""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from wts_app.ingestion.copyright_metadata import merge_file_metadata, resolve_file_metadata_ids
from wts_app.ingestion.promote import promote_workbook_file
from wts_app.ingestion.schemas import validate_payload
from wts_app.ingestion.staging_files import workbook_file_mime_type
from wts_app.models import Person, WorkbookStep
from wts_app.models.workbook_pipeline import WorkbookStep as WorkbookStepModel

from .base import StepDefinition


class UserProfilePicturesRecipe:
    key = "user_profile_pictures"
    batch_per_file = True

    def steps(self) -> list[StepDefinition]:
        return [
            StepDefinition("upload", 0, requires_review=False, commit_writes_production=False),
            StepDefinition("link_entities", 1, requires_review=True, commit_writes_production=False),
            StepDefinition(
                "publish_profile_picture",
                2,
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
            if merged.get("person_id") == "":
                merged["person_id"] = None
            validate_payload(recipe_key, "link_entities", merged)
        return merged

    def can_start(self, step: WorkbookStep) -> None:
        return

    def commit_step(self, step: WorkbookStep, *, actor) -> None:
        if step.step_key == "upload":
            return
        if step.step_key == "link_entities":
            merged = self.validate_draft(step, step.payload or {})
            if not merged.get("person_id"):
                raise ValueError("person_id is required.")
            if not Person.objects.filter(pk=merged["person_id"]).exists():
                raise ValueError("person_id does not exist.")
            step.payload = merged
            return
        if step.step_key == "publish_profile_picture":
            self._commit_publish(step)
            return

    def on_step_committed(self, step: WorkbookStep) -> None:
        return

    def ui_schema(self, step_key: str) -> dict:
        schemas = {
            "upload": {"type": "upload", "title": "Upload"},
            "link_entities": {
                "type": "profile_picture_link",
                "title": "Link person and source",
                "fields": [
                    {"name": "person_id", "type": "person_picker"},
                    {"name": "original_url", "type": "url"},
                    {"name": "attribution_text", "type": "text"},
                    {"name": "file_metadata", "type": "copyright_metadata"},
                ],
            },
            "publish_profile_picture": {
                "type": "profile_picture_publish",
                "title": "Publish profile picture",
                "note": "Copies the image to public storage and sets the person's photo.",
            },
        }
        return schemas.get(step_key, {"type": "generic", "title": step_key})

    def build_gemini_prompt(self, step: WorkbookStep) -> str:
        return ""

    def apply_gemini_response(self, step: WorkbookStep, raw: dict) -> None:
        return

    def rewind_to_step_key(self, rejected_step: WorkbookStep) -> str | None:
        if rejected_step.step_key == "publish_profile_picture":
            return "link_entities"
        if rejected_step.step_key == "link_entities":
            return "upload"
        return None

    def _get_step(self, step: WorkbookStep, step_key: str) -> WorkbookStep:
        qs = WorkbookStep.objects.filter(
            workbook=step.workbook,
            step_key=step_key,
        )
        if step.workbook_file_id:
            qs = qs.filter(workbook_file_id=step.workbook_file_id)
        return qs.get()

    def _file_metadata_for_publish(self, step: WorkbookStep, link_payload: dict) -> dict:
        link_meta = (link_payload or {}).get("file_metadata") or {}
        publish_meta = (step.payload or {}).get("file_metadata") or {}
        workbook_meta = step.workbook.batch_defaults or {}
        merged = merge_file_metadata(workbook_meta, link_meta, publish_meta)
        return resolve_file_metadata_ids(merged)

    def _commit_publish(self, step: WorkbookStep) -> None:
        workbook_file = step.workbook_file
        if workbook_file is None:
            raise ValueError("publish_profile_picture requires a workbook file.")

        link = self._get_step(step, "link_entities")
        if link.status != WorkbookStepModel.Status.COMMITTED:
            raise ValueError("link_entities must be committed before publishing.")
        link_payload = link.payload or {}
        person = Person.objects.get(pk=link_payload["person_id"])

        file_metadata = self._file_metadata_for_publish(step, link_payload)
        original_url = _strip(link_payload.get("original_url"))
        if original_url:
            file_metadata["source_url"] = original_url
        elif file_metadata.get("source_url"):
            pass
        else:
            file_metadata.setdefault("source_url", "")

        attribution = _strip(link_payload.get("attribution_text"))
        file_metadata["file_name"] = f"{person.display_name}'s photo"
        file_metadata["file_description"] = attribution or ""
        file_metadata["file_type"] = workbook_file_mime_type(workbook_file)
        file_metadata.setdefault("published_date", timezone.now().date().isoformat())

        file_obj = promote_workbook_file(
            workbook_file,
            file_metadata=file_metadata,
        )

        with transaction.atomic():
            person.photo = file_obj
            person.save(update_fields=["photo", "updated_at"])

            publish_payload = dict(step.payload or {})
            publish_payload["file_id"] = str(file_obj.id)
            publish_payload["person_id"] = str(person.id)
            step.payload = publish_payload
            ct = ContentType.objects.get_for_model(Person)
            step.production_content_type = ct
            step.production_object_id = str(person.id)


def _strip(value) -> str:
    return str(value or "").strip()
