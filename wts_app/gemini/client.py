"""Client wrapper for Gemini batch processing."""

from __future__ import annotations

from typing import Iterable, Optional

from django.conf import settings

from google import genai
from google.genai import types
from google.oauth2 import service_account


class GeminiClient:
    """Thin wrapper around the Google GenAI client for AI Studio."""

    def __init__(self, api_key: Optional[str] = None):
        api_key = api_key or getattr(settings, "GEMINI_API_KEY", None)
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")
        self.client = genai.Client(api_key=api_key)

    def upload_file(
        self,
        file_obj,
        *,
        mime_type: str,
        display_name: Optional[str] = None,
    ) -> types.File:
        config = {"mime_type": mime_type}
        if display_name:
            config["display_name"] = display_name
        return self.client.files.upload(file=file_obj, config=config)

    def register_files(
        self,
        *,
        uris: Iterable[str],
    ) -> list[types.File]:
        """
        Registers files with the Gemini Files API and returns a list of registered File objects.

        Each URI provided must be a gs:// URI for a file in the bucket specified by GCP_PRIVATE_FILES_BUCKET.
        """
   
        credentials = service_account.Credentials.from_service_account_info(
            settings.GCP_PRIVATE_FILES_CREDENTIALS,
            scopes=[
                'https://www.googleapis.com/auth/devstorage.read_only',
                'https://www.googleapis.com/auth/cloud-platform'
            ]
        )

        response = self.client.files.register_files(uris=uris, auth=credentials)

        files = getattr(response, "files", None)
        if files is not None:
            return list(files)
        else:
            raise ValueError("Failed to extract registered files from the response.")

    def create_batch_job(
        self,
        *,
        model: str,
        requests: Iterable[types.InlinedRequest],
        display_name: Optional[str] = None,
    ) -> types.BatchJob:
        config = {"display_name": display_name} if display_name else None
        return self.client.batches.create(model=model, src=list(requests), config=config)

    def get_batch_job(self, *, name: str) -> types.BatchJob:
        return self.client.batches.get(name=name)

    def download_file(self, *, file_name: str) -> bytes:
        return self.client.files.download(file=file_name)
