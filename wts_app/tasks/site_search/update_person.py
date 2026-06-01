from celery import shared_task
from wts_app.models import Person, SiteSearch
from wts_app.views.people import PersonSimpleSerializer
from django.db import transaction
import json

@shared_task(name="wts_app.site_search.update_person_site_search")
def update_person(person_id: str):
    try:
        person = Person.objects.get(id=person_id)
    except Person.DoesNotExist:
        return

    with transaction.atomic():
        serialized_data = json.loads(
            json.dumps(PersonSimpleSerializer(person).data, default=str)
        )
        site_search = person.site_search
        if not site_search:
            site_search = SiteSearch.objects.create(
                type="person",
                name=person.display_name,
                description=person.cached_description,
                data=serialized_data,
            )
        else:
            site_search.name = person.display_name
            site_search.description = person.cached_description
            site_search.data = serialized_data
            site_search.save()
        person.site_search = site_search
        person.save(update_site_search=False)