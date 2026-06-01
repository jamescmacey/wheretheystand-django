from celery import shared_task, current_app
from wts_app.models import Person, Party, Electorate, Bill

@shared_task(name="wts_app.site_search.seed_site_search")
def seed(full_reindex=False):
    for person in (Person.objects.all() if full_reindex else Person.objects.filter(site_search__isnull=True)):
        current_app.send_task("wts_app.site_search.update_person_site_search", kwargs={"person_id": person.id})
    for party in (Party.objects.all() if full_reindex else Party.objects.filter(site_search__isnull=True)):
        current_app.send_task("wts_app.site_search.update_party_site_search", kwargs={"party_id": party.id})
    for electorate in (Electorate.objects.all() if full_reindex else Electorate.objects.filter(site_search__isnull=True)):
        current_app.send_task("wts_app.site_search.update_electorate_site_search", kwargs={"electorate_id": electorate.id})
    for bill in (Bill.objects.all() if full_reindex else Bill.objects.filter(site_search__isnull=True)):
        current_app.send_task("wts_app.site_search.update_bill_site_search", kwargs={"bill_id": bill.id})