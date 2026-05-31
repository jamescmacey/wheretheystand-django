"""Celery task for fetching daily Hansard."""

from __future__ import annotations

import json
import logging
from datetime import date, timezone as dt_timezone
from urllib.parse import urlparse

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from playwright.sync_api import sync_playwright

from wts_app.models import (
    Bill,
    HansardBillAssocation,
    HansardDaily,
    HansardDebate,
    HansardItem,
    Person
)

logger = logging.getLogger(__name__)

HANSARD_BASE = "https://hansard.parliament.nz"


def _transcript_api_path(sitting_date: str) -> str:
    return f"/api/resources/transcript/{sitting_date}"


def _daily_api_path(sitting_date: str) -> str:
    return f"/api/data/daily/{sitting_date}"


def _transcript_style_api_path() -> str:
    return "/api/resources/transcript-style"


def _is_get_for_path(response, path: str) -> bool:
    return (
        response.request.method == "GET"
        and urlparse(response.url).path.rstrip("/") == path.rstrip("/")
    )


def _response_body(response) -> str | dict:
    content_type = (response.headers.get("content-type") or "").lower()
    if "json" in content_type:
        return response.json()
    return response.text()


def _normalize_resource_body(body: str | dict, *, keys: tuple[str, ...]) -> str:
    if isinstance(body, str):
        return body
    for key in keys:
        if key in body and body[key] is not None:
            value = body[key]
            return value if isinstance(value, str) else json.dumps(value)
    return json.dumps(body)


def _normalize_transcript(body: str | dict) -> str:
    return _normalize_resource_body(
        body, keys=("content", "html", "value", "transcript")
    )


def _normalize_transcript_style(body: str | dict) -> str:
    return _normalize_resource_body(body, keys=("content", "css", "style", "value"))


def fetch_daily_responses(page, url: str, sitting_date: str) -> tuple[str, dict, str]:
    transcript_path = _transcript_api_path(sitting_date)
    daily_path = _daily_api_path(sitting_date)
    style_path = _transcript_style_api_path()

    with page.expect_response(
        lambda response: _is_get_for_path(response, daily_path)
    ) as daily_info:
        with page.expect_response(
            lambda response: _is_get_for_path(response, transcript_path)
        ) as transcript_info:
            with page.expect_response(
                lambda response: _is_get_for_path(response, style_path)
            ) as style_info:
                page.goto(url, wait_until="networkidle", timeout=120_000)

    transcript_html = _normalize_transcript(_response_body(transcript_info.value))
    transcript_style = _normalize_transcript_style(_response_body(style_info.value))
    daily_body = _response_body(daily_info.value)
    if not isinstance(daily_body, dict):
        raise ValueError(f"Expected JSON daily payload for {sitting_date}")

    return transcript_html, daily_body, transcript_style


def _choice_value(value: str | None, choices: list[tuple[str, str]]) -> str | None:
    if not value:
        return None
    allowed = {choice[0] for choice in choices}
    return value if value in allowed else "__other__"

def _save_debate_items(debate: HansardDebate, debate_data: dict) -> None:
    for item_data in debate_data.get("hansardItems", []):

        start_time = parse_datetime(
            (item_data.get("startTime") or "").replace("Z", "+00:00")
        )
        if start_time:
            start_time = start_time.replace(tzinfo=dt_timezone.utc)  # <-- Use datetime.timezone.utc
        if start_time and start_time.year < 1900:
            start_time = None

        member_id = item_data.get("memberId")
        matched_person = None

        if member_id:
            try:
                matched_person = Person.objects.get(parliament_api_id=member_id)
            except Person.DoesNotExist:
                matched_person = None
            except Person.MultipleObjectsReturned:
                matched_person = None
                logger.warning(
                    f"Multiple people found for {member_id}, skipping"
                )

        HansardItem.objects.create(
            debate=debate,
            item_id=item_data.get("id"),
            item_type=_choice_value(
                item_data.get("type"),
                HansardItem.ITEM_TYPES,
            ),
            item_member_id=member_id,
            item_member_name=item_data.get("memberName"),
            item_electorate=item_data.get("electorate"),
            item_start_time=start_time,
            item_title=item_data.get("title"),
            item_subtitle=item_data.get("subtitle"),
            item_content=item_data.get("content"),
            matched_person=matched_person,
        )


