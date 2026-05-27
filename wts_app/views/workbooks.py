"""
Workbook views.

User-scoped CRUD for workbooks used to group files ready for ingestion.
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAdminUser

from ..models import Workbook, WorkbookFile
from .base import StandardResultsSetPagination
from django.conf import settings
from django.contrib.auth import get_user_model

class WorkbookAccessMixin:
    """Limit workbook access to those owned by the user or unassigned (user is null)."""

    def get_workbook_queryset(self):
        # NULL does not match user__in=(..., None) in SQL; use Q for unassigned workbooks.
        return Workbook.objects.filter(
            Q(user=self.request.user) | Q(user__isnull=True)
        )

class WorkbookUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = get_user_model()
        fields = ("id", "username", "email", "first_name", "last_name", "avatar")

class WorkbookFileSerializer(serializers.ModelSerializer):
    file = serializers.FileField()
    class Meta:
        model = WorkbookFile
        fields = ("id", "file")
        read_only_fields = ("id", "created_at", "updated_at")

class WorkbookSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(),
        allow_null=True,
        required=False,
    )
    files = WorkbookFileSerializer(many=True, read_only=True)

    class Meta:
        model = Workbook
        fields = ("id", "user", "name", "created_at", "updated_at", "files")
        read_only_fields = ("id", "created_at", "updated_at")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["user"] = (
            WorkbookUserSerializer(instance.user).data if instance.user_id else None
        )
        return data

    def validate_user(self, value):
        request = self.context.get("request")
        if request is None:
            return value

        instance = getattr(self, "instance", None)
        if instance is None:
            if value is not None and value != request.user:
                raise serializers.ValidationError(
                    "Cannot assign workbook to another user."
                )
            return value

        if value == instance.user:
            return value

        if instance.user_id is None and value == request.user:
            return value

        raise serializers.ValidationError(
            "Workbook owner can only be set by claiming an unassigned workbook."
        )

WORKBOOK_ORDERING = frozenset(
    {"updated_at", "-updated_at", "created_at", "-created_at", "name", "-name"}
)


class WorkbookListCreateView(WorkbookAccessMixin, generics.ListCreateAPIView):
    """List or create workbooks for the authenticated user."""

    serializer_class = WorkbookSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = self.get_workbook_queryset()

        scope = (self.request.query_params.get("scope") or "").strip().lower()
        if scope == "mine":
            qs = qs.filter(user=self.request.user)
        elif scope == "system":
            qs = qs.filter(user__isnull=True)

        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(name__icontains=search)

        ordering = (self.request.query_params.get("ordering") or "-updated_at").strip()
        if ordering not in WORKBOOK_ORDERING:
            ordering = "-updated_at"
        return qs.order_by(ordering)

    def perform_create(self, serializer):
        if "user" in serializer.validated_data:
            serializer.save()
        else:
            serializer.save(user=self.request.user)


class WorkbookRetrieveUpdateDestroyView(WorkbookAccessMixin, generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a workbook belonging to the authenticated user."""

    serializer_class = WorkbookSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]
    lookup_field = "pk"

    def get_queryset(self):
        return self.get_workbook_queryset()


class WorkbookFileListCreateView(WorkbookAccessMixin, generics.ListCreateAPIView):
    """List or upload files for a workbook the authenticated user can access."""

    serializer_class = WorkbookFileSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def get_workbook(self):
        return get_object_or_404(self.get_workbook_queryset(), pk=self.kwargs["pk"])

    def get_queryset(self):
        return WorkbookFile.objects.filter(workbook=self.get_workbook()).order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(workbook=self.get_workbook())


class WorkbookFileDestroyView(WorkbookAccessMixin, generics.DestroyAPIView):
    """Delete a file from a workbook the authenticated user can access."""

    serializer_class = WorkbookFileSerializer
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def get_workbook(self):
        return get_object_or_404(self.get_workbook_queryset(), pk=self.kwargs["pk"])

    def get_object(self):
        return get_object_or_404(
            WorkbookFile.objects.filter(workbook=self.get_workbook()),
            pk=self.kwargs["file_pk"],
        )