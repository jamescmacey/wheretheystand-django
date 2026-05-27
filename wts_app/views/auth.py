import os
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from wts import oauth

User = get_user_model()

AUTH_NEXT_SESSION_KEY = "auth_login_next"
DEFAULT_POST_LOGIN_PATH = "/admin"


def _allowed_next_origins():
    explicit = os.getenv("AUTH_ALLOWED_NEXT_ORIGINS", "").strip()
    if explicit:
        return [origin.strip() for origin in explicit.split(",") if origin.strip()]
    origins = set(settings.CORS_ALLOWED_ORIGINS)
    origins.update(
        {
            "https://wheretheystand.nz",
            "https://www.wheretheystand.nz",
            "https://elections.wheretheystand.nz",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://0.0.0.0:3000",
        }
    )
    return sorted(origins)


def _normalize_next_url(url: str) -> str:
    """Expand Nuxt console paths to absolute URLs; leave Django-relative paths (e.g. /admin) as-is."""
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return url
    if url.startswith("/console"):
        site_origin = os.getenv("NUXT_SITE_ORIGIN", "http://localhost:3000").rstrip("/")
        return f"{site_origin}{url}"
    return url


def is_safe_next_url(url: str) -> bool:
    url = _normalize_next_url(url)
    if not url:
        return False
    parsed = urlparse(url)
    allowed_schemes = ("https",)
    if settings.DEBUG:
        allowed_schemes = ("https", "http")
    if parsed.scheme not in allowed_schemes or not parsed.netloc:
        return False
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin in _allowed_next_origins()


def get_post_login_redirect(request) -> str:
    next_url = request.session.pop(AUTH_NEXT_SESSION_KEY, None)
    if next_url:
        next_url = _normalize_next_url(next_url)
        if is_safe_next_url(next_url):
            return next_url
    return DEFAULT_POST_LOGIN_PATH


def sync_user_from_oidc_claims(claims) -> User:
    if hasattr(claims, "get"):
        email = claims.get("email")
    else:
        email = getattr(claims, "email", None)
    email = (email or "").strip().lower()
    if not email:
        raise PermissionDenied("Email claim missing from identity provider.")
    try:
        return User.objects.get(email__iexact=email, is_active=True)
    except User.DoesNotExist:
        raise PermissionDenied("No active user account for this email.")


def _callback_redirect_uri(request) -> str:
    return request.build_absolute_uri("/auth/callback/")


def login_view(request):
    next_url = _normalize_next_url(request.GET.get("next", DEFAULT_POST_LOGIN_PATH))
    if is_safe_next_url(next_url):
        request.session[AUTH_NEXT_SESSION_KEY] = next_url
    else:
        request.session[AUTH_NEXT_SESSION_KEY] = DEFAULT_POST_LOGIN_PATH
    return oauth.cloudflare.authorize_redirect(request, _callback_redirect_uri(request))


class AuthCallbackView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        token = oauth.cloudflare.authorize_access_token(request)
        userinfo = oauth.cloudflare.userinfo(token=token)
        user = sync_user_from_oidc_claims(userinfo)
        login(request, user)
        return redirect(get_post_login_redirect(request))


class LogoutView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return JsonResponse({"ok": True})


class SessionView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"authenticated": False, "user": None})
        user = request.user
        return JsonResponse(
            {
                "authenticated": True,
                "user": {
                    "id": user.pk,
                    "email": user.email,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "github_username": user.github_username,
                    "bio": user.bio,
                    "avatar": user.avatar.url if user.avatar else None,
                    "is_staff": user.is_staff,
                    "is_superuser": user.is_superuser,
                },
            }
        )


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return JsonResponse({"csrfToken": get_token(request)})


# Backward compatibility for existing imports and admin redirect URI
OAuthAuthorisation = AuthCallbackView
