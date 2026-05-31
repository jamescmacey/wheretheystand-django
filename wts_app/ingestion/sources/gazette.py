"""Gazette Electoral Act monitored source handler."""

from __future__ import annotations

import urllib.error
import urllib.request
from datetime import timedelta

from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import timezone

from wts_app.models import MonitoredSource, GazetteNotice

from .base import DetectedItem


class GazetteElectoralActHandler:
    slug = "gazette_electoral_act"

    def poll(self, source: MonitoredSource) -> list[DetectedItem]:
        days = source.config.get("poll_days", 7)
        search_url = (
            "https://gazette.govt.nz/home/search?keyword=&year=&pageNumber="
            f"&noticeNumber=&dateStart={timezone.now().date() - timedelta(days=days)}"
            "&dateEnd=&type=&act=&tags=Electoral%20Act"
        )
        req = urllib.request.Request(search_url)
        req.add_header("User-Agent", settings.BOT_USER_AGENT)
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read()
        soup = BeautifulSoup(content, "html.parser")
        items: list[DetectedItem] = []
        table = soup.find("table", class_="w-full overflow-x-scroll")
        if not table:
            pdf_link = soup.find("a", class_="pdf relative mt-8 w-full")
            if pdf_link:
                href = pdf_link.get("href", "")
                number = href.split("/")[-2] if href else ""
                if len(number) == 11 and number[4] == "-":
                    items.append(
                        DetectedItem(
                            external_id=number,
                            payload={"notice_number": number},
                            source_url=f"https://gazette.govt.nz/notice/id/{number}",
                        )
                    )
            return items
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) > 1:
                link = cells[1].find("a")
                if link:
                    href = link.get("href", "")
                    number = href.split("/")[-1]
                    if len(number) == 11 and number[4] == "-":
                        items.append(
                            DetectedItem(
                                external_id=number,
                                payload={"notice_number": number},
                                source_url=f"https://gazette.govt.nz/notice/id/{number}",
                            )
                        )
        return items

    def process_event(self, source: MonitoredSource, item: DetectedItem):
        GazetteNotice.objects.get_or_create(number=item.external_id)

        

