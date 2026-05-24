from django.urls import path

from .views.auth import (
    AuthCallbackView,
    CsrfView,
    LogoutView,
    SessionView,
    login_view,
)

urlpatterns = [
    path("login/", login_view, name="auth-login"),
    path("callback/", AuthCallbackView.as_view(), name="auth-callback"),
    path("oauth-auth/", AuthCallbackView.as_view(), name="oauth-auth"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("session/", SessionView.as_view(), name="auth-session"),
    path("csrf/", CsrfView.as_view(), name="auth-csrf"),
]
