from celery import shared_task

from wts_app.models import Feedback
from wts_app.staff_mail import send_feedback_submitted_staff_mail


@shared_task(name="wts_app.feedback.notify_staff")
def notify_staff_feedback_submitted(feedback_id: str, admin_url: str) -> None:
    feedback = Feedback.objects.get(pk=feedback_id)
    send_feedback_submitted_staff_mail(feedback, admin_url=admin_url)
