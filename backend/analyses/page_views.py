from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView

from .models import EXPECTED_ACTION_CHOICES, AnalysisJob, JobStatus, PersonPrediction
from .serializers import ALLOWED_VIDEO_SUFFIXES
from .uncertainty import evaluate_person

RECENT_JOB_LIMIT = 10


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


# ---------- 10단계: 관리자 대시보드 ----------

PROCESSING_DURATION = ExpressionWrapper(
    F("finished_at") - F("started_at"),
    output_field=DurationField(),
)


def _field_choices(model, field_name):
    return list(model._meta.get_field(field_name).choices)


def _round_or_none(value, digits=4):
    return round(value, digits) if value is not None else None


def _seconds_or_none(duration):
    return round(duration.total_seconds(), 1) if duration is not None else None


def _action_stats():
    rows = PersonPrediction.objects.values("action_label").annotate(
        count=Count("id"),
        avg_confidence=Avg("confidence"),
    )
    found = {row["action_label"]: row for row in rows}

    stats = []
    for value, label in _field_choices(PersonPrediction, "action_label"):
        row = found.get(value, {})
        stats.append(
            {
                "value": value,
                "label": str(label),
                "count": row.get("count", 0),
                "avg_confidence": _round_or_none(row.get("avg_confidence")),
            }
        )
    return stats


def _status_stats():
    rows = AnalysisJob.objects.values("status").annotate(count=Count("id"))
    found = {row["status"]: row["count"] for row in rows}
    return [
        {"value": value, "label": str(label), "count": found.get(value, 0)}
        for value, label in _field_choices(AnalysisJob, "status")
    ]


def _input_stats():
    rows = AnalysisJob.objects.values("input_type").annotate(
        count=Count("id"),
        avg_processing=Avg(PROCESSING_DURATION, filter=Q(status=JobStatus.COMPLETED)),
    )
    found = {row["input_type"]: row for row in rows}

    stats = []
    for value, label in _field_choices(AnalysisJob, "input_type"):
        row = found.get(value, {})
        stats.append(
            {
                "value": value,
                "label": str(label),
                "count": row.get("count", 0),
                "avg_processing": _seconds_or_none(row.get("avg_processing")),
            }
        )
    return stats


def _summary(status_stats):
    counts = {item["value"]: item["count"] for item in status_stats}
    completed = counts.get(JobStatus.COMPLETED, 0)
    failed = counts.get(JobStatus.FAILED, 0)
    finished = completed + failed
    avg_processing = AnalysisJob.objects.filter(status=JobStatus.COMPLETED).aggregate(
        value=Avg(PROCESSING_DURATION)
    )["value"]
    return {
        "total": sum(counts.values()),
        "completed": completed,
        "failed": failed,
        "success_rate": round(completed / finished * 100) if finished else None,
        "avg_processing": _seconds_or_none(avg_processing),
    }


def _recent_jobs():
    jobs = (
        AnalysisJob.objects.select_related("user")
        .prefetch_related("predictions")
        .order_by("-id")[:RECENT_JOB_LIMIT]
    )
    recent = []
    for job in jobs:
        predictions = list(job.predictions.all())
        top = max(predictions, key=lambda p: p.confidence or 0, default=None)
        recent.append({"job": job, "top": top, "people": len(predictions)})
    return recent


class DashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "analyses/dashboard.html"

    def test_func(self):
        return self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        actions = _action_stats()
        statuses = _status_stats()
        context["summary"] = _summary(statuses)
        context["actions"] = actions
        context["statuses"] = statuses
        context["inputs"] = _input_stats()
        context["recent_jobs"] = _recent_jobs()
        context["chart_data"] = {"actions": actions, "statuses": statuses}
        return context