from celery import shared_task
from django.db import transaction
from django.utils import timezone
from wts_app.models import HansardDaily, HansardItem, HansardDebate, HansardSearchResult, Vote, Parliament
from .get_daily import get_daily
from .get_results import get_results
from datetime import timedelta

class UpdateMode(Enum):
    FULL = "weeky"
    DAILY = "daily"

@shared_task(name="wts_app.hansard.update", queue="hansard")
def update(mode: UpdateMode) -> None:
    today = timezone.now().date()

    # Determine the range to get results for
    if mode == UpdateMode.DAILY:
        from_date = today - timedelta(days=7)
    elif mode == UpdateMode.FULL:
        one_year_ago = today - timedelta(days=365)

        current_parliament_start_date = None
        try:
            current_parliament_start_date = Parliament.objects.get(end_date__isnull=True).start_date
        except Parliament.DoesNotExist:
            try:
                current_parliament_start_date = Parliament.objects.order_by("-end_date").first().start_date
            except:
                pass
        except:
            pass
        
        from_date = min(one_year_ago, current_parliament_start_date) if current_parliament_start_date else one_year_ago
    
    # Get search results
    get_results(from_date=from_date.strftime("%Y-%m-%d"))

    # Determine which dailies need to be updated

    # If this is a daily update we update:
    # - dailies for votes occurring in the last seven days
    # - dailies for votes where status of the Search Result for that vote differs from the status of the vote itself
    results_from_last_seven_days = HansardSearchResult.objects.filter(result_sitting_date__gte=today - timedelta(days=7), result_type="Vote")
    votes_from_last_seven_days = Vote.objects.filter(date__gte=today - timedelta(days=7))

    # Get the result_sitting_date values for results_from_last_seven_days
    result_sitting_dates = results_from_last_seven_days.values_list("result_sitting_date", flat=True)
    # Get the date values for votes_from_last_seven_days
    vote_dates = votes_from_last_seven_days.values_list("date", flat=True)

    # Get the unique dates
    dates_to_update = list(set(result_sitting_dates + vote_dates))
    

    if mode == UpdateMode.FULL:
        # If this is a full update we update:
        # - dailies where the vote status is not Final
        results_where_not_final = HansardSearchResult.objects.filter(result_progress__not="Final")
        votes_where_not_final = Vote.objects.filter(hansard_status__not="Final")

        # Get the result_sitting_date values for results_where_not_final
        result_sitting_dates = results_where_not_final.values_list("result_sitting_date", flat=True)
        # Get the date values for votes_where_not_final
        vote_dates = votes_where_not_final.values_list("date", flat=True)

        # Get the unique dates
        dates_to_update.extend(list(set(result_sitting_dates + vote_dates)))

    for date in dates_to_update:
        get_daily(date.strftime("%Y-%m-%d"))