from celery import shared_task
import requests as req
from django.conf import settings
from wts_app.models import Bill, Person
import json
from django.db import transaction
from django.utils import timezone
from datetime import datetime
import math

def _parse_date(date_string: str) -> datetime.date | None:
    if not date_string or date_string.strip() == '':
        return None
    try:
        dt = datetime.fromisoformat(date_string)
        if timezone.is_aware(dt):
            # Convert to current timezone and return .date()
            dt = timezone.localtime(dt)
        return dt.date()
 
    except (ValueError, TypeError):
        return None

def _update_bill(id = None, parliament_api_id = None):

    import logging
    logger = logging.getLogger(__name__)

    bill = None
    if id:
        bill = Bill.objects.get(id=id)
        parliament_api_id = bill.parliament_api_id
    elif parliament_api_id:
        try:
            bill = Bill.objects.get(parliament_api_id=parliament_api_id)
        except Bill.DoesNotExist:
            pass
    else:
        raise ValueError("Either id or parliament_api_id must be provided")

    url = f'https://bills.parliament.nz/api/data/Bill/{parliament_api_id}'
    response = req.get(url, headers={'User-Agent': settings.BOT_USER_AGENT})
    if response.status_code != 200:
        raise Exception(f"Failed to get bill with UUID {parliament_api_id}: {response.status_code}")
    
    try:
        data = response.json()
    except json.JSONDecodeError:
        raise Exception(f"Failed to parse JSON response for bill with UUID {parliament_api_id}.")

    # Verify that DocumentType is Bill
    document_type = data.get('DocumentType', 'not provided')
    if document_type != 'Bill':
        raise Exception(f"Expected a bill with UUID {parliament_api_id} but instead got an instance of {document_type}.")

    # Verify that the bill provided is the same bill as has been requested.
    if data.get('Id') != parliament_api_id:
        raise Exception(f"Expected the bill with UUID {parliament_api_id} but instead got a bill with UUID {data.get('Id')}.")

    # Start an atomic transaction to update the bill.
    with transaction.atomic():
        if not bill:
            bill = Bill(
                parliament_api_id=parliament_api_id,
                name=data.get('Title'),
                description=data.get('Description'),
                retrieved_at=timezone.now(),
                original_api_response=data,
            )
        else:
            bill.name = data.get('Title')
            bill.description = data.get('Description')
            bill.retrieved_at = timezone.now()
            bill.original_api_response = data
        
        bill.parliament_api_status = data.get("BillStatusCode")
        bill.ref = data.get("BillNumber")

        bill.bill_type = {
            "Government": "government",
            "Private": "private",
            "Local": "local",
            "Members": "members"
        }.get(data.get("BillTypeCode",None),None)

        bill.legislation_url = data.get("BillLegislationUrl")

        # Parse the ISO 8601 date strings into Django DateField objects.
        bill.introduction_date = _parse_date(data.get("IntroducedDate"))
        bill.first_reading_date = _parse_date(data.get("FirstReadingDate"))
        bill.second_reading_date = _parse_date(data.get("SecondReadingDate"))
        bill.whole_house_date = _parse_date(data.get("CommitteeOfWholeHouseDate"))
        bill.third_reading_date = _parse_date(data.get("ThirdReadingDate"))
        bill.royal_assent_date = _parse_date(data.get("RoyalAssentDate"))
        bill.last_activity_date = _parse_date(data.get("LastUpdatedDate"))

        bill.is_divided = len(data.get("ChildBills", [])) > 0

        bill.act_name = data.get("Act")
        try:
            bill.act_number = int(data.get("AssentNumber").split("/")[1])
            bill.act_year = int(data.get("AssentNumber").split("/")[0])
        except (AttributeError, IndexError, TypeError, ValueError):
            bill.act_year = None
            bill.act_number = None

        if bill.act_year and (bill.act_year < 1840 or bill.act_year > timezone.now().year):
            bill.act_year = None
            bill.act_number = None

        # Unimplemented fields:
        # - WithdrawnDate
        # - LapsedDate
        # - Parliaments

        urgency_used = False
        extended_sittings_used = False
        bill.defeated_reading = None
        bill.defeated_date = None
        for stage in data.get("Stages", []):
            if stage.get("TypeCode") == "Urgency":
                urgency_used = True
            elif stage.get("TypeCode") == "Extended":
                extended_sittings_used = True
            
            if stage.get("StageCode") in ["First Reading", "Second Reading", "Third Reading"]:
                if stage.get("OutcomeCode") == "NotAgreed":
                    bill.defeated_reading = {"First Reading": 1, "Second Reading": 2, "Third Reading": 3}[stage.get("StageCode")]
                    bill.defeated_date = _parse_date(stage.get("StageDate"))
                    
        bill.urgency_used = urgency_used
        bill.extended_sittings_used = extended_sittings_used
        bill.flag_scraped_under_v2 = True

        # Determine status
        if data.get("BillStatusCode") == "Active":
            bill.status = "in_progress"

        if bill.third_reading_date:
            bill.status = "passed"

        if bill.royal_assent_date:
            bill.status = "enacted"

        if bill.defeated_date:
            bill.status = "defeated"

        if bill.withdrawn_date:
            bill.status = "withdrawn"
    
        if bill.lapsed_date:
            bill.status = "lapsed"

        if data.get("BillStatusCode") == "Terminated":
            match data.get("TerminationReasonName"):
                case "Withdrawn":
                    bill.status = "withdrawn"
                case "Divided":
                    bill.status = "divided"
                case "Lapsed":
                    bill.status = "lapsed"
                case "Assented":
                    bill.status = "enacted"
                case "Discharged":
                    bill.status = "discharged"
            if bill.status == "unknown":
                bill.status = "unknown_not_current"

        if data.get("SelectCommitteeInfo"):
            bill.report_back_date = _parse_date(data.get("SelectCommitteeInfo").get("ReportDueDate"))
            bill.submissions_due_date = _parse_date(data.get("SelectCommitteeInfo").get("SubmissionDueDate")) if data.get("SelectCommitteeInfo").get("SubmissionCalled") else None
            if len(data.get("SelectCommitteeInfo").get("Committees", [])) > 0:
                committee = data.get("SelectCommitteeInfo").get("Committees")[0]
                bill.select_committee_name = committee.get("Name")
                if committee.get("StartDate"):
                    bill.select_committee_status = "Currently before committee"
                if committee.get("EndDate"):
                    bill.select_committee_status = "Previously before committee"

   
        people_responsible = []
        for member in data.get("Members", []):
            member_id = member.get("MemberId")
            sorted_name = member.get("SortedName", "").split(",")
            if len(sorted_name) < 2:
                logger.warning(
                    f"Person {member.get('SortedName')} is listed as a member responsible for bill "
                    f"{parliament_api_id} but SortedName could not be parsed."
                )
                continue
            last_name = sorted_name[0].strip()
            first_name = sorted_name[1].strip()

            if member_id:
                try:
                    people_responsible.append(Person.objects.get(parliament_api_id=member_id))
                    continue
                except Person.DoesNotExist:
                    pass

            try:
                person = Person.objects.get(first_name=first_name, last_name=last_name)
            except Person.DoesNotExist:
                logger.warning(f"Person {sorted_name} is listed as a member responsible for bill {parliament_api_id} but no match was found in our database.")
                continue

            people_responsible.append(person)

        bill.save()

        bill.people_responsible.set(people_responsible)

        child_bills = []
        for child_bill_data in data.get("ChildBills", []):
            child_bill_id = child_bill_data.get("ChildBillId")
            try:
                child_bills.append(Bill.objects.get(parliament_api_id=child_bill_id))
            except Bill.DoesNotExist:
                logger.warning(f"Child bill {child_bill_id} is listed as a child bill for bill {parliament_api_id} but no match was found in our database.  This may resolve on future updates.")
                continue

        bill.child_bills.set(child_bills)

    logger.info(f"Updated bill {bill.id}")
    return bill


