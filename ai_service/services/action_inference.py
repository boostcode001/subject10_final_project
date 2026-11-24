"""
action_inference.py
사람별 38-D 프레임 목록 → 30 Step Sequence → Random Forest 예측 → 동작·신뢰도 정리

- 30 Step 변환과 1,140개 펼치기는 수업 코드(src.sequence_utils)를 그대로 사용
- 2-3단계: 사람마다 영상 전체를 구간 1개로 보고 1회 예측 (A안)
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from services.pose_pipeline import TrackFrames, VideoResult
from src.sequence_utils import flatten_sequence, resample_sequence


# ① 설정값
MIN_VALID_FRAMES = 10                      # rf_training_info.json의 min_valid_frames
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.55"))
UNKNOWN_LABEL = "UNKNOWN"


# ② 프레임 목록 1개 → 예측 1개
def predict_sequence(artifacts: dict, features: list, frame_ids: list) -> tuple[str, float, dict]:
    matrix = np.asarray(features, dtype=np.float32)
    sequence = resample_sequence(
        matrix,
        frame_ids,
        target_steps=artifacts["sequence_steps"],
    )
    flat = flatten_sequence(sequence)

    model = artifacts["model"]
    row = pd.DataFrame([flat], columns=artifacts["columns"])
    probabilities = model.predict_proba(row)[0]

    best_index = int(np.argmax(probabilities))
    label = str(model.classes_[best_index])
    confidence = float(probabilities[best_index])
    all_probabilities = {
        str(name): round(float(value), 4)
        for name, value in zip(model.classes_, probabilities)
    }
    return label, confidence, all_probabilities


# ③ 신뢰도가 기준보다 낮으면 UNKNOWN
def apply_threshold(label: str, confidence: float) -> str:
    if confidence < CONFIDENCE_THRESHOLD:
        return UNKNOWN_LABEL
    return label


# ④ 사람 1명 → 응답용 딕셔너리
def predict_track(artifacts: dict, track: TrackFrames) -> dict | None:
    if track.valid_frames < MIN_VALID_FRAMES:
        return None

    label, confidence, probabilities = predict_sequence(
        artifacts, track.features, track.frame_ids
    )
    final_label = apply_threshold(label, confidence)

    segment = {
        "segment_no": 1,
        "start_sec": round(track.times_sec[0], 2),
        "end_sec": round(track.times_sec[-1], 2),
        "action_label": final_label,
        "confidence": round(confidence, 4),
    }

    return {
        "track_id": track.track_id,
        "action_label": final_label,
        "confidence": round(confidence, 4),
        "probabilities": probabilities,
        "segment_count": 1,
        "segments": [segment],
        "valid_frames": track.valid_frames,
        "valid_frame_ratio": round(track.valid_frame_ratio, 4),
        "mean_keypoint_conf": round(track.mean_keypoint_conf, 4),
    }


# ⑤ 영상 1개의 모든 사람
def predict_tracks(artifacts: dict, video: VideoResult) -> tuple[list[dict], int]:
    predictions = []
    skipped = 0
    for track in sorted(video.tracks.values(), key=lambda item: item.track_id):
        result = predict_track(artifacts, track)
        if result is None:
            skipped += 1
            continue
        predictions.append(result)
    return predictions, skipped