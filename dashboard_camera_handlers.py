"""Camera-related dashboard handlers."""

from __future__ import annotations

from datetime import datetime
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse


def parse_camera_index(path: str, camera_count: int) -> int:
    parsed_path = urlparse(path).path
    camera_index = int(parsed_path.rstrip("/").split("/")[-1])
    if camera_index < 0 or camera_index >= camera_count:
        raise ValueError(f"camera index out of range: {camera_index}")
    return camera_index


def camera_url_for_proxy(raw_url: str, in_docker: bool, camera_index: int | None = None) -> str:
    parsed = urlparse(raw_url)
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "::1"):
        if in_docker and camera_index is not None:
            return f"{parsed.scheme}://camera{camera_index + 1}:8080"
        netloc = "host.docker.internal"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()
    return raw_url


def handle_camera_snapshot(handler, cameras, in_docker, parse_index, request_cls, urlopen_fn):
    if not handler.path.startswith("/camera_snapshot/"):
        return False

    parsed = urlparse(handler.path)
    try:
        camera_index = parse_index(parsed.path)
        cam = cameras[camera_index]
        target_url = camera_url_for_proxy(cam["url"], in_docker, camera_index) + "/snapshot"
        req = request_cls(target_url)
        with urlopen_fn(req, timeout=5) as response:
            payload = response.read()

        query = parse_qs(parsed.query)
        should_download = query.get("download", ["0"])[0] in ("1", "true", "yes")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if (c.isalnum() and c.isascii()) else "_" for c in cam["name"]).strip("_") or f"camera{camera_index+1}"
        filename = f"snapshot_{safe_name}_{timestamp}.jpg"

        handler.send_response(200)
        handler.send_header("Content-type", "image/jpeg")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        if should_download:
            handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError):
        handler.send_response(503)
        handler.end_headers()
        return True
    except Exception:
        handler.send_response(500)
        handler.end_headers()
        return True


def _proxy_camera_post(
    handler,
    camera_path,
    ok_status,
    cameras,
    in_docker,
    parse_index,
    request_cls,
    urlopen_fn,
):
    try:
        camera_index = parse_index(handler.path)
        cam = cameras[camera_index]
        target_url = camera_url_for_proxy(cam["url"], in_docker, camera_index) + camera_path
        req = request_cls(target_url, method="POST")
        with urlopen_fn(req, timeout=5) as response:
            payload = response.read()

        handler.send_response(ok_status)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError) as e:
        handler.send_response(503)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True


def _read_handler_body(handler) -> bytes:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except Exception:
        length = 0
    return handler.rfile.read(length) if length > 0 else b""


