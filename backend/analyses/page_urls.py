from django.urls import path

from .page_views import AnalysisIndexView, AnalysisResultView

app_name = "analyses"

urlpatterns = [
    path("", AnalysisIndexView.as_view(), name="index"),
    path("<int:pk>/", AnalysisResultView.as_view(), name="result"),
]