"""System events admin API."""

from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from wts_app.ingestion.preprocess import process_system_event
from wts_app.models import MonitoredSource, SystemEvent
from wts_app.views.base import StandardResultsSetPagination


class MonitoredSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonitoredSource
        fields = (
            "id",
            "slug",
            "name",
            "handler",
            "config",
            "is_active",
            "default_recipe_key",
            "poll_interval_minutes",
        )


class SystemEventSerializer(serializers.ModelSerializer):
    source_slug = serializers.CharField(source="source.slug", read_only=True)

    class Meta:
        model = SystemEvent
        fields = (
            "id",
            "source",
            "source_slug",
            "external_id",
            "payload",
            "status",
            "workbook",
            "error_message",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class MonitoredSourceListView(generics.ListAPIView):
    queryset = MonitoredSource.objects.all()
    serializer_class = MonitoredSourceSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]


class SystemEventListView(generics.ListAPIView):
    serializer_class = SystemEventSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = SystemEvent.objects.select_related("source", "workbook").order_by("-created_at")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        source_slug = self.request.query_params.get("source")
        if source_slug:
            qs = qs.filter(source__slug=source_slug)
        return qs


class SystemEventDetailView(generics.RetrieveAPIView):
    serializer_class = SystemEventSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]
    queryset = SystemEvent.objects.select_related("source", "workbook")


class SystemEventRetryView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        event = get_object_or_404(SystemEvent, pk=pk)
        try:
            process_system_event(str(event.id))
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        event.refresh_from_db()
        return Response(SystemEventSerializer(event).data)