@shared_task
def update_bill(id = None, parliament_api_id = None):
    from wts_app.models import AutoUpdate
    from django.contrib.contenttypes.models import ContentType
    import logging
    logger = logging.getLogger(__name__)

    auto_update = AutoUpdate.objects.create(
        status="started",
        payload={
            "id":id,
            "parliament_api_id":parliament_api_id,
        },
    )

    try:
        bill = _update_bill(id=id, parliament_api_id=parliament_api_id)
        auto_update.status = "successful"
        auto_update.updated_object = bill
        auto_update.save()

    except Exception as e:
        logger.error(f"Failed to update bill {id} or {parliament_api_id}: {e}")
        auto_update.status = "failed"
        auto_update.error_message = str(e)
        auto_update.save()


def _build_search_payload(page: int, date: str, results_per_page: int) -> dict:
    return {
        "id":None,
        "documentPreset":1,
        "keyword":None,
        "selectCommittee":None,
        "status":[],
        "documentTypes":[],
        "documentSubtypes":[],
        "beforeCommittee":None,
        "billStages":[],
        "billTab":"All",
        "billId":None,
        "includeBillStages":True,
        "subject":None,
        "person":None,
        "parliament":None,
        "dateFrom":date,
        "dateTo":None,
        "datePeriod":None,
        "restrictedFrom":date,
        "restrictedTo":None,
        "terminatedReason":None,
        "prettyTerminatedReason":None,
        "terminatedReasons":[],
        "column":17,"direction":1,"pageSize":results_per_page,"page":page}

@shared_task
def update(from_date: datetime.date):
    from_date_str = f"{from_date.strftime("%Y-%m-%d")}T00:00:00"
    ### First send a post request to https://bills.parliament.nz/api/data/search

    page = 1
    total_results = None
    results_per_page = 100
    results = []
    while total_results is None or page <= math.ceil(total_results / results_per_page):
        search_payload = _build_search_payload(page, from_date_str, results_per_page)
        request = req.post("https://bills.parliament.nz/api/data/search", json=search_payload, headers={'User-Agent': settings.BOT_USER_AGENT})
        if request.status_code != 200:
            raise Exception(f"Failed to get search results: {request.status_code}")
        data = request.json()
        total_results = data.get("totalResults", 0)
        results.extend(data.get("results", []))
        page += 1

    ids = [result.get("id") for result in results if result.get("id")]

    # Make a list of all the ids that are not already in our database
    ids_not_in_database = [
        parliament_api_id for parliament_api_id in ids
        if not Bill.objects.filter(parliament_api_id=parliament_api_id).exists()
    ]

    # Also refresh in-progress and passed bills regardless of search results
    existing_active_ids = Bill.objects.filter(
        status__in=["in_progress", "passed"]
    ).values_list("parliament_api_id", flat=True)

    ids_to_update = list(set(ids_not_in_database) | set(existing_active_ids))

    for parliament_api_id in ids_to_update:
        update_bill.delay(parliament_api_id=parliament_api_id)