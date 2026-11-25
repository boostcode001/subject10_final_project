from pathlib import Path

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from .models import ActionSegment, AnalysisJob, InputType, JobStatus, PersonPrediction
from .uncertainty import evaluate_person, label_display

ALLOWED_VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv"}
FINISHED_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED}


def job_phase(job):
    if job.status == JobStatus.PENDING:
        return "waiting"
    if job.status == JobStatus.PROCESSING:
        if job.input_type == InputType.WEBCAM and job.capture_seconds is None:
            return "recording"
        return "analyzing"
    if job.status == JobStatus.COMPLETED:
        return "completed"
    return "failed"


class ActionSegmentSerializer(serializers.ModelSerializer):
    action_label_display = serializers.CharField(
        source="get_action_label_display", read_only=True
    )

    class Meta:
        model = ActionSegment
        fields = [
            "segment_no",
            "start_sec",
            "end_sec",
            "duration_sec",
            "action_label",
            "action_label_display",
            "confidence",
            "probabilities",
        ]


class PersonPredictionSerializer(serializers.ModelSerializer):
    action_label_display = serializers.CharField(
        source="get_action_label_display", read_only=True
    )
    segments = ActionSegmentSerializer(many=True, read_only=True)
    uncertainty = serializers.SerializerMethodField()

    class Meta:
        model = PersonPrediction
        fields = [
            "track_id",
            "action_label",
            "action_label_display",
            "confidence",
            "segment_count",
            "mean_keypoint_conf",
            "valid_frame_ratio",
            "uncertainty",
            "segments",
        ]

    def get_uncertainty(self, person):
        return evaluate_person(person)


class AnalysisJobSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source="user.username")
    phase = serializers.SerializerMethodField()
    top_action = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisJob
        fields = [
            "id",
            "username",
            "input_type",
            "video_file",
            "camera_key",
            "capture_seconds",
            "title",
            "memo",
            "expected_action",
            "status",
            "phase",
            "top_action",
            "celery_task_id",
            "result_message",
            "error_message",
            "created_at",
            "finished_at",
        ]
        read_only_fields = [
            "capture_seconds",
            "status",
            "celery_task_id",
            "result_message",
            "error_message",
            "created_at",
            "finished_at",
        ]

    def get_phase(self, job):
        return job_phase(job)

    def get_top_action(self, job):
        people = list(job.predictions.all())
        if not people:
            return None
        best = max(people, key=lambda person: person.confidence)
        return {
            "label": best.action_label,
            "display": label_display(best.action_label),
            "confidence": best.confidence,
        }

    def validate_video_file(self, video_file):
        if video_file is None:
            return video_file
        suffix = Path(video_file.name).suffix.lower()
        if suffix not in ALLOWED_VIDEO_SUFFIXES:
            allowed = ", ".join(sorted(ALLOWED_VIDEO_SUFFIXES))
            raise serializers.ValidationError(
                f"지원하지 않는 영상 형식입니다. 허용: {allowed}"
            )
        return video_file

    def validate(self, attrs):
        input_type = attrs.get("input_type", InputType.UPLOAD)

        if input_type == InputType.UPLOAD:
            if not attrs.get("video_file"):
                raise serializers.ValidationError(
                    {"video_file": "영상 업로드 방식은 영상 파일이 필요합니다."}
                )
            attrs.pop("camera_key", None)
            return attrs

        if attrs.get("video_file"):
            raise serializers.ValidationError(
                {"video_file": "IP Webcam 방식에는 영상 파일을 함께 보낼 수 없습니다."}
            )

        camera_key = attrs.get("camera_key")
        if not camera_key:
            raise serializers.ValidationError({"camera_key": "카메라를 선택하세요."})
        if camera_key not in settings.CAMERA_SOURCES:
            allowed = ", ".join(settings.CAMERA_SOURCES) or "없음"
            raise serializers.ValidationError(
                {"camera_key": f"허용되지 않은 카메라입니다. 선택 가능: {allowed}"}
            )
        return attrs


class AnalysisJobDetailSerializer(AnalysisJobSerializer):
    predictions = PersonPredictionSerializer(many=True, read_only=True)

    class Meta(AnalysisJobSerializer.Meta):
        fields = AnalysisJobSerializer.Meta.fields + [
            "video_duration_sec",
            "video_fps",
            "started_at",
            "processing_seconds",
            "predictions",
        ]
        read_only_fields = AnalysisJobSerializer.Meta.read_only_fields + [
            "video_duration_sec",
            "video_fps",
            "started_at",
        ]


class AnalysisJobUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisJob
        fields = ["id", "title", "memo"]
        read_only_fields = ["id"]


class AnalysisJobStatusSerializer(serializers.ModelSerializer):
    is_finished = serializers.SerializerMethodField()
    phase = serializers.SerializerMethodField()
    elapsed_sec = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisJob
        fields = [
            "id",
            "input_type",
            "status",
            "phase",
            "is_finished",
            "capture_seconds",
            "result_message",
            "error_message",
            "created_at",
            "started_at",
            "finished_at",
            "elapsed_sec",
            "processing_seconds",
        ]

    def get_is_finished(self, job):
        return job.status in FINISHED_STATUSES

    def get_phase(self, job):
        return job_phase(job)

    def get_elapsed_sec(self, job):
        if job.started_at is None:
            return None
        end = job.finished_at or timezone.now()
        seconds = (end - job.started_at).total_seconds()
        return round(max(seconds, 0.0), 1)