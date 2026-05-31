"""Promote WorkbookFile from private GCS to production R2 File."""

from __future__ import annotations

import mimetypes
import os
from datetime import date

from django.core.files.base import ContentFile
from django.utils import timezone

from wts_app.models import File, WorkbookFile
from wts_app.models.documents import Category, Document


def _parse_published_date(value) -> date:
    if value is None:
        return timezone.now().date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def promote_workbook_file(
    workbook_file: WorkbookFile,
    *,
    file_metadata: dict | None = None,
) -> File:
    """Copy staged workbook file to documents storage and return File row."""
    if not workbook_file.file:
        raise ValueError("Workbook file has no uploaded content.")

    original_name = os.path.basename(workbook_file.file.name)
    mime_type = (
        mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    )

    with workbook_file.file.open("rb") as handle:
        content = handle.read()

    meta = file_metadata or {}
    display_file_name = meta.get("file_name") or original_name
    if "file_description" in meta:
        file_description = meta["file_description"]
    else:
        file_description = f"Workbook upload: {original_name}"

    file_type = meta.get("file_type")
    if not file_type:
        file_type = mime_type.split("/")[-1] if "/" in mime_type else mime_type

    document = None
    document_name = meta.get("document_name")
    if document_name:
        document = Document.objects.create(
            name=document_name,
            description=meta.get("document_description") or "",
        )
        category_name = meta.get("document_category_name")
        if category_name:
            category, _ = Category.objects.get_or_create(
                name=category_name,
                defaults={"description": category_name},
            )
            document.categories.add(category)

    file_obj = File(
        document=document,
        file_name=display_file_name,
        file_description=file_description,
        original_link_alive=False,
        source_url=meta.get("source_url") or "",
        file_type=file_type,
        published_date=_parse_published_date(meta.get("published_date")),
    )
    if meta.get("licence_id"):
        file_obj.licence_id = meta["licence_id"]
    if meta.get("copyright_owner_id"):
        file_obj.copyright_owner_id = meta["copyright_owner_id"]
    if meta.get("licence_grantor_id"):
        file_obj.licence_grantor_id = meta["licence_grantor_id"]
    file_obj._file_content_for_hash = content
    file_obj.file.save(original_name, ContentFile(content), save=False)
    file_obj.save()
    return file_obj
