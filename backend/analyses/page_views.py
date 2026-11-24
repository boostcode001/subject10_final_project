from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView

from .models import EXPECTED_ACTION_CHOICES, AnalysisJob, JobStatus
from .serializers import ALLOWED_VIDEO_SUFFIXES
from .uncertainty import evaluate_person


def home(request):
    if request.user.is_authenticated:
        return redirect("analyses:index")
    return render(request, "home.html")


def _user_jobs(user):
    queryset = AnalysisJob.objects.visible().prefetch_related("predictions__segments")
    if user.is_staff:
        return queryset
    return queryset.filter(user=user)


def _camera_config():
    return {
        "cameraMinSeconds": settings.CAMERA_MIN_SECONDS,
        "cameraMaxSeconds": settings.CAMERA_MAX_SECONDS,
    }


@method_decorator(ensure_csrf_cookie, name="dispatch")
class AnalysisIndexView(LoginRequiredMixin, TemplateView):
    template_name = "analyses/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["camera_keys"] = list(settings.CAMERA_SOURCES)
        context["expected_actions"] = EXPECTED_ACTION_CHOICES
        context["allowed_suffixes"] = ", ".join(sorted(ALLOWED_VIDEO_SUFFIXES))
        context["page_config"] = _camera_config()
        return context


@method_decorator(ensure_csrf_cookie, name="dispatch")
class AnalysisResultView(LoginRequiredMixin, TemplateView):
    template_name = "analyses/result.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        job = get_object_or_404(_user_jobs(self.request.user), pk=kwargs["pk"])

        people = []
        for person in sorted(job.predictions.all(), key=lambda p: p.track_id):
            people.append(
                {
                    "person": person,
                    "uncertainty": evaluate_person(person),
                    "segments": sorted(person.segments.all(), key=lambda s: s.segment_no),
                }
            )

        is_finished = job.status in (JobStatus.COMPLETED, JobStatus.FAILED)
        context["job"] = job
        context["people"] = people
        context["is_finished"] = is_finished
        context["page_config"] = {**_camera_config(), "jobId": job.id, "isFinished": is_finished}
        return context