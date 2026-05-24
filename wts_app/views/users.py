from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny

from ..models import User


class UserPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "first_name")


class UserRetrieveView(generics.RetrieveAPIView):
    """Public endpoint to retrieve a user's ID and first name."""

    queryset = User.objects.all()
    serializer_class = UserPublicSerializer
    permission_classes = [AllowAny]
