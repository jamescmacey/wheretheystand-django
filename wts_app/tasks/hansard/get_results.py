"""Celery task for fetching Hansard search results."""
from celery import shared_task

from django.db import transaction
import json
import math
from pathlib import Path
from django.utils import timezone
from wts_app.models import HansardSearchResult, Person

from playwright.sync_api import sync_playwright


import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

PAGE_URL = (
    "https://hansard.parliament.nz/hansard-debates/rhr"
    "?lang=en&Tab=Search&Page=1&Dir=Desc&SubType=Vote&From=2023-10-14"
)
SEARCH_API_URL = "https://hansard.parliament.nz/api/data/search"
SEARCH_PAGE_SIZE = 100

search_state = {"page": 1}


def is_search_post(response) -> bool:
    return (
        response.url.rstrip("/") == SEARCH_API_URL.rstrip("/")
        and response.request.method == "POST"
    )


def modify_search_request(route, request) -> None:
    if request.method != "POST":
        route.continue_()
        return

    payload = request.post_data_json
    if payload is None:
        payload = json.loads(request.post_data or "{}")

    payload["pageSize"] = SEARCH_PAGE_SIZE
    payload["page"] = search_state["page"]

    route.continue_(
        post_data=json.dumps(payload),
        headers={**request.headers, "content-type": "application/json"},
    )


def fetch_search_page(page, *, navigate: bool = False) -> dict:
    with page.expect_response(is_search_post) as response_info:
        if navigate:
            page.goto(PAGE_URL, wait_until="networkidle", timeout=120_000)
        else:
            page.locator('[data-test-ref="btn-next-page"]').click()

    return response_info.value.json()

def save_results(results: list[dict]) -> None:
    if not results:
        return

    with transaction.atomic():
        logger.info("Writing %s results to database", len(results))
        for result in results:
            member_id = result.get("memberId")
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

            HansardSearchResult.objects.update_or_create(
                result_id=result["id"],
                defaults={
                    "result_title": result["title"],
                    "result_subtitle": result["subtitle"],
                    "result_volume_number": result["volumeNumber"],
                    "result_sitting_date": result["sittingDate"][:10],
                    "result_document_type": result["documentType"],
                    "result_document_subtype": result["documentSubtype"],
                    "result_progress": result["progress"],
                    "result_member_id": result["memberId"],
                    "result_member_name": result["memberName"],
                    "result_sort_index": result["sortIndex"],
                    "result_portfolio": result["portfolio"],
                    "result_parliament_number": result["parliamentNumber"],
                    "result_parent_result_id": result["parentId"],
                    "retrieved_at": timezone.now(),
                    "matched_person": matched_person,
                },
            )

@shared_task(name="wts_app.hansard.get_results", queue="hansard")
def get_results() -> None:
    result_batches: list[list[dict]] = []

    with sync_playwright() as playwright:
        logger.info("Launching browser")
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        page.route("**/api/data/search", modify_search_request)

        search_state["page"] = 1
        logger.info("Fetching first page")
        first_page = fetch_search_page(page, navigate=True)
        result_batches.append(first_page["value"])
        total_count = first_page["@odata.count"]
        total_pages = math.ceil(total_count / SEARCH_PAGE_SIZE)

        logger.info("Fetching %s results from %s pages", total_count, total_pages)

        for page_num in range(2, total_pages + 1):
            logger.info("Fetching page %s of %s", page_num, total_pages)
            search_state["page"] = page_num
            page_data = fetch_search_page(page)
            result_batches.append(page_data["value"])

        browser.close()

    for batch in result_batches:
        save_results(batch)

    logger.info("Complete.")


