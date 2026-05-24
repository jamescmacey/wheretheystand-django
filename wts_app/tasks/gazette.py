from celery import shared_task
from django.conf import settings
from bs4 import BeautifulSoup
import urllib.request
from django.utils import timezone
from datetime import timedelta

def _create_gazette_notice(number: str):
    from wts_app.models import GazetteNotice
    if len(number) != 11 or number[4] != '-':
        return
    GazetteNotice.objects.get_or_create(number=number)

# This task gets any Gazette notices that have been published under the Electoral Act in the last seven days and, if necessary, saves them.
@shared_task
def update_gazette_notices():
    search_url = f"https://gazette.govt.nz/home/search?keyword=&year=&pageNumber=&noticeNumber=&dateStart={timezone.now().date()-timedelta(days=7)}&dateEnd=&type=&act=&tags=Electoral%20Act"
    print(search_url)
    req = urllib.request.Request(search_url)
    req.add_header('User-Agent', settings.BOT_USER_AGENT)
    with urllib.request.urlopen(req, timeout=30) as response:
        content = response.read()
        soup = BeautifulSoup(content, 'html.parser')

    # Get the table containing the notices
    table = soup.find('table', class_='w-full overflow-x-scroll')

    if not table:
        no_results = soup.find('span', class_='no-results')
        if no_results:
            return

    # If there is no table nor a page that says no results found, we have been redirected to a single result
    if not table:
        pdf_link = soup.find('a', class_='pdf relative mt-8 w-full')
        if pdf_link:
            notice_number = pdf_link.get("href", None)
            if notice_number:
                _create_gazette_notice(notice_number.split('/')[-2])
            else:
                return
        else:
            return

    # Get the rows in the table
    rows = table.find_all('tr')
    for row in rows:
        data_cells = row.find_all('td')
        if len(data_cells) > 1:
            data_cell = data_cells[1]
            link = data_cell.find('a').get('href', None)
            if link:
                notice_number = link.split('/')[-1]
                _create_gazette_notice(notice_number)
            else:
                continue
        else:
            continue