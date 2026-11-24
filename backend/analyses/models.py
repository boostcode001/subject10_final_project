"""
analyses/models.py
DB 테이블 명세서 v1 (T01 분석 작업, T02 사람별 예측, T03 동작 구간)
"""
from django.conf import settings
from django.db import models


# ① 선택지 (choices)
class InputType(models.TextChoices):
    UPLOAD = "UPLOAD", "영상 업로드"
    WEBCAM = "WEBCAM", "IP Webcam"


class JobStatus(models.TextChoices):
    PENDING = "PENDING", "대기"
    PROCESSING = "PROCESSING", "처리 중"
    COMPLETED = "COMPLETED", "완료"
    FAILED = "FAILED", "실패"


class ActionLabel(models.TextChoices):
    SEATED_KNEE_EXTENSION = "seated_knee_extension", "A001 앉아서 무릎 펴기"
    SHOULDER_REACH_UP_DOWN = "shoulder_reach_up_down", "A002 팔 위아래로 뻗기"
    SIDE_LYING_LEG_RAISE = "side_lying_leg_raise", "A006 옆으로 누워 다리 들기"
    UNKNOWN = "UNKNOWN", "판단 불확실"


# 사용자가 고르는 예상 동작은 UNKNOWN 제외
EXPECTED_ACTION_CHOICES = [
    choice for choice in ActionLabel.choices if choice[0] != ActionLabel.UNKNOWN
]


# ② 조회 기준을 한 곳에 모음 (나중에 Soft Delete로 바꿀 때 여기만 수정)
class AnalysisJobQuerySet(models.QuerySet):
    def visible(self):
        return self.all()


# ③ T01 분석 작업
class AnalysisJob(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="analysis_jobs",
    )
    input_type = models.CharField(max_length=10, choices=InputType.choices)
    video_file = models.FileField(
        upload_to="videos/%Y/%m/%d/", max_length=255, null=True, blank=True
    )
    camera_key = models.CharField(max_length=50, null=True, blank=True)
    capture_seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    video_duration_sec = models.FloatField(null=True, blank=True)
    video_fps = models.FloatField(null=True, blank=True)
    title = models.CharField(max_length=100, blank=True, default="")
    memo = models.TextField(blank=True, default="")
    expected_action = models.CharField(
        max_length=50, choices=EXPECTED_ACTION_CHOICES, null=True, blank=True
    )
    status = models.CharField(
        max_length=12, choices=JobStatus.choices, default=JobStatus.PENDING
    )
    celery_task_id = models.CharField(max_length=255, null=True, blank=True)
    result_message = models.CharField(max_length=255, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = AnalysisJobQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "분석 작업"
        verbose_name_plural = "분석 작업"

    def __str__(self):
        return f"#{self.pk} {self.get_input_type_display()} {self.get_status_display()}"

    @property
    def processing_seconds(self):
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


# ④ T02 사람별 예측
class PersonPrediction(models.Model):
    job = models.ForeignKey(
        AnalysisJob, on_delete=models.CASCADE, related_name="predictions"
    )
    track_id = models.PositiveIntegerField()
    action_label = models.CharField(max_length=50, choices=ActionLabel.choices)
    confidence = models.FloatField()
    segment_count = models.PositiveIntegerField()
    mean_keypoint_conf = models.FloatField(null=True, blank=True)
    valid_frame_ratio = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["job", "track_id"]
        verbose_name = "사람별 예측"
        verbose_name_plural = "사람별 예측"
        constraints = [
            models.UniqueConstraint(
                fields=["job", "track_id"], name="unique_track_per_job"
            ),
        ]

    def __str__(self):
        return f"작업 #{self.job_id} / Track {self.track_id} / {self.action_label}"


# ⑤ T03 동작 구간
class ActionSegment(models.Model):
    person = models.ForeignKey(
        PersonPrediction, on_delete=models.CASCADE, related_name="segments"
    )
    segment_no = models.PositiveSmallIntegerField()
    start_sec = models.FloatField()
    end_sec = models.FloatField()
    action_label = models.CharField(max_length=50, choices=ActionLabel.choices)
    confidence = models.FloatField()
    probabilities = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["person", "segment_no"]
        verbose_name = "동작 구간"
        verbose_name_plural = "동작 구간"
        constraints = [
            models.UniqueConstraint(
                fields=["person", "segment_no"], name="unique_segment_per_person"
            ),
        ]

    def __str__(self):
        return f"{self.person} / 구간 {self.segment_no}"

    @property
    def duration_sec(self):
        return self.end_sec - self.start_sec