def _proxy_camera_json(
    handler,
    *,
    camera_index: int,
    target_path: str,
    method: str,
    cameras,
    in_docker,
    request_cls,
    urlopen_fn,
    body: bytes = b"",
    timeout: float = 10,
):
    cam = cameras[camera_index]
    target_url = camera_url_for_proxy(cam["url"], in_docker, camera_index) + target_path
    headers = {"Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"
    req = request_cls(target_url, data=body if body else None, headers=headers, method=method)
    with urlopen_fn(req, timeout=timeout) as response:
        payload = response.read()
    return payload


def proxy_camera_recording_request(
    handler,
    *,
    target_path: str,
    method: str,
    cameras,
    in_docker,
    parse_index,
    request_cls,
    urlopen_fn,
    timeout: float = 10,
):
    parsed = urlparse(handler.path)
    try:
        camera_index = parse_index(parsed.path)
        body = _read_handler_body(handler) if method.upper() != "GET" else b""
        payload = _proxy_camera_json(
            handler,
            camera_index=camera_index,
            target_path=target_path,
            method=method.upper(),
            cameras=cameras,
            in_docker=in_docker,
            request_cls=request_cls,
            urlopen_fn=urlopen_fn,
            body=body,
            timeout=timeout,
        )
        handler.send_response(200)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError) as e:
        handler.send_response(503)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True
    except HTTPError as e:
        payload = e.read() if hasattr(e, "read") else b""
        handler.send_response(e.code)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(payload or json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True
    except Exception as e:
        handler.send_response(500)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True


def handle_camera_mask(handler, *args):
    if not handler.path.startswith("/camera_mask/"):
        return False
    return _proxy_camera_post(handler, "/update_mask", 200, *args)


def handle_camera_mask_confirm(handler, *args):
    if not handler.path.startswith("/camera_mask_confirm/"):
        return False
    return _proxy_camera_post(handler, "/confirm_mask_update", 200, *args)


def handle_camera_mask_discard(handler, *args):
    if not handler.path.startswith("/camera_mask_discard/"):
        return False
    return _proxy_camera_post(handler, "/discard_mask_update", 200, *args)


def handle_camera_restart(handler, cameras, in_docker, parse_index, request_cls, urlopen_fn):
    if not handler.path.startswith("/camera_restart/"):
        return False

    try:
        camera_index = parse_index(handler.path)
        cam = cameras[camera_index]
        target_url = camera_url_for_proxy(cam["url"], in_docker, camera_index) + "/restart"
        req = request_cls(target_url, method="POST")
        with urlopen_fn(req, timeout=5) as response:
            payload = response.read()

        handler.send_response(202)
        handler.send_header("Content-type", "application/json")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except (ValueError, URLError, TimeoutError) as e:
        handler.send_response(503)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True
    except Exception as e:
        handler.send_response(500)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
        return True


def handle_camera_mask_image(handler, cameras, in_docker, parse_index, request_cls, urlopen_fn):
    if not handler.path.startswith("/camera_mask_image/"):
        return False

    parsed = urlparse(handler.path)
    try:
        camera_index = parse_index(parsed.path)
        cam = cameras[camera_index]
        target_url = camera_url_for_proxy(cam["url"], in_docker, camera_index) + "/mask"
        if parsed.query:
            target_url += "?" + parsed.query
        req = request_cls(target_url)
        with urlopen_fn(req, timeout=5) as response:
            payload = response.read()

        handler.send_response(200)
        handler.send_header("Content-type", "image/png")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler.wfile.write(payload)
        return True
    except HTTPError as e:
        handler.send_response(404 if e.code == 404 else 503)
        handler.end_headers()
        return True
    except (ValueError, URLError, TimeoutError):
        handler.send_response(503)
        handler.end_headers()
        return True
    except Exception:
        handler.send_response(500)
        handler.end_headers()
        return True


def handle_camera_settings_current(handler, cameras, camera_stats_target, request_cls, urlopen_fn):
    if handler.path != "/camera_settings/current":
        return False

    results = []
    first_settings = {}

    for camera_index, cam in enumerate(cameras):
        target_url = camera_stats_target(camera_index)
        try:
            req = request_cls(target_url, headers={"Accept": "application/json"})
            with urlopen_fn(req, timeout=5) as response:
                payload = response.read()
            data = json.loads(payload.decode("utf-8")) if payload else {}
            settings = data.get("settings", {}) if isinstance(data, dict) else {}
            if not first_settings and isinstance(settings, dict) and settings:
                first_settings = settings
            results.append({
                "camera": cam["name"],
                "success": True,
                "settings": settings,
            })
        except Exception as e:
            results.append({
                "camera": cam["name"],
                "success": False,
                "error": str(e),
            })

    ok_count = sum(1 for item in results if item.get("success"))
    handler.send_response(200)
    handler.send_header("Content-type", "application/json")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.end_headers()
    handler.wfile.write(
        json.dumps(
            {
                "success": ok_count > 0,
                "settings": first_settings,
                "results": results,
                "ok_count": ok_count,
                "total": len(cameras),
            }
        ).encode("utf-8")
    )
    return True


def handle_camera_settings_apply_all(handler, cameras, camera_apply_settings_target, request_cls, urlopen_fn):
    if handler.path != "/camera_settings/apply_all":
        return False

    try:
        length = int(handler.headers.get("Content-Length", "0"))
        raw_body = handler.rfile.read(length)
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        if not isinstance(payload, dict):
            raise ValueError("payload must be object")
    except Exception as e:
        handler.send_response(400)
        handler.send_header("Content-type", "application/json")
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "error": f"invalid payload: {e}"}).encode("utf-8"))
        return True

    results = []
    applied_count = 0
    request_body = json.dumps(payload).encode("utf-8")
    for camera_index, cam in enumerate(cameras):
        target_url = camera_apply_settings_target(camera_index)
        try:
            req = request_cls(
                target_url,
                data=request_body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen_fn(req, timeout=8) as response:
                resp_payload = response.read()
            data = json.loads(resp_payload.decode("utf-8")) if resp_payload else {}
            success = bool(data.get("success", False))
            if success:
                applied_count += 1
            results.append({
                "camera": cam["name"],
                "success": success,
                "response": data,
            })
        except Exception as e:
            results.append({
                "camera": cam["name"],
                "success": False,
                "error": str(e),
            })

    handler.send_response(200)
    handler.send_header("Content-type", "application/json")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.end_headers()
    handler.wfile.write(
        json.dumps(
            {
                "success": applied_count > 0,
                "applied_count": applied_count,
                "total": len(cameras),
                "results": results,
            }
        ).encode("utf-8")
    )
    return True
