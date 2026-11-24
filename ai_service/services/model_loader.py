"""
model_loader.py
팀 모델(joblib)과 학습 정보(JSON)를 읽고, 추론 전에 입력 규격이 맞는지 검사합니다.
FastAPI main.py가 서버 시작 시 load_artifacts()를 한 번 호출합니다.
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib

from src.sequence_utils import sequence_feature_names


# ① 경로 설정
AI_SERVICE_DIR = Path(__file__).resolve().parents[1]
MODELS_DIR = AI_SERVICE_DIR / "models"

MODEL_FILE = "rf_action_team.joblib"
COLUMNS_FILE = "rf_feature_columns.json"
INFO_FILE = "rf_training_info.json"

FRAME_FEATURE_COUNT = 38


# ② JSON 읽기 도우미
def _read_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"파일이 없습니다: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


# ③ 모델·학습 정보 불러오기 + 검사 4개
def load_artifacts(models_dir: Path = MODELS_DIR) -> dict:
    model_path = models_dir / MODEL_FILE
    if not model_path.exists():
        raise FileNotFoundError(f"모델 파일이 없습니다: {model_path}")

    model = joblib.load(model_path)
    columns = _read_json(models_dir / COLUMNS_FILE)
    info = _read_json(models_dir / INFO_FILE)

    classes = list(info["classes"])
    sequence_steps = int(info["sequence_steps"])
    feature_count = int(info["feature_count"])

    # 검사 1: 모델이 아는 동작과 학습 정보의 동작이 같은가
    model_classes = [str(c) for c in model.classes_]
    if sorted(model_classes) != sorted(classes):
        raise RuntimeError(
            f"[검사1 실패] 동작 목록 불일치 model={model_classes} info={classes}"
        )

    # 검사 2: 입력 개수가 모두 같은가
    if not (model.n_features_in_ == feature_count == len(columns)):
        raise RuntimeError(
            f"[검사2 실패] 입력 개수 불일치 model={model.n_features_in_} "
            f"info={feature_count} columns={len(columns)}"
        )

    # 검사 3: Step 수 × 38 = 입력 개수인가
    if sequence_steps * FRAME_FEATURE_COUNT != feature_count:
        raise RuntimeError(
            f"[검사3 실패] {sequence_steps} × {FRAME_FEATURE_COUNT} != {feature_count}"
        )

    # 검사 4: 내 코드가 만드는 컬럼 이름·순서가 학습 때와 같은가
    my_columns = sequence_feature_names(sequence_steps)
    if my_columns != columns:
        first_diff = next(
            (i for i, (a, b) in enumerate(zip(my_columns, columns)) if a != b),
            min(len(my_columns), len(columns)),
        )
        raise RuntimeError(
            f"[검사4 실패] 컬럼 이름·순서 불일치, 첫 차이 위치={first_diff}"
        )

    return {
        "model": model,
        "columns": columns,
        "classes": model_classes,
        "sequence_steps": sequence_steps,
        "feature_count": feature_count,
    }


# ④ 터미널에서 직접 실행할 때만 결과 출력
if __name__ == "__main__":
    artifacts = load_artifacts()
    print("검사 1~4 PASS")
    print("classes        :", artifacts["classes"])
    print("sequence_steps :", artifacts["sequence_steps"])
    print("feature_count  :", artifacts["feature_count"])