from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from wts_app.models import AutoUpdate, Bill
from django.contrib.contenttypes.models import ContentType
from wts_app.staff_mail import send_daily_email_summary

@shared_task
def clean_up_auto_updates():
    auto_updates = AutoUpdate.objects.filter(updated_at__lt=timezone.now() - timedelta(days=7)).delete()

@shared_task
def daily_email_summary():
    auto_updates = AutoUpdate.objects.filter(updated_at__gte=timezone.now() - timedelta(days=1))

    """
    Generate a summary email of the auto updates that have occurred in the last day:
    - Total number of auto updates
    - Number of auto updates that were successful, broken down by model
    - Number of auto updates that failed, broken down by model
    """

    summary = {
        "total": auto_updates.count(),
        "successful": {
            "bills": auto_updates.filter(status="successful", updated_content_type=ContentType.objects.get_for_model(Bill)).count(),
        },
        "failed": {
            "bills": auto_updates.filter(status="failed", updated_content_type=ContentType.objects.get_for_model(Bill)).count(),
        },
    }

    send_daily_email_summary(summary)