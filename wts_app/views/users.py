from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny

from ..models import User


class UserPublicSerializer(serializers.ModelSerializer):
    last_initial = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "first_name", "last_initial", "avatar", "github_username", "bio")

    def get_last_initial(self, obj):
        if obj.last_name:
            return obj.last_name[0]
        return ""
   


class UserRetrieveView(generics.RetrieveAPIView):
    """Public endpoint to retrieve a user's basic information."""

    queryset = User.objects.all()
    serializer_class = UserPublicSerializer
    permission_classes = [AllowAny]
