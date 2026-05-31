"""Helpers for workbook files on private GCS staging storage."""

from __future__ import annotations

import mimetypes
import os

from django.conf import settings

from wts_app.models import WorkbookFile


def workbook_file_gcs_uri(workbook_file: WorkbookFile) -> str:
    """Return a gs:// URI for the staged workbook file."""
    if not workbook_file.file:
        raise ValueError("Workbook file has no storage path.")
    storage = workbook_file.file.storage
    bucket = getattr(storage, "bucket_name", None) or getattr(
        settings,
        "GCP_PRIVATE_FILES_BUCKET_NAME",
        None,
    )
    if not bucket:
        raise ValueError("GCP private files bucket is not configured.")
    blob_name = workbook_file.file.name.lstrip("/")
    return f"gs://{bucket}/{blob_name}"


def workbook_file_mime_type(workbook_file: WorkbookFile) -> str:
    name = workbook_file.file.name if workbook_file.file else ""
    display = os.path.basename(name.split("?")[0])
    guessed = mimetypes.guess_type(display)[0]
    return guessed or "application/octet-stream"


def workbook_file_gemini_display_name(workbook_file: WorkbookFile) -> str:
    name = workbook_file.file.name if workbook_file.file else "workbook-file"
    return os.path.basename(name.split("?")[0])
