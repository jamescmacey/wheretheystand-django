from celery import shared_task
from wts_app.models import HansardSearchResult, VoteStub, Bill
from django.db import transaction, models

@shared_task(name="wts_app.hansard.create_stubs", queue="celery")
def create_stubs():

    hansard_search_results = HansardSearchResult.objects.filter(result_document_subtype="Vote", result_subtitle__in=["First Reading", "Second Reading", "Third Reading"], vote_stubs__isnull=True)
    
    for search_result in hansard_search_results.iterator():
        with transaction.atomic():
            search_result.vote_stubs.all().delete()
            sitting_date = search_result.result_sitting_date
            
            # First get the name of the bill
            bill_name = "".join(search_result.result_title.split("Vote: Bills — ")).strip()
            bills = Bill.objects.filter(name__iexact=bill_name)

            if bills.count() == 0:
                continue

            match search_result.result_subtitle:
                case "First Reading":
                    bill_filters = bills.filter(
                        (models.Q(first_reading_date=sitting_date)) |
                        (models.Q(defeated_date=sitting_date, defeated_reading=1))
                    )
                    reading = 1
                case "Second Reading":
                    bill_filters = bills.filter(
                        (models.Q(second_reading_date=sitting_date)) |
                        (models.Q(defeated_date=sitting_date, defeated_reading=2))
                    )
                    reading = 2
                case "Third Reading":
                    bill_filters = bills.filter(
                        (models.Q(third_reading_date=sitting_date)) |
                        (models.Q(defeated_date=sitting_date, defeated_reading=3))
                    )
                    reading = 3

            if bill_filters.count() != 1:
                continue

            bill = bill_filters.first()

            # Check if a vote stub already exists for this reading and bill: if it does, only store the earliest sort index.
            existing_vote_stubs = VoteStub.objects.filter(reading=reading, bill=bill)
            if existing_vote_stubs.count() > 0:
                existing_sort_index_values = existing_vote_stubs.values_list('hansard_search_result__result_sort_index', flat=True)
                if search_result.result_sort_index > min(existing_sort_index_values):
                    continue
                else:
                    existing_vote_stubs.delete()

            VoteStub.objects.create(
                date=sitting_date,
                hansard_search_result=search_result,
                reading=reading,
                bill=bill,
            )

       

            