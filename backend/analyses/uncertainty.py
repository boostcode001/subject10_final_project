from django.conf import settings

from .models import ActionLabel

UNKNOWN_LABEL = "UNKNOWN"

LEVEL_OK = "ok"
LEVEL_UNCERTAIN = "uncertain"
LEVEL_UNKNOWN = "unknown"

LEVEL_TEXT = {
    LEVEL_OK: "정상",
    LEVEL_UNCERTAIN: "판단 불확실",
    LEVEL_UNKNOWN: "판정 불가",
}

DEFAULT_REASON = "인공지능이 이 동작을 확실하게 판단하지 못했습니다. 다시 촬영해 보세요."


def label_display(label):
    try:
        return ActionLabel(label).label
    except ValueError:
        return label


def _percent(value):
    return f"{value * 100:.0f}%"


def _top_candidates(probabilities, limit=2):
    if not probabilities:
        return []
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    return [
        {"label": label, "display": label_display(label), "probability": round(prob, 4)}
        for label, prob in ranked[:limit]
    ]


def _level(person):
    if person.action_label == UNKNOWN_LABEL:
        return LEVEL_UNKNOWN
    if person.confidence < settings.ANALYSIS_UNCERTAIN_CONFIDENCE:
        return LEVEL_UNCERTAIN
    return LEVEL_OK


def _reasons(person, segments, best, candidates):
    reasons = []

    keypoint_conf = person.mean_keypoint_conf
    if keypoint_conf is not None and keypoint_conf < settings.ANALYSIS_MIN_KEYPOINT_CONF:
        reasons.append(
            f"몸의 관절이 또렷하게 보이지 않았습니다(인식 정도 {_percent(keypoint_conf)}). "
            "밝은 곳에서 머리부터 발끝까지 화면에 들어오게 촬영하면 더 정확해집니다."
        )

    frame_ratio = person.valid_frame_ratio
    if frame_ratio is not None and frame_ratio < settings.ANALYSIS_MIN_VALID_FRAME_RATIO:
        reasons.append(
            f"영상의 {_percent(frame_ratio)}에서만 사람을 찾을 수 있었습니다. "
            "몸이 화면 밖으로 나가거나 가려지지 않게 해 주세요."
        )

    if best is not None:
        duration = best.end_sec - best.start_sec
        if duration < settings.ANALYSIS_MIN_SEGMENT_SEC:
            reasons.append(
                f"동작이 {duration:.1f}초 동안만 감지되어 인공지능이 판단하기에 짧았습니다. "
                "동작을 3초 이상 천천히 해 주세요."
            )

    labels = []
    for segment in segments:
        if segment.action_label != UNKNOWN_LABEL and segment.action_label not in labels:
            labels.append(segment.action_label)
    if len(labels) == 2:
        reasons.append(
            f"영상 앞부분은 '{label_display(labels[0])}', 뒷부분은 "
            f"'{label_display(labels[1])}'로 보여 하나로 판단하기 어려웠습니다. "
            "한 번에 한 가지 동작만 해 주세요."
        )
    elif len(labels) > 2:
        names = ", ".join(f"'{label_display(label)}'" for label in labels)
        reasons.append(
            f"영상 안에서 여러 동작({names})이 감지되어 하나로 판단하기 어려웠습니다. "
            "한 번에 한 가지 동작만 해 주세요."
        )

    if len(candidates) >= 2:
        first, second = candidates[0], candidates[1]
        if first["probability"] - second["probability"] < settings.ANALYSIS_MIN_TOP2_MARGIN:
            reasons.append(
                f"'{first['display']}'({_percent(first['probability'])})와 "
                f"'{second['display']}'({_percent(second['probability'])})가 비슷하게 나와 "
                "어느 쪽인지 확실하지 않습니다."
            )

    return reasons or [DEFAULT_REASON]


def evaluate_person(person):
    segments = sorted(person.segments.all(), key=lambda segment: segment.segment_no)
    best = max(segments, key=lambda segment: segment.confidence, default=None)
    candidates = _top_candidates(best.probabilities if best else None)

    level = _level(person)
    reasons = [] if level == LEVEL_OK else _reasons(person, segments, best, candidates)

    return {
        "level": level,
        "level_text": LEVEL_TEXT[level],
        "reasons": reasons,
        "top_candidates": candidates,
    }