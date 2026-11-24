from pathlib import Path

import requests
from django.conf import settings

PREDICT_PATH = "/api/v1/predict/"


class AIServiceError(Exception):
    """FastAPI 호출 실패. 메시지는 그대로 사용자에게 보여줄 수 있는 문장이다."""


def _error_detail(response):
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return str(detail or response.text)[:300]


def request_prediction(job):
    url = f"{settings.FASTAPI_BASE_URL.rstrip('/')}{PREDICT_PATH}"
    timeout = (settings.FASTAPI_CONNECT_TIMEOUT_SEC, settings.FASTAPI_READ_TIMEOUT_SEC)
    filename = Path(job.video_file.name).name

    try:
        with job.video_file.open("rb") as video:
            response = requests.post(
                url,
                files={"file": (filename, video, "application/octet-stream")},
                data={"max_people": settings.ANALYSIS_MAX_PEOPLE},
                timeout=timeout,
            )
    except FileNotFoundError as error:
        raise AIServiceError("업로드된 영상 파일을 찾을 수 없습니다.") from error
    except requests.ConnectionError as error:
        raise AIServiceError("AI 서버에 연결할 수 없습니다.") from error
    except requests.Timeout as error:
        raise AIServiceError("AI 분석 시간이 초과되었습니다.") from error
    except requests.RequestException as error:
        raise AIServiceError(f"AI 서버 요청 중 오류가 발생했습니다: {error}") from error

    if response.status_code == 200:
        try:
            return response.json()
        except ValueError as error:
            raise AIServiceError("AI 서버 응답을 해석할 수 없습니다.") from error

    detail = _error_detail(response)
    if response.status_code == 400:
        raise AIServiceError(f"영상을 분석할 수 없습니다: {detail}")
    if response.status_code == 503:
        raise AIServiceError("AI 모델이 준비되지 않았습니다.")
    raise AIServiceError(f"AI 서버 오류 (HTTP {response.status_code}): {detail}")