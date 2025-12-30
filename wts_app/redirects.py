from django.shortcuts import redirect
from wts import oauth

def login_view_redirect(request):
    redirect_uri = request.build_absolute_uri('/auth/oauth-auth')
    return oauth.cloudflare.authorize_redirect(request, redirect_uri)