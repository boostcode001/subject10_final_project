import logging
import time

from celery import shared_task
from django.utils import timezone

from .models import AnalysisJob, JobStatus

logger = logging.getLogger(__name__)

STEP6_DUMMY_SECONDS = 2


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
    logger.info("작업 %s 처리 시작", job_id)

    try:
        # 6단계: AI 미연결 — 7단계에서 FastAPI 호출로 교체
        time.sleep(STEP6_DUMMY_SECONDS)
        job.result_message = "6단계 연결 테스트 (AI 미연결)"
        job.status = JobStatus.COMPLETED
    except Exception as error:
        logger.exception("작업 %s 처리 실패", job_id)
        job.status = JobStatus.FAILED
        job.error_message = str(error)[:1000]
    finally:
        job.finished_at = timezone.now()
        job.save(
            update_fields=["status", "result_message", "error_message", "finished_at"]
        )

    logger.info("작업 %s 종료: %s", job_id, job.status)
    return {"job_id": job_id, "status": job.status}