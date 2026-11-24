from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status as http_status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .camera_capture import request_stop
from .models import AnalysisJob, InputType, JobStatus
from .serializers import (
    AnalysisJobDetailSerializer,
    AnalysisJobSerializer,
    AnalysisJobStatusSerializer,
    AnalysisJobUpdateSerializer,
)
from .tasks import run_analysis_job


class QueueUnavailable(APIException):
    status_code = 503
    default_detail = "분석 작업을 대기열에 등록하지 못했습니다. 잠시 후 다시 시도하세요."
    default_code = "queue_unavailable"


class AnalysisJobViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = AnalysisJob.objects.visible().select_related("user")

        if self.action in ("list", "retrieve"):
            queryset = queryset.prefetch_related("predictions__segments")

        if self.request.user.is_staff:
            return queryset
        return queryset.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AnalysisJobDetailSerializer
        if self.action == "partial_update":
            return AnalysisJobUpdateSerializer
        if self.action == "status":
            return AnalysisJobStatusSerializer
        return AnalysisJobSerializer

    def perform_create(self, serializer):
        job = serializer.save(user=self.request.user)
        transaction.on_commit(lambda: self._enqueue(job))

    def _enqueue(self, job):
        try:
            result = run_analysis_job.delay(job.id)
        except Exception as error:
            job.status = JobStatus.FAILED
            job.error_message = f"작업 큐 등록 실패: {error}"[:1000]
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at"])
            raise QueueUnavailable() from error

        job.celery_task_id = result.id
        job.save(update_fields=["celery_task_id"])

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        job = self.get_object()
        serializer = self.get_serializer(job)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        job = self.get_object()

        if job.input_type != InputType.WEBCAM:
            return self._conflict("웹캠 작업만 녹화를 종료할 수 있습니다.")
        if job.status == JobStatus.PENDING:
            return self._conflict("아직 녹화가 시작되지 않았습니다.")
        if job.status != JobStatus.PROCESSING or job.capture_seconds is not None:
            return self._conflict("녹화 중인 작업이 아닙니다.")

        elapsed = (timezone.now() - job.started_at).total_seconds()
        if elapsed < settings.CAMERA_MIN_SECONDS:
            return self._conflict(
                f"녹화 시작 후 {settings.CAMERA_MIN_SECONDS}초가 지나야 종료할 수 있습니다."
            )

        request_stop(job.id)
        return Response(
            {"detail": "녹화 종료를 요청했습니다. 곧 분석이 시작됩니다."},
            status=http_status.HTTP_202_ACCEPTED,
        )

    @staticmethod
    def _conflict(message):
        return Response({"detail": message}, status=http_status.HTTP_409_CONFLICT)