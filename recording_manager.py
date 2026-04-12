"""
recording_manager.py
録画ジョブ管理・ffmpegサブプロセス制御。

detection_state.state を通じてグローバル状態にアクセスする。
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from detection_state import state, _storage_camera_name


def _recordings_dir() -> Optional[Path]:  # pragma: no cover
    if state.current_output_dir is None or not state.current_camera_name:
        return None
    return Path(state.current_output_dir) / "manual_recordings" / _storage_camera_name(state.current_camera_name)


def _recording_supported() -> bool:  # pragma: no cover
    return shutil.which("ffmpeg") is not None and bool(state.current_rtsp_url)


def _format_recording_dt(value: Optional[datetime]) -> str:  # pragma: no cover
    if value is None:
        return ""
    try:
        return value.astimezone().isoformat(timespec="seconds")
    except Exception:
        return value.isoformat(timespec="seconds")


def _parse_recording_start_at(value) -> datetime:  # pragma: no cover
    text = str(value or "").strip()
    if not text:
        return datetime.now().astimezone()
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.astimezone()
    return dt.astimezone()


def _recording_snapshot_locked() -> dict:  # pragma: no cover
    now = datetime.now().astimezone()
    payload = {
        "supported": _recording_supported(),
        "state": "idle",
        "camera": state.current_camera_name or state.camera_name,
        "job_id": "",
        "start_at": "",
        "scheduled_at": "",
        "started_at": "",
        "ended_at": "",
        "duration_sec": 0,
        "remaining_sec": 0,
        "output_path": "",
        "error": "",
    }
    job = state.current_recording_job
    if not job:
        return payload
    payload.update(
        {
            "state": job.get("state", "idle"),
            "job_id": job.get("job_id", ""),
            "start_at": _format_recording_dt(job.get("start_at")),
            "scheduled_at": _format_recording_dt(job.get("scheduled_at")),
            "started_at": _format_recording_dt(job.get("started_at")),
            "ended_at": _format_recording_dt(job.get("ended_at")),
            "duration_sec": int(job.get("duration_sec", 0) or 0),
            "output_path": str(job.get("output_path") or ""),
            "error": str(job.get("error") or ""),
        }
    )
    snapshot_state = payload["state"]
    start_at = job.get("start_at")
    duration_sec = max(0, int(job.get("duration_sec", 0) or 0))
    if snapshot_state == "scheduled" and start_at is not None:
        payload["remaining_sec"] = max(0, int((start_at - now).total_seconds()))
    elif snapshot_state == "recording":
        started_at = job.get("started_at") or now
        elapsed = max(0.0, (now - started_at).total_seconds())
        payload["remaining_sec"] = max(0, int(duration_sec - elapsed))
    return payload


def _set_recording_job_state(job: dict, job_state: str, *, error: str = "") -> None:  # pragma: no cover
    with state.current_recording_lock:
        if state.current_recording_job is not job:
            return
        job["state"] = job_state
        if error:
            job["error"] = error
        if job_state == "scheduled":
            job["scheduled_at"] = datetime.now().astimezone()
        elif job_state == "recording":
            job["started_at"] = datetime.now().astimezone()
        elif job_state in ("completed", "failed", "stopped"):
            job["ended_at"] = datetime.now().astimezone()
            job["process"] = None


def _stop_recording_process(job: dict, *, reason: str = "stopped") -> bool:  # pragma: no cover
    proc = job.get("process")
    stop_event = job.get("stop_event")
    if stop_event is not None:
        stop_event.set()
    if proc is None:
        return False
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
    except Exception:
        pass
    _set_recording_job_state(job, "stopped", error=reason)
    return True


def _recording_worker(job: dict) -> None:  # pragma: no cover
    stop_event = job["stop_event"]
    try:
        wait_seconds = max(0.0, (job["start_at"] - datetime.now().astimezone()).total_seconds())
        if wait_seconds > 0 and stop_event.wait(wait_seconds):
            _set_recording_job_state(job, "stopped", error="cancelled before start")
            return
        if stop_event.is_set():
            _set_recording_job_state(job, "stopped", error="cancelled before start")
            return
        recordings_dir = _recordings_dir()
        if recordings_dir is None:
            _set_recording_job_state(job, "failed", error="output directory not ready")
            return
        recordings_dir.mkdir(parents=True, exist_ok=True)
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            _set_recording_job_state(job, "failed", error="ffmpeg not found")
            return
        duration_sec = int(job["duration_sec"])
        output_path = Path(job["output_path"])
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            state.current_rtsp_url,
            "-map",
            "0:v:0",
            "-an",
            "-t",
            str(duration_sec),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            "-y",
            str(output_path),
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        with state.current_recording_lock:
            if state.current_recording_job is not job:
                try:
                    proc.terminate()
                except Exception:
                    pass
                return
            job["process"] = proc
        _set_recording_job_state(job, "recording")
        _, stderr = proc.communicate()
        if stop_event.is_set():
            _set_recording_job_state(job, "stopped", error="stopped")
            return
        if proc.returncode == 0:
            thumb_path = output_path.with_suffix(".jpg")
            thumb_cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                "1",
                "-i",
                str(output_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(thumb_path),
            ]
            try:
                thumb_proc = subprocess.run(
                    thumb_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False
                )
                if thumb_proc.returncode != 0 and thumb_path.exists():
                    thumb_path.unlink(missing_ok=True)
            except Exception:
                if thumb_path.exists():
                    thumb_path.unlink(missing_ok=True)
            _set_recording_job_state(job, "completed")
            return
        err_text = stderr.decode("utf-8", errors="ignore").strip()
        _set_recording_job_state(
            job, "failed", error=err_text or f"ffmpeg exited with code {proc.returncode}"
        )
    except Exception as e:
        _set_recording_job_state(job, "failed", error=str(e))
