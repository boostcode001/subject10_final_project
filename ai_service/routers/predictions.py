"""
predictions.py
POST /api/v1/predict/ : Celery Worker(지금은 Swagger)가 보낸 영상 1개를 분석해 JSON으로 반환
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from services.action_inference import CONFIDENCE_THRESHOLD, predict_tracks
from services.pose_pipeline import DEFAULT_MAX_PEOPLE, VideoReadError, extract_tracks


# ① 라우터와 허용 확장자
router = APIRouter(prefix="/api/v1", tags=["predictions"])

ALLOWED_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv"}


# ② 영상 분석 API
@router.post("/predict/")
def predict_video(
    request: Request,
    file: UploadFile = File(...),
    max_people: int = Form(DEFAULT_MAX_PEOPLE),
):
    # ②-1 모델 준비 여부
    artifacts = request.app.state.artifacts
    if artifacts is None:
        raise HTTPException(status_code=503, detail="모델이 준비되지 않았습니다.")

    # ②-2 입력 검사
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 형식입니다: {suffix or '(확장자 없음)'}",
        )
    if not 1 <= max_people <= DEFAULT_MAX_PEOPLE:
        raise HTTPException(
            status_code=400,
            detail=f"max_people은 1~{DEFAULT_MAX_PEOPLE} 사이여야 합니다.",
        )

    # ②-3 임시 파일로 저장
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = temp.name
    try:
        shutil.copyfileobj(file.file, temp)
        temp.close()

        # ②-4 관절 추출 → 동작 예측
        started = time.perf_counter()
        try:
            video = extract_tracks(temp_path, max_people=max_people)
        except VideoReadError as error:
            raise HTTPException(status_code=400, detail=str(error))
        predictions, skipped = predict_tracks(artifacts, video)
        elapsed = time.perf_counter() - started

        # ②-5 결과 메시지 (오류가 아닌 정상 결과)
        message = None
        if not video.tracks:
            message = "영상에서 사람을 찾지 못했습니다."
        elif not predictions:
            message = "동작을 판단할 만큼 유효한 프레임이 없습니다."

        return {
            "predictions": predictions,
            "skipped_tracks": skipped,
            "video": {
                "fps": round(video.fps, 2),
                "frame_count": video.frame_count,
                "duration_sec": round(video.duration_sec, 2),
            },
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "elapsed_sec": round(elapsed, 2),
            "message": message,
        }
    finally:
        # ②-6 임시 파일 삭제 (성공·실패와 관계없이)
        temp.close()
        if os.path.exists(temp_path):
            os.remove(temp_path)