from celery import shared_task
from wts_app.models import Party, SiteSearch
from wts_app.views.parties import PartyListSerializer
from django.db import transaction
import json

@shared_task(name="wts_app.site_search.update_party_site_search")
def update_party(party_id: str):
    try:
        party = Party.objects.get(id=party_id)
    except Party.DoesNotExist:
        return

    with transaction.atomic():
        serialized_data = json.loads(
            json.dumps(PartyListSerializer(party).data, default=str)
        )
        site_search = party.site_search
        if not site_search:
            site_search = SiteSearch.objects.create(
                type="party",
                name=party.display_name,
                description=party.legal_name,
                data=serialized_data,
            )
        else:
            site_search.name = party.display_name
            site_search.description = party.legal_name
            site_search.data = serialized_data
            site_search.save()
        party.site_search = site_search
        party.save(update_site_search=False)