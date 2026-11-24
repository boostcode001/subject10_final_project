import os
import tempfile
import time

import cv2
import numpy as np
import redis
from django.conf import settings
from django.core.files import File

MIN_FRAMES = 30
READ_FAIL_LIMIT = 30
JPEG_QUALITY = 90
STOP_CHECK_INTERVAL_SEC = 0.3


class CameraError(Exception):
    """카메라 수집 실패. 메시지는 그대로 사용자에게 보여줄 수 있는 문장이다."""


def _redis():
    return redis.Redis.from_url(settings.REDIS_URL)


def _stop_key(job_id):
    return f"camera:stop:{job_id}"


def request_stop(job_id):
    _redis().set(_stop_key(job_id), "1", ex=settings.CAMERA_MAX_SECONDS + 60)


def _clear_stop(job_id):
    try:
        _redis().delete(_stop_key(job_id))
    except redis.RedisError:
        pass


def _stop_requested(client, job_id):
    try:
        return bool(client.exists(_stop_key(job_id)))
    except redis.RedisError:
        return False


def get_camera_url(camera_key):
    url = settings.CAMERA_SOURCES.get(camera_key)
    if not url:
        raise CameraError(f"허용되지 않은 카메라입니다: {camera_key}")
    return url


def _open_camera(url):
    timeout = settings.CAMERA_TIMEOUT_MSEC
    capture = cv2.VideoCapture(
        url,
        cv2.CAP_FFMPEG,
        [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout, cv2.CAP_PROP_READ_TIMEOUT_MSEC, timeout],
    )
    if not capture.isOpened():
        capture.release()
        raise CameraError("카메라에 연결할 수 없습니다.")
    return capture


def _collect_frames(capture, job_id):
    client = _redis()
    encoded = []
    failures = 0
    last_check = 0.0
    started = time.monotonic()

    while True:
        elapsed = time.monotonic() - started
        if elapsed >= settings.CAMERA_MAX_SECONDS:
            break
        if (
            elapsed >= settings.CAMERA_MIN_SECONDS
            and elapsed - last_check >= STOP_CHECK_INTERVAL_SEC
        ):
            last_check = elapsed
            if _stop_requested(client, job_id):
                break

        ok, frame = capture.read()
        if not ok:
            failures += 1
            if failures >= READ_FAIL_LIMIT:
                raise CameraError("카메라 연결이 끊겼습니다.")
            continue
        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ok:
            encoded.append(buffer)

    return encoded, time.monotonic() - started


def _write_video(encoded, fps, path):
    first = cv2.imdecode(np.asarray(encoded[0]), cv2.IMREAD_COLOR)
    height, width = first.shape[:2]
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    try:
        for buffer in encoded:
            writer.write(cv2.imdecode(np.asarray(buffer), cv2.IMREAD_COLOR))
    finally:
        writer.release()


def capture_to_job(job):
    url = get_camera_url(job.camera_key)
    _clear_stop(job.id)

    capture = _open_camera(url)
    try:
        encoded, elapsed = _collect_frames(capture, job.id)
    finally:
        capture.release()
        _clear_stop(job.id)

    if len(encoded) < MIN_FRAMES:
        raise CameraError(f"수집된 프레임이 부족합니다 ({len(encoded)}개).")

    fps = len(encoded) / elapsed
    handle, temp_path = tempfile.mkstemp(suffix=".mp4")
    os.close(handle)
    try:
        _write_video(encoded, fps, temp_path)
        with open(temp_path, "rb") as video:
            job.video_file.save(f"webcam_job{job.id}.mp4", File(video), save=False)
    finally:
        os.remove(temp_path)

    job.capture_seconds = round(elapsed)
    return {"frames": len(encoded), "fps": round(fps, 2), "seconds": round(elapsed, 2)}