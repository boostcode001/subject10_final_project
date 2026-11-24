import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import ActionLabel, ActionSegment, AnalysisJob, JobStatus, PersonPrediction
from .services import AIServiceError, request_prediction

logger = logging.getLogger(__name__)

VALID_LABELS = set(ActionLabel.values)


def _checked_label(label):
    if label not in VALID_LABELS:
        raise ValueError(f"알 수 없는 동작 라벨입니다: {label}")
    return label


@transaction.atomic
def _save_result(job, result):
    predictions = result.get("predictions", [])

    for item in predictions:
        person = PersonPrediction.objects.create(
            job=job,
            track_id=item["track_id"],
            action_label=_checked_label(item["action_label"]),
            confidence=item["confidence"],
            segment_count=item["segment_count"],
            mean_keypoint_conf=item["mean_keypoint_conf"],
            valid_frame_ratio=item["valid_frame_ratio"],
        )
        ActionSegment.objects.bulk_create(
            [
                ActionSegment(
                    person=person,
                    segment_no=segment["segment_no"],
                    start_sec=segment["start_sec"],
                    end_sec=segment["end_sec"],
                    action_label=_checked_label(segment["action_label"]),
                    confidence=segment["confidence"],
                )
                for segment in item.get("segments", [])
            ]
        )

    video = result.get("video") or {}
    job.video_fps = video.get("fps")
    job.video_duration_sec = video.get("duration_sec")
    job.result_message = result.get("message") or f"분석 완료: {len(predictions)}명"


@shared_task
def run_analysis_job(job_id):
    try:
        job = AnalysisJob.objects.get(pk=job_id)
    except AnalysisJob.DoesNotExist:
        logger.warning("작업 %s를 찾을 수 없습니다 (삭제됨).", job_id)
        return {"job_id": job_id, "status": "MISSING"}

    if job.status != JobStatus.PENDING:
        logger.info("작업 %s는 이미 %s 상태라 건너뜁니다.", job_id, job.status)
        return {"job_id": job_id, "status": job.status}

    job.status = JobStatus.PROCESSING
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at"])
    logger.info("작업 %s 처리 시작: FastAPI 호출", job_id)

    try:
        result = request_prediction(job)
        _save_result(job, result)
        job.status = JobStatus.COMPLETED
    except AIServiceError as error:
        logger.warning("작업 %s AI 서버 실패: %s", job_id, error)
        job.status = JobStatus.FAILED
        job.error_message = str(error)[:1000]
    except Exception as error:
        logger.exception("작업 %s 처리 실패", job_id)
        job.status = JobStatus.FAILED
        job.error_message = f"분석 결과 처리 중 오류: {error}"[:1000]
    finally:
        job.finished_at = timezone.now()
        job.save(
            update_fields=[
                "status",
                "result_message",
                "error_message",
                "finished_at",
                "video_fps",
                "video_duration_sec",
            ]
        )

    logger.info("작업 %s 종료: %s", job_id, job.status)
    return {"job_id": job_id, "status": job.status}