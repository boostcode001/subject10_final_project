"""
segmenter.py
사람 1명의 프레임 목록에서 "움직임이 있는 구간"만 찾아냅니다.

규칙 (2026-11-24 결정)
- 움직임 양 = 이웃 프레임 사이 정규화 좌표(34개)의 평균 변화량 / 시간
- 기준값은 영상마다 그 사람의 움직임 분포로 자동 결정 (정지 상태 대비 상대값)
- 0.5초 미만의 멈춤은 같은 구간으로 이어 붙임
- 2초 미만 구간은 삭제 (학습 동작은 모두 3초 이상)
- 남은 구간은 앞뒤로 1초씩 넓힘 (학습 영상이 "정지 1초 + 동작 + 정지 1초" 형태)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np


# ① 설정값 (환경변수로 조정 가능)
COORD_DIM = 34                                   # 38-D 중 앞 34개가 정규화 좌표
SMOOTH_SEC = 0.5                                 # 움직임 양을 0.5초 단위로 평균
THRESHOLD_RATIO = float(os.getenv("SEGMENT_THRESHOLD_RATIO", "0.25"))
MIN_MOTION_RANGE = float(os.getenv("SEGMENT_MIN_MOTION_RANGE", "0.02"))
MERGE_GAP_SEC = float(os.getenv("SEGMENT_MERGE_GAP_SEC", "0.5"))
MIN_SEGMENT_SEC = float(os.getenv("SEGMENT_MIN_SEC", "2.0"))
PAD_SEC = float(os.getenv("SEGMENT_PAD_SEC", "1.0"))


# ② 결과 자료형
@dataclass
class Segment:
    start_index: int          # 프레임 목록 안의 시작 위치 (포함)
    end_index: int            # 프레임 목록 안의 끝 위치 (포함)
    start_sec: float
    end_sec: float
    motion_sec: float         # 넓히기 전 실제 움직임 길이

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


@dataclass
class SegmentResult:
    segments: list[Segment]
    discarded: int            # 2초 미만이라 버린 구간 수
    threshold: float          # 이번 영상에서 쓴 움직임 기준값 (확인용)


# ③ 프레임마다 움직임 양 계산
def motion_energy(features, times: np.ndarray) -> np.ndarray:
    coords = np.asarray(features, dtype=np.float32)[:, :COORD_DIM]
    energy = np.zeros(len(coords), dtype=np.float32)
    if len(coords) < 2:
        return energy

    change = np.abs(np.diff(coords, axis=0)).mean(axis=1)
    dt = np.maximum(np.diff(times), 1e-3)
    energy[1:] = change / dt
    energy[0] = energy[1]
    return energy


# ④ 시간 기준 이동 평균 (관절 떨림 제거)
def smooth(values: np.ndarray, times: np.ndarray, window_sec: float) -> np.ndarray:
    half = window_sec / 2
    left = np.searchsorted(times, times - half, side="left")
    right = np.searchsorted(times, times + half, side="right")
    cumulative = np.concatenate([[0.0], np.cumsum(values, dtype=np.float64)])
    return (cumulative[right] - cumulative[left]) / np.maximum(right - left, 1)


# ⑤ True가 이어진 구간 찾기
def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs = []
    start = None
    for index, flag in enumerate(mask):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


# ⑥ 구간 검출 메인 함수
def find_segments(features, times_sec) -> SegmentResult:
    times = np.asarray(times_sec, dtype=np.float64)
    if len(times) < 2:
        return SegmentResult([], 0, 0.0)

    energy = smooth(motion_energy(features, times), times, SMOOTH_SEC)

    # ⑥-1 영상마다 기준값 자동 결정
    low, high = np.percentile(energy, [10, 90])
    if high - low < MIN_MOTION_RANGE:
        return SegmentResult([], 0, float(high))
    threshold = low + THRESHOLD_RATIO * (high - low)

    # ⑥-2 움직임 구간 → 짧은 멈춤 이어 붙이기
    merged: list[tuple[int, int]] = []
    for start, end in _runs(energy >= threshold):
        if merged and times[start] - times[merged[-1][1]] < MERGE_GAP_SEC:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    # ⑥-3 2초 미만 삭제
    kept = []
    discarded = 0
    for start, end in merged:
        if times[end] - times[start] < MIN_SEGMENT_SEC:
            discarded += 1
        else:
            kept.append((start, end))

    # ⑥-4 앞뒤로 넓히기 (이웃 구간과는 겹치지 않게 가운데에서 자름)
    segments = []
    for position, (start, end) in enumerate(kept):
        start_time = times[start] - PAD_SEC
        end_time = times[end] + PAD_SEC
        if position > 0:
            previous_end = times[kept[position - 1][1]]
            start_time = max(start_time, (previous_end + times[start]) / 2)
        if position < len(kept) - 1:
            next_start = times[kept[position + 1][0]]
            end_time = min(end_time, (times[end] + next_start) / 2)

        padded_start = int(np.searchsorted(times, start_time, side="left"))
        padded_end = int(np.searchsorted(times, end_time, side="right")) - 1
        segments.append(
            Segment(
                start_index=padded_start,
                end_index=padded_end,
                start_sec=float(times[padded_start]),
                end_sec=float(times[padded_end]),
                motion_sec=float(times[end] - times[start]),
            )
        )

    return SegmentResult(segments, discarded, float(threshold))