def _save_debate_bill_associations(debate: HansardDebate, debate_data: dict) -> None:
    for assoc_data in debate_data.get("hansardDebateAssociationsBill", []):
        bill_id = assoc_data.get("billId")
        matched_bill = None

        if bill_id:
            try:
                matched_bill = Bill.objects.get(parliament_api_id=bill_id)
            except Bill.DoesNotExist:
                matched_bill = None
            except Bill.MultipleObjectsReturned:
                matched_bill = None
                logger.warning(
                    f"Multiple bills found for {bill_id}, skipping"
                )

        HansardBillAssocation.objects.create(
            debate=debate,
            assocation_id=assoc_data.get("id"),
            bill_id=bill_id,
            bill_title=assoc_data.get("title"),
            matched_bill=matched_bill,
        )


def _apply_daily_fields(daily: HansardDaily, daily_data: dict) -> None:
    daily.daily_id = daily_data.get("id")
    daily.daily_title = daily_data.get("title")
    daily.daily_subtitle = daily_data.get("subtitle")
    daily.daily_volume_number = daily_data.get("volumeNumber")
    daily.daily_parliament_number = daily_data.get("parliamentNumber")
    daily.daily_progress = _choice_value(
        daily_data.get("progress"), HansardDaily.DAILY_PROGRESS_TYPES
    )
    daily.daily_content = daily_data.get("content")
    daily.retrieved_at = timezone.now()


def _save_daily_files(
    daily: HansardDaily, sitting_date: str, transcript_html: str, transcript_style: str
) -> None:
    daily.transcript_file.save(
        f"{sitting_date}.html",
        ContentFile(transcript_html.encode("utf-8")),
        save=False,
    )
    daily.style_file.save(
        f"{sitting_date}.css",
        ContentFile(transcript_style.encode("utf-8")),
        save=False,
    )
    daily.save()


def save_daily_data(
    sitting_date: str,
    transcript_html: str,
    daily_data: dict,
    transcript_style: str,
) -> None:
    parsed_date = date.fromisoformat(sitting_date[:10])

    with transaction.atomic():
        try:
            daily = HansardDaily.objects.select_for_update().get(
                sitting_date=parsed_date
            )
        except HansardDaily.DoesNotExist:
            daily = HansardDaily(sitting_date=parsed_date)
            _apply_daily_fields(daily, daily_data)
            _save_daily_files(daily, sitting_date, transcript_html, transcript_style)
        else:
            _apply_daily_fields(daily, daily_data)
            _save_daily_files(daily, sitting_date, transcript_html, transcript_style)

        daily.debates.all().delete()

        for debate_data in daily_data.get("hansardDebates", []):
            debate = HansardDebate.objects.create(
                daily=daily,
                debate_id=debate_data.get("id"),
                debate_title=debate_data.get("title"),
                debate_subtitle=debate_data.get("subtitle"),
                debate_content=debate_data.get("content"),
            )
            _save_debate_items(debate, debate_data)
            _save_debate_bill_associations(debate, debate_data)

    logger.info("Saved daily Hansard for %s", sitting_date)


@shared_task(name="wts_app.hansard.get_daily", queue="hansard")
def get_daily(sitting_date: str) -> None:
    """Fetch daily Hansard transcript and structured daily data via Playwright."""
    logger.info("Fetching daily Hansard for %s", sitting_date)

    url = f"{HANSARD_BASE}/hansard-transcript/{sitting_date}?lang=en"
    transcript_html: str | None = None
    daily_data: dict | None = None
    transcript_style: str | None = None

    with sync_playwright() as playwright:
        logger.info("Launching browser")
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            transcript_html, daily_data, transcript_style = fetch_daily_responses(
                page, url, sitting_date
            )
        finally:
            browser.close()

    if not transcript_html or not transcript_style or daily_data is None:
        raise ValueError(
            f"Did not receive transcript, transcript-style, and daily API "
            f"responses for {sitting_date}"
        )

    save_daily_data(sitting_date, transcript_html, daily_data, transcript_style)
    logger.info("Complete.")
