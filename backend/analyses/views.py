from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import AnalysisJob
from .serializers import (
    AnalysisJobDetailSerializer,
    AnalysisJobSerializer,
    AnalysisJobStatusSerializer,
    AnalysisJobUpdateSerializer,
)


class AnalysisJobViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = AnalysisJob.objects.visible().select_related("user")

        if self.action == "retrieve":
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
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        job = self.get_object()
        serializer = self.get_serializer(job)
        return Response(serializer.data)