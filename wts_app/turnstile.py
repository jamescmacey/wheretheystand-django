"""Cloudflare Turnstile server-side verification."""

from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile_token(token: str, remoteip: str | None = None) -> bool:
    """
    Returns True if Cloudflare confirms the token is valid.
    On transport errors or malformed responses, returns False.
    """
    if settings.TURNSTILE_BYPASS_CODE and settings.TURNSTILE_BYPASS_CODE == token:
        return True
        
    if not token or not str(token).strip():
        return False
    data = {
        "secret": settings.TURNSTILE_SECRET_KEY,
        "response": token.strip(),
    }
    if remoteip:
        data["remoteip"] = remoteip
    try:
        response = requests.post(
            TURNSTILE_VERIFY_URL,
            data=data,
            timeout=10,
        )
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Turnstile verification request failed: %s", exc)
        return False
    return bool(body.get("success"))
