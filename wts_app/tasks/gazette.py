from celery import shared_task
from django.conf import settings
from bs4 import BeautifulSoup
import urllib.request
from django.utils import timezone
from datetime import timedelta

from wts_app.models import MonitoredSource


def _create_gazette_notice_legacy(number: str):
    """Legacy path: create GazetteNotice (triggers direct File download on save)."""
    from wts_app.models import GazetteNotice

    if len(number) != 11 or number[4] != "-":
        return
    GazetteNotice.objects.get_or_create(number=number)


@shared_task
def update_gazette_notices():
    source = MonitoredSource.objects.filter(
        slug="gazette_electoral_act", is_active=True
    ).first()
    if source:
        from wts_app.tasks.monitored_sources import poll_monitored_sources

        poll_monitored_sources()
        return

    search_url = (
        f"https://gazette.govt.nz/home/search?keyword=&year=&pageNumber="
        f"&noticeNumber=&dateStart={timezone.now().date() - timedelta(days=7)}"
        f"&dateEnd=&type=&act=&tags=Electoral%20Act"
    )
    req = urllib.request.Request(search_url)
    req.add_header("User-Agent", settings.BOT_USER_AGENT)
    with urllib.request.urlopen(req, timeout=30) as response:
        content = response.read()
        soup = BeautifulSoup(content, "html.parser")

    table = soup.find("table", class_="w-full overflow-x-scroll")
    if not table:
        no_results = soup.find("span", class_="no-results")
        if no_results:
            return
        pdf_link = soup.find("a", class_="pdf relative mt-8 w-full")
        if pdf_link:
            notice_number = pdf_link.get("href", None)
            if notice_number:
                _create_gazette_notice_legacy(notice_number.split("/")[-2])
        return

    for row in table.find_all("tr"):
        data_cells = row.find_all("td")
        if len(data_cells) > 1:
            link = data_cells[1].find("a")
            if link:
                href = link.get("href", None)
                if href:
                    _create_gazette_notice_legacy(href.split("/")[-1])
