"""
evaluate_segments.py (확인용)
test_videos/videos/S02, S03 영상 전부에 대해
  A안: 영상 전체 1회 예측
  B안: 움직임 구간 검출(2초 필터) 후 예측
두 결과를 정답과 비교해 표로 출력합니다.

실행: ai_service/ 폴더에서
    python -m scripts.evaluate_segments --splits S03
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from services.action_inference import (
    MIN_VALID_FRAMES,
    apply_threshold,
    predict_sequence,
    predict_track,
)
from services.model_loader import load_artifacts
from services.pose_pipeline import extract_tracks


# ① 정답 매핑과 영상 위치
ACTION_CODES = {
    "A001": "seated_knee_extension",
    "A002": "shoulder_reach_up_down",
    "A006": "side_lying_leg_raise",
}
VIDEO_ROOT = Path(__file__).resolve().parents[2] / "test_videos" / "videos"


# ② 영상 1개 평가
def evaluate_video(artifacts: dict, path: Path) -> dict:
    truth = ACTION_CODES[path.stem.split("_")[1]]
    video = extract_tracks(path, max_people=1)
    row = {"file": path.name, "truth": truth, "duration": video.duration_sec}

    if not video.tracks:
        row.update(whole="NO_PERSON", seg="NO_PERSON")
        return row

    track = max(video.tracks.values(), key=lambda item: item.valid_frames)

    # ②-1 A안: 영상 전체 1회
    if track.valid_frames >= MIN_VALID_FRAMES:
        label, confidence, _ = predict_sequence(artifacts, track.features, track.frame_ids)
        row["whole"] = apply_threshold(label, confidence)
        row["whole_conf"] = confidence
    else:
        row["whole"] = "TOO_FEW"

    # ②-2 B안: 구간 검출
    result = predict_track(artifacts, track)
    if result is None:
        row["seg"] = "NO_SEGMENT"
    else:
        row["seg"] = result["action_label"]
        row["seg_conf"] = result["confidence"]
        row["seg_count"] = result["segment_count"]
        row["discarded"] = result["discarded_segments"]
        row["motion"] = [s["motion_sec"] for s in result["segments"]]
    return row


# ③ 전체 실행과 요약
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--splits", nargs="+", default=["S02", "S03"])
    args = parser.parse_args()

    artifacts = load_artifacts()
    rows = []
    started = time.perf_counter()

    for split in args.splits:
        for path in sorted((VIDEO_ROOT / split).glob("*.mp4")):
            row = evaluate_video(artifacts, path)
            rows.append(row)
            whole_ok = "O" if row["whole"] == row["truth"] else "X"
            seg_ok = "O" if row["seg"] == row["truth"] else "X"
            print(
                f"{row['file']:<20} {row['duration']:5.1f}s | "
                f"A {whole_ok} {row['whole']:<23} {row.get('whole_conf', 0):.2f} | "
                f"B {seg_ok} {row['seg']:<23} {row.get('seg_conf', 0):.2f} "
                f"구간 {row.get('seg_count', 0)} 버림 {row.get('discarded', 0)} "
                f"움직임 {row.get('motion', [])}"
            )

    total = len(rows)
    whole_correct = sum(row["whole"] == row["truth"] for row in rows)
    seg_correct = sum(row["seg"] == row["truth"] for row in rows)
    print("-" * 60)
    print(f"영상 {total}개, 소요 {time.perf_counter() - started:.0f}초")
    print(f"A안(영상 전체) 정답: {whole_correct}/{total}")
    print(f"B안(구간 검출) 정답: {seg_correct}/{total}")


if __name__ == "__main__":
    main()