from pathlib import Path

from rest_framework import serializers

from .models import ActionSegment, AnalysisJob, InputType, JobStatus, PersonPrediction

ALLOWED_VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv"}
FINISHED_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED}


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
        ]


class PersonPredictionSerializer(serializers.ModelSerializer):
    action_label_display = serializers.CharField(
        source="get_action_label_display", read_only=True
    )
    segments = ActionSegmentSerializer(many=True, read_only=True)

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
            "segments",
        ]


class AnalysisJobSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source="user.username")

    class Meta:
        model = AnalysisJob
        fields = [
            "id",
            "username",
            "input_type",
            "video_file",
            "title",
            "memo",
            "expected_action",
            "status",
            "result_message",
            "error_message",
            "created_at",
            "finished_at",
        ]
        read_only_fields = [
            "status",
            "result_message",
            "error_message",
            "created_at",
            "finished_at",
        ]

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

        if input_type == InputType.WEBCAM:
            raise serializers.ValidationError(
                {"input_type": "IP Webcam 입력은 8단계에서 지원합니다."}
            )

        if input_type == InputType.UPLOAD and not attrs.get("video_file"):
            raise serializers.ValidationError(
                {"video_file": "영상 업로드 방식은 영상 파일이 필요합니다."}
            )

        return attrs


class AnalysisJobDetailSerializer(AnalysisJobSerializer):
    predictions = PersonPredictionSerializer(many=True, read_only=True)

    class Meta(AnalysisJobSerializer.Meta):
        fields = AnalysisJobSerializer.Meta.fields + [
            "video_duration_sec",
            "video_fps",
            "celery_task_id",
            "started_at",
            "processing_seconds",
            "predictions",
        ]
        read_only_fields = AnalysisJobSerializer.Meta.read_only_fields + [
            "video_duration_sec",
            "video_fps",
            "celery_task_id",
            "started_at",
        ]


class AnalysisJobUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisJob
        fields = ["id", "title", "memo"]
        read_only_fields = ["id"]


class AnalysisJobStatusSerializer(serializers.ModelSerializer):
    is_finished = serializers.SerializerMethodField()

    class Meta:
        model = AnalysisJob
        fields = [
            "id",
            "status",
            "is_finished",
            "result_message",
            "error_message",
            "created_at",
            "started_at",
            "finished_at",
            "processing_seconds",
        ]

    def get_is_finished(self, job):
        return job.status in FINISHED_STATUSES