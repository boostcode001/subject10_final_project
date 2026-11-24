"""
main.py
FastAPI 앱을 만들고, 서버가 시작될 때 모델을 한 번만 불러와 보관합니다.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from routers.predictions import router as predictions_router
from services.model_loader import load_artifacts


# ① 서버 시작·종료 시 실행할 작업
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.artifacts = load_artifacts()
        app.state.model_error = None
    except Exception as error:
        app.state.artifacts = None
        app.state.model_error = str(error)
    yield
    app.state.artifacts = None


# ② FastAPI 앱 생성
app = FastAPI(
    title="subject10 AI Service",
    description="MediaPipe heavy + Random Forest 동작 추론 서버",
    version="0.1.0",
    lifespan=lifespan,
)

# ③ 예측 API 연결 (2-3단계에서 추가)
app.include_router(predictions_router)


# ④ 서버·모델 상태 확인
@app.get("/health")
def health():
    artifacts = app.state.artifacts
    if artifacts is None:
        return {
            "server": "ok",
            "model_ready": False,
            "error": app.state.model_error,
        }
    return {
        "server": "ok",
        "model_ready": True,
        "classes": artifacts["classes"],
        "sequence_steps": artifacts["sequence_steps"],
        "feature_count": artifacts["feature_count"],
    }