from django.shortcuts import redirect

from wts import oauth
from wts_app.views.auth import AUTH_NEXT_SESSION_KEY, DEFAULT_POST_LOGIN_PATH, _callback_redirect_uri


def login_view_redirect(request):
    request.session[AUTH_NEXT_SESSION_KEY] = DEFAULT_POST_LOGIN_PATH
    return oauth.cloudflare.authorize_redirect(request, _callback_redirect_uri(request))
