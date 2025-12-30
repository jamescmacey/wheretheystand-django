from django.urls import path
from .views import (
    OAuthAuthorisation
)

urlpatterns = [
    path('oauth-auth/', OAuthAuthorisation.as_view(), name='oauth-auth'),
]
