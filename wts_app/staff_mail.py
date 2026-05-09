"""
Email helpers for notifying Django staff users.

HTML layout is shared via templates/emails/staff/base.html (Open Sans body,
Mulish 700 footer in theme1 #349494 to match the public site).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse

from .models import Feedback

logger = logging.getLogger(__name__)

def feedback_category_item_label(category: str) -> str:
    """Phrase used in staff notification copy (matches form categories)."""
    if category == Feedback.Category.GENERAL:
        return "enquiry"
    if category == Feedback.Category.FEEDBACK:
        return "feedback item"
    if category == Feedback.Category.CORRECTION:
        return "correction"
    return "submission"


def _staff_recipient_names():
    User = get_user_model()
    for row in (
        User.objects.filter(is_staff=True, is_active=True)
        .exclude(Q(email__isnull=True) | Q(email=""))
        .values_list("email", "first_name", "username")
    ):
        email, first_name, username = row
        if not email:
            continue
        name = (first_name or "").strip()
        recipient_name = name if name else (username or "there")
        yield email, recipient_name


def send_feedback_submitted_staff_mail(feedback: Feedback, request) -> None:
    """Notify all active staff (with email) that a new Feedback row exists."""
    path = reverse("admin:wts_app_feedback_change", args=[str(feedback.pk)])
    admin_url = request.build_absolute_uri(path)
    category = feedback.category
    item_label = feedback_category_item_label(category)
    submission_id = str(feedback.pk)

    recipients = list(_staff_recipient_names())
    if not recipients:
        logger.info("No staff recipients with email; skipping feedback notification for %s", submission_id)
        return

    subject = f"WhereTheyStand: new {item_label} submitted"

    for to_email, recipient_name in recipients:
        context = {
            "recipient_name": recipient_name,
            "item_label": item_label,
            "submission_id": submission_id,
            "admin_url": admin_url,
        }
        text_body = render_to_string("emails/staff/feedback_submitted.txt", context)
        html_body = render_to_string("emails/staff/feedback_submitted.html", context)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
        )
        msg.attach_alternative(html_body, "text/html")
        try:
            msg.send()
        except Exception:
            logger.exception(
                "Failed to send feedback staff notification to %s for submission %s",
                to_email,
                submission_id,
            )
