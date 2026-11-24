"""
pose_pipeline.py
영상 1개 → 사람(Track ID)별 38-D 프레임 Feature 목록

- 사람 박스 + Track ID : YOLO11n-pose + ByteTrack
- 관절               : 박스 안을 MediaPipe heavy로 다시 추출 (33개 → COCO 17개)
- 38-D Feature       : 수업 코드 src.sequence_utils.frame_feature_from_row 그대로 사용
- MediaPipe가 관절을 못 잡은 프레임은 YOLO 관절로 대체하지 않고 버림 (학습 규격 유지)
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import pandas as pd
import torch
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision
from ultralytics import YOLO

from src.pose_utils import COCO_KEYPOINT_NAMES
from src.sequence_utils import frame_feature_from_row


# ① 경로와 설정값
AI_SERVICE_DIR = Path(__file__).resolve().parents[1]
MODELS_DIR = AI_SERVICE_DIR / "models"
YOLO_MODEL_PATH = MODELS_DIR / "yolo11n-pose.pt"
MP_MODEL_PATH = MODELS_DIR / "pose_landmarker_heavy.task"

# 팀 학습과 같은 MediaPipe 33점 → COCO 17점 변환 표
MP_TO_COCO = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]

CROP_PAD = 0.15          # 박스를 상하좌우 15% 넓혀서 자름 (팀 방식)
MP_MIN_CONF = 0.3        # MediaPipe 검출 기준 (팀 방식)
YOLO_CONF = 0.25         # YOLO 사람 검출 기준 (팀 방식)
TRACKER = "bytetrack.yaml"
DEFAULT_MAX_PEOPLE = 5


# ② 오류와 결과를 담는 자료형
class VideoReadError(Exception):
    """영상 파일을 열 수 없거나 프레임이 없을 때 발생합니다."""


@dataclass
class TrackFrames:
    """사람 1명(Track ID 1개)의 프레임별 결과"""

    track_id: int
    frame_ids: list[int] = field(default_factory=list)
    times_sec: list[float] = field(default_factory=list)
    features: list[np.ndarray] = field(default_factory=list)
    keypoint_conf: list[float] = field(default_factory=list)
    detected_frames: int = 0

    @property
    def valid_frames(self) -> int:
        return len(self.features)

    @property
    def valid_frame_ratio(self) -> float:
        if self.detected_frames == 0:
            return 0.0
        return self.valid_frames / self.detected_frames

    @property
    def mean_keypoint_conf(self) -> float:
        if not self.keypoint_conf:
            return 0.0
        return float(np.mean(self.keypoint_conf))


@dataclass
class VideoResult:
    """영상 1개의 처리 결과"""

    fps: float
    frame_count: int
    duration_sec: float
    tracks: dict[int, TrackFrames]


# ③ MediaPipe 준비 (사람마다 잘라서 한 장씩 처리하는 IMAGE 모드)
def _create_landmarker():
    options = vision.PoseLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=str(MP_MODEL_PATH)),
        running_mode=vision.RunningMode.IMAGE,
        num_poses=1,
        min_pose_detection_confidence=MP_MIN_CONF,
        min_pose_presence_confidence=MP_MIN_CONF,
    )
    return vision.PoseLandmarker.create_from_options(options)


# ④ 사람 박스를 넓혀서 자르기
def _crop_box(frame: np.ndarray, box: np.ndarray):
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = box
    box_w, box_h = x2 - x1, y2 - y1

    cx1 = int(max(0, x1 - box_w * CROP_PAD))
    cy1 = int(max(0, y1 - box_h * CROP_PAD))
    cx2 = int(min(width, x2 + box_w * CROP_PAD))
    cy2 = int(min(height, y2 + box_h * CROP_PAD))

    crop = frame[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None, None
    return crop, (cx1, cy1, cx2 - cx1, cy2 - cy1)


# ⑤ 잘라낸 이미지에서 MediaPipe 관절 → 원본 좌표의 COCO 17개
def _mediapipe_keypoints(landmarker, crop: np.ndarray, region):
    image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=cv2.cvtColor(np.ascontiguousarray(crop), cv2.COLOR_BGR2RGB),
    )
    result = landmarker.detect(image)
    if not result.pose_landmarks:
        return None, None

    points = result.pose_landmarks[0]
    offset_x, offset_y, crop_w, crop_h = region

    xy = np.zeros((17, 2), dtype=np.float32)
    conf = np.zeros(17, dtype=np.float32)
    for coco_index, mp_index in enumerate(MP_TO_COCO):
        point = points[mp_index]
        xy[coco_index, 0] = offset_x + point.x * crop_w
        xy[coco_index, 1] = offset_y + point.y * crop_h
        conf[coco_index] = float(getattr(point, "visibility", 1.0) or 0.0)
    return xy, conf


# ⑥ COCO 17개 관절 → 38-D (수업 코드 그대로 사용)
def _feature_from_keypoints(xy: np.ndarray):
    row = {"pose_detected": 1}
    for name, (x, y) in zip(COCO_KEYPOINT_NAMES, xy):
        row[f"{name}_x_px"] = float(x)
        row[f"{name}_y_px"] = float(y)
    return frame_feature_from_row(pd.Series(row))


# ⑦ 영상 1개 처리
def extract_tracks(video_path: str | Path, max_people: int = DEFAULT_MAX_PEOPLE) -> VideoResult:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise VideoReadError(f"영상을 열 수 없습니다: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    device = 0 if torch.cuda.is_available() else "cpu"
    yolo = YOLO(str(YOLO_MODEL_PATH))           # 영상마다 새로 만들어 Track ID를 1부터 시작
    landmarker = _create_landmarker()
    tracks: dict[int, TrackFrames] = {}
    frame_id = 0

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break

            result = yolo.track(
                frame, persist=True, tracker=TRACKER,
                conf=YOLO_CONF, device=device, verbose=False,
            )[0]

            boxes = result.boxes
            if boxes is not None and boxes.id is not None and len(boxes) > 0:
                xyxy = boxes.xyxy.cpu().numpy()
                ids = boxes.id.cpu().numpy().astype(int)
                scores = boxes.conf.cpu().numpy()
                keep = np.argsort(-scores)[:max_people]

                for index in keep:
                    track_id = int(ids[index])
                    track = tracks.setdefault(track_id, TrackFrames(track_id=track_id))
                    track.detected_frames += 1

                    crop, region = _crop_box(frame, xyxy[index])
                    if crop is None:
                        continue
                    xy, conf = _mediapipe_keypoints(landmarker, crop, region)
                    if xy is None:
                        continue
                    feature = _feature_from_keypoints(xy)
                    if feature is None:
                        continue

                    track.frame_ids.append(frame_id)
                    track.times_sec.append(frame_id / fps)
                    track.features.append(feature)
                    track.keypoint_conf.append(float(conf.mean()))

            frame_id += 1
    finally:
        capture.release()
        landmarker.close()

    if frame_id == 0:
        raise VideoReadError(f"읽을 수 있는 프레임이 없습니다: {video_path}")

    return VideoResult(
        fps=float(fps),
        frame_count=frame_id,
        duration_sec=frame_id / fps,
        tracks=tracks,
    )


# ⑧ 터미널 확인용: python -m services.pose_pipeline --source 영상경로
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--max-people", type=int, default=DEFAULT_MAX_PEOPLE)
    args = parser.parse_args()

    started = time.perf_counter()
    video = extract_tracks(args.source, max_people=args.max_people)
    elapsed = time.perf_counter() - started

    print(f"영상: {video.frame_count} frames, {video.fps:.1f} fps, {video.duration_sec:.1f}초")
    print(f"처리 시간: {elapsed:.1f}초 ({video.frame_count / elapsed:.1f} FPS)")
    print(f"사람 수(Track ID): {len(video.tracks)}")
    for track in video.tracks.values():
        print(
            f"  ID {track.track_id}: 검출 {track.detected_frames} / 유효 {track.valid_frames} "
            f"({track.valid_frame_ratio:.0%}), 평균 관절 신뢰도 {track.mean_keypoint_conf:.2f}"
        )