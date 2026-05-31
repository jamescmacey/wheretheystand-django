"""Monitored source handler types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from wts_app.models import MonitoredSource, Workbook, WorkbookFile


@dataclass
class DetectedItem:
    external_id: str
    payload: dict
    source_url: str = ""


class MonitoredSourceHandler(Protocol):
    slug: str

    def poll(self, source: MonitoredSource) -> list[DetectedItem]: ...

    def fetch_document(self, source: MonitoredSource, item: DetectedItem) -> bytes: ...

    def bootstrap_workbook(
        self,
        source: MonitoredSource,
        item: DetectedItem,
        *,
        file_bytes: bytes,
        filename: str,
    ) -> tuple[Workbook, WorkbookFile]: ...
