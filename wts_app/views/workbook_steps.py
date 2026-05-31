"""Workbook pipeline step API views."""

from django.http import Http404
from django.shortcuts import redirect, get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from wts_app.ingestion.gemini import submit_gemini_for_step
from wts_app.ingestion.orchestrator import (
    apply_batch_defaults,
    commit_step,
    compute_progress,
    ensure_steps,
    reject_step,
    save_draft,
    start_step,
)
from wts_app.ingestion.recipes.registry import get_recipe, PIPELINE_RECIPE_REGISTRY
from wts_app.models import Workbook, WorkbookFile, WorkbookStep
from wts_app.views.workbooks import WorkbookAccessMixin


class WorkbookStepSerializer(serializers.ModelSerializer):
    production_object_type = serializers.SerializerMethodField()
    ui_schema = serializers.SerializerMethodField()

    class Meta:
        model = WorkbookStep
        fields = (
            "id",
            "workbook",
            "workbook_file",
            "step_key",
            "sequence",
            "status",
            "payload",
            "error_message",
            "committed_at",
            "committed_by",
            "production_object_id",
            "production_object_type",
            "ui_schema",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_production_object_type(self, obj):
        if obj.production_content_type_id:
            return obj.production_content_type.model
        return None

    def get_ui_schema(self, obj):
        if not obj.workbook.recipe_key:
            return {}
        try:
            recipe = get_recipe(obj.workbook.recipe_key)
            return recipe.ui_schema(obj.step_key)
        except ValueError:
            return {}


class WorkbookStepListView(WorkbookAccessMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def get_workbook(self):
        return get_object_or_404(self.get_workbook_queryset(), pk=self.kwargs["pk"])

    def get(self, request, pk):
        workbook = self.get_workbook()
        qs = WorkbookStep.objects.filter(workbook=workbook).order_by(
            "workbook_file_id", "sequence"
        )
        file_id = request.query_params.get("workbook_file")
        if file_id:
            qs = qs.filter(workbook_file_id=file_id)
        return Response(
            {
                "progress": compute_progress(workbook),
                "results": WorkbookStepSerializer(qs, many=True).data,
            }
        )


class WorkbookStepDetailView(WorkbookAccessMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def get_workbook(self):
        return get_object_or_404(self.get_workbook_queryset(), pk=self.kwargs["pk"])

    def get_step(self, workbook):
        qs = WorkbookStep.objects.filter(workbook=workbook, step_key=self.kwargs["step_key"])
        file_id = self.request.query_params.get("workbook_file")
        if file_id:
            qs = qs.filter(workbook_file_id=file_id)
        elif workbook.files.count() == 1:
            qs = qs.filter(workbook_file=workbook.files.first())
        return get_object_or_404(qs)

    def get(self, request, pk, step_key):
        workbook = self.get_workbook()
        step = self.get_step(workbook)
        return Response(WorkbookStepSerializer(step).data)

    def patch(self, request, pk, step_key):
        workbook = self.get_workbook()
        step = self.get_step(workbook)
        payload = request.data.get("payload", request.data)
        if not isinstance(payload, dict):
            return Response(
                {"detail": "payload must be an object."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            step = save_draft(step, payload)
        except (ValueError, Exception) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(WorkbookStepSerializer(step).data)


class WorkbookStepActionView(WorkbookAccessMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def get_workbook(self):
        return get_object_or_404(self.get_workbook_queryset(), pk=self.kwargs["pk"])

    def get_step(self, workbook):
        qs = WorkbookStep.objects.filter(workbook=workbook, step_key=self.kwargs["step_key"])
        file_id = self.request.data.get("workbook_file") or self.request.query_params.get(
            "workbook_file"
        )
        if file_id:
            qs = qs.filter(workbook_file_id=file_id)
        elif workbook.files.count() == 1:
            qs = qs.filter(workbook_file=workbook.files.first())
        return get_object_or_404(qs)

    def post(self, request, pk, step_key, action):
        workbook = self.get_workbook()
        step = self.get_step(workbook)

        try:
            if action == "start":
                if step_key == "gemini_extract":
                    submit_gemini_for_step(step)
                    step.refresh_from_db()
                else:
                    start_step(step)
                    step.refresh_from_db()
            elif action == "commit":
                step = commit_step(step, actor=request.user)
            elif action == "reject":
                reason = request.data.get("reason", "")
                step = reject_step(step, actor=request.user, reason=reason)
            else:
                return Response(status=status.HTTP_404_NOT_FOUND)
        except (ValueError, Exception) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(WorkbookStepSerializer(step).data)


class WorkbookApplyBatchDefaultsView(WorkbookAccessMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        workbook = get_object_or_404(self.get_workbook_queryset(), pk=pk)
        if "batch_defaults" in request.data:
            workbook.batch_defaults = request.data["batch_defaults"]
            workbook.save(update_fields=["batch_defaults", "updated_at"])
        count = apply_batch_defaults(workbook)
        return Response(
            {
                "batch_defaults": workbook.batch_defaults,
                "steps_updated": count,
            }
        )


class WorkbookEnsureStepsView(WorkbookAccessMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        workbook = get_object_or_404(self.get_workbook_queryset(), pk=pk)
        if workbook.status == Workbook.Status.CLOSED:
            return Response(
                {"detail": "Workbook is closed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        recipe_key = request.data.get("recipe_key") or workbook.recipe_key
        if not recipe_key:
            return Response(
                {"detail": "recipe_key is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if recipe_key not in PIPELINE_RECIPE_REGISTRY:
            return Response(
                {"detail": f"Unknown recipe_key '{recipe_key}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        workbook.recipe_key = recipe_key
        workbook.save(update_fields=["recipe_key", "updated_at"])

        file_id = request.data.get("workbook_file")
        if file_id:
            workbook_file = get_object_or_404(WorkbookFile, pk=file_id, workbook=workbook)
            steps = ensure_steps(workbook, workbook_file=workbook_file)
        else:
            steps = ensure_steps(workbook)
        return Response(
            {
                "recipe_key": recipe_key,
                "steps_created": len(steps),
                "progress": compute_progress(workbook),
            }
        )


class WorkbookFileDownloadView(WorkbookAccessMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAdminUser]

    def get(self, request, pk, file_pk):
        workbook = get_object_or_404(self.get_workbook_queryset(), pk=pk)
        workbook_file = get_object_or_404(
            WorkbookFile.objects.filter(workbook=workbook),
            pk=file_pk,
        )
        if not workbook_file.file:
            raise Http404
        # The str() of file field gives a signed URL when using GCS storage
        return redirect(str(workbook_file.file.url))
