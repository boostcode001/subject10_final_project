from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AnalysisJobViewSet

router = DefaultRouter()
router.register("analyses", AnalysisJobViewSet, basename="analysis")

urlpatterns = [
    path("", include(router.urls)),
]