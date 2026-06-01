from celery import shared_task
from wts_app.models import Electorate, SiteSearch
from wts_app.views.electorates import ElectorateSerializer
from django.db import transaction
import json

@shared_task(name="wts_app.site_search.update_electorate_site_search")
def update_electorate(electorate_id: str):
    try:
        electorate = Electorate.objects.get(id=electorate_id)
    except Electorate.DoesNotExist:
        return

    with transaction.atomic():
        serialized_data = json.loads(
            json.dumps(ElectorateSerializer(electorate).data, default=str)
        )
        site_search = electorate.site_search
        if not site_search:
            site_search = SiteSearch.objects.create(
                type="electorate",
                name=electorate.name,
                description=electorate.electorate_type,
                data=serialized_data,
            )
        else:
            site_search.name = electorate.name
            site_search.description = electorate.electorate_type
            site_search.data = serialized_data
            site_search.save()
        electorate.site_search = site_search
        electorate.save(update_site_search=False)