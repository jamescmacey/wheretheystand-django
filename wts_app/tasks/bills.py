from celery import shared_task
import requests as req
from django.conf import settings
from wts_app.models import Bill, Person
import json
from django.db import transaction
from django.utils import timezone
from datetime import datetime

def _parse_date(date_string: str) -> datetime.date | None:
    if not date_string or date_string.strip() == '':
        return None
    try:
        return datetime.fromisoformat(date_string).date()
    except:
        return None

@shared_task
def update_bill(id = None, parliament_api_id = None):

    import logging
    logger = logging.getLogger(__name__)

    bill = None
    if id:
        bill = Bill.objects.get(id=id)
        parliament_api_id = bill.parliament_api_id
    elif parliament_api_id:
        try:
            bill = Bill.objects.get(parliament_api_id=parliament_api_id)
        except:
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
        bill.people_responsible.set([])

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
        except:
            bill.act_year = None
            bill.act_number = None

        if bill.act_year and (bill.act_year < 1840 or bill.act_year > timezone.now().year):
            bill.act_year = None
            bill.act_number = None

        # Unimplemented fields:
        # - ExtendedSittingsUsed
        # - UrgencyUsed
        # - FlagScrapedUnderV2
        # - FlagEnactedButMissingAssentNumber
        # - SelectCommitteeName
        # - SelectCommitteeStatus
        # - Status
        # - SubmissionsDueDate
        # - ReportBackDate
        # - WithdrawnDate
        # - DefeatedDate
        # - DefeatedReading
        # - LapsedDate
        # - Parliaments

        people_responsible = []
        for member in data.get("Members", []):
            sorted_name = member.get("SortedName", "").split(",")
            last_name = sorted_name[0].strip()
            first_name = sorted_name[1].strip()

            try:
                person = Person.objects.get(first_name=first_name, last_name=last_name)
            except:
                logger.warning(f"Person {sorted_name} is listed as a member responsible for bill {parliament_api_id} but no match was found in our database.")
                continue

            people_responsible.append(person)

        bill.save()

        bill.people_responsible.set(people_responsible)

        child_bills = []
        for child_bill in data.get("ChildBills", []):
            try:
                child_bill = Bill.objects.get(parliament_api_id=child_bill.get("ChildBillId"))
                child_bills.append(child_bill)
            except:
                logger.warning(f"Child bill {child_bill.get('ChildBillId')} is listed as a child bill for bill {parliament_api_id} but no match was found in our database.  This may resolve on future updates.")
                continue

        bill.child_bills.set(child_bills)


    logger.info(f"Updated bill {bill.id}")