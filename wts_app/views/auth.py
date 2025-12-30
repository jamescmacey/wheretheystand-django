from wts import oauth
from django.contrib.auth import login
from django.shortcuts import redirect
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from rest_framework.views import APIView

class OAuthAuthorisation(APIView):
    def get(self, request, options=None):
        token = oauth.cloudflare.authorize_access_token(request)
        user = oauth.cloudflare.userinfo(token=token)
        
        try:
            user = User.objects.get(email=user.email, is_active=True)
            login(request, user)
            return redirect('/admin')
        except:
            raise PermissionDenied()
    