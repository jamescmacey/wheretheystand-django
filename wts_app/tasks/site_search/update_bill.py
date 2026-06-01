from celery import shared_task
from wts_app.models import Bill, SiteSearch
from wts_app.views.bills import BillSimpleSerializer
from django.db import transaction
import json

@shared_task(name="wts_app.site_search.update_bill_site_search")
def update_bill(bill_id: str):
    try:
        bill = Bill.objects.get(id=bill_id)
    except Bill.DoesNotExist:
        return

    with transaction.atomic():
        serialized_data = json.loads(
            json.dumps(BillSimpleSerializer(bill).data, default=str)
        )
        site_search = bill.site_search
        if not site_search:
            site_search = SiteSearch.objects.create(
                type="bill",
                name=bill.name,
                description=bill.description,
                data=serialized_data,
            )
        else:
            site_search.name = bill.name
            site_search.description = bill.description
            site_search.data = serialized_data
            site_search.save()
        bill.site_search = site_search
        bill.save(update_site_search=False)