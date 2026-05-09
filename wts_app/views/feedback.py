from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny

from ..models import Feedback
from ..staff_mail import send_feedback_submitted_staff_mail
from ..turnstile import verify_turnstile_token


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class FeedbackCreateSerializer(serializers.ModelSerializer):
    """Accepts a Turnstile token; it is verified and not stored on the model."""

    turnstile = serializers.CharField(write_only=True)

    class Meta:
        model = Feedback
        fields = ("id", "category", "name", "email", "message", "turnstile")
        read_only_fields = ("id",)

    def validate(self, attrs):
        token = attrs.pop("turnstile", None)
        request = self.context.get("request")
        remoteip = _client_ip(request) if request else None
        if not verify_turnstile_token(token, remoteip=remoteip):
            raise serializers.ValidationError(
                {"turnstile": ["Turnstile verification failed. Please try again."]}
            )
        return attrs


class FeedbackCreateView(generics.CreateAPIView):
    """
    Public endpoint to submit feedback. Requires a valid Cloudflare Turnstile token
    in the JSON body under the key ``turnstile``.
    """

    queryset = Feedback.objects.all()
    serializer_class = FeedbackCreateSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        instance = serializer.save()
        send_feedback_submitted_staff_mail(instance, self.request)
