from __future__ import annotations

import base64
import json
import re
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse


_VIEW_ID_RE = re.compile(r"(v\d{3}_yaw-?\d+(?:\.\d+)?_pitch-?\d+(?:\.\d+)?)")


class RuntimeCaptureTimeout(RuntimeError):
    """Raised when a runtime Laya capture job does not return all expected views."""


@dataclass
class _RuntimeCaptureState:
    condition: threading.Condition = field(default_factory=threading.Condition)
    command: dict[str, Any] | None = None
    active_nonce: str = ""
    output_dir: Path | None = None
    expected_order: list[str] = field(default_factory=list)
    expected: set[str] = field(default_factory=set)
    received: set[str] = field(default_factory=set)
    files_by_view: dict[str, str] = field(default_factory=dict)
    logs: list[dict[str, Any]] = field(default_factory=list)
    browser_score: dict[str, Any] | None = None


class RuntimeCaptureBridge:
    """Reusable HTTP bridge for Laya runtime RenderTexture capture.

    Laya's ``MaterialFitCapture`` component polls ``/material-fit/capture-command``
    and posts rendered images back to this bridge. PNG and raw RGBA payloads are
    both accepted so optimization runs can skip browser-side PNG encoding when
    the scoring path can consume raw pixels directly.
    """

    def __init__(self, *, host: str = "127.0.0.1", port: int = 8787) -> None:
        self.host = host
        self.port = int(port)
        self._state = _RuntimeCaptureState()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("RuntimeCaptureBridge is not started")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "RuntimeCaptureBridge":
        if self._server is not None:
            return self
        self._server = _make_server(self.host, self.port, self._state)
        self._thread = threading.Thread(target=self._server.serve_forever, name="runtime-laya-capture", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is None:
            return
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=2.0)

    def __enter__(self) -> "RuntimeCaptureBridge":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()

    def capture(self, command: dict[str, Any], *, output_dir: str | Path, timeout_s: float = 90.0) -> dict[str, Any]:
        self.start()
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        payload = dict(command)
        nonce = str(payload.get("nonce") or f"runtime-capture-{time.time_ns()}")
        payload["enabled"] = True
        payload["nonce"] = nonce
        payload["server_base_url"] = self.base_url
        payload["post_url"] = f"{self.base_url}/material-fit/capture-result"
        payload["output_dir"] = str(output_path)
        payload = _with_reference_image_urls(payload, self.base_url)
        expected_order = _expected_view_ids(payload)
        expected = set(expected_order)

        with self._state.condition:
            self._state.command = payload
            self._state.active_nonce = nonce
            self._state.output_dir = output_path
            self._state.expected_order = expected_order
            self._state.expected = expected
            self._state.received = set()
            self._state.files_by_view = {}
            self._state.logs = []
            self._state.browser_score = None
            self._state.condition.notify_all()

            deadline = time.monotonic() + float(timeout_s)
            while not expected.issubset(self._state.received):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    missing = sorted(expected - self._state.received)
                    self._state.command = None
                    raise RuntimeCaptureTimeout(f"Timed out waiting for Laya runtime capture views: {missing}")
                self._state.condition.wait(timeout=min(0.2, remaining))

            screenshots = [
                self._state.files_by_view[view_id]
                for view_id in expected_order
                if view_id in self._state.files_by_view
            ]
            report = {
                "nonce": nonce,
                "expected": expected_order,
                "received": sorted(self._state.received),
                "files": screenshots,
                "logs": list(self._state.logs),
                "browser_score": copy_json(self._state.browser_score),
            }
            browser_score = copy_json(self._state.browser_score)
            self._state.command = None

        return {
            "status": "ok",
            "command": payload,
            "output_dir": str(output_path),
            "screenshots": screenshots,
            "candidate_overrides": _build_candidate_overrides(screenshots),
            "report": report,
            **({"browser_score": browser_score} if isinstance(browser_score, dict) else {}),
        }


def _make_server(host: str, port: int, state: _RuntimeCaptureState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/material-fit/capture-command":
                query = parse_qs(parsed.query)
                last_nonce = query.get("last_nonce", [""])[0]
                with state.condition:
                    if state.command is not None and last_nonce != state.active_nonce:
                        payload = dict(state.command)
                    else:
                        payload = {"enabled": False, "nonce": last_nonce or state.active_nonce}
                self._write_json(payload)
                return
            if parsed.path == "/material-fit/status":
                with state.condition:
                    payload = {
                        "active_nonce": state.active_nonce,
                        "expected": state.expected_order,
                        "received": sorted(state.received),
                        "logs": state.logs[-20:],
                        "browser_score": state.browser_score,
                    }
                self._write_json(payload)
                return
            if parsed.path == "/material-fit/reference-image":
                self._handle_reference_image(parsed)
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/material-fit/capture-raw-rgba":
                    self._handle_capture_raw_rgba(parsed)
                    return
                payload = self._read_json_body()
                if parsed.path == "/material-fit/capture-result":
                    self._handle_capture_result(payload)
                    return
                if parsed.path == "/material-fit/capture-score":
                    self._handle_capture_score(payload)
                    return
                if parsed.path == "/material-fit/capture-log":
                    with state.condition:
                        state.logs.append(payload)
                        state.condition.notify_all()
                    self._write_json({"ok": True})
                    return
            except Exception as exc:  # noqa: BLE001
                self._write_json({"ok": False, "error": str(exc)}, status=500)
                return
            self.send_error(404)

        def _handle_capture_result(self, payload: dict[str, Any]) -> None:
            raw_nonce = str(payload.get("nonce") or "")
            raw_view_id = str(payload.get("view_id") or "view")
            view_id = _safe_name(raw_view_id)
            file_name = _safe_name(str(payload.get("file_name") or f"{view_id}.png"))
            if not file_name.lower().endswith(".png"):
                file_name += ".png"
            image_bytes = base64.b64decode(str(payload.get("png_base64") or ""))

            with state.condition:
                if raw_nonce != state.active_nonce:
                    self._write_json({"ok": False, "error": "stale capture nonce"}, status=409)
                    return
                if state.output_dir is None:
                    self._write_json({"ok": False, "error": "no active output directory"}, status=409)
                    return
                output_path = state.output_dir / file_name
                output_path.write_bytes(image_bytes)
                sidecar = dict(payload)
                sidecar.pop("png_base64", None)
                sidecar["saved_path"] = str(output_path)
                (state.output_dir / f"{output_path.stem}.json").write_text(
                    json.dumps(sidecar, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                state.received.add(view_id)
                state.files_by_view[view_id] = str(output_path)
                state.condition.notify_all()
                self._write_json({"ok": True, "path": str(output_path), "received": sorted(state.received)})

        def _handle_capture_score(self, payload: dict[str, Any]) -> None:
            raw_nonce = str(payload.get("nonce") or "")
            browser_score = payload.get("browser_score")
            if not isinstance(browser_score, dict):
                self._write_json({"ok": False, "error": "missing browser_score"}, status=400)
                return
            with state.condition:
                if raw_nonce != state.active_nonce:
                    self._write_json({"ok": False, "error": "stale capture nonce"}, status=409)
                    return
                if state.output_dir is None:
                    self._write_json({"ok": False, "error": "no active output directory"}, status=409)
                    return
                score_payload = dict(browser_score)
                score_payload.setdefault("enabled", True)
                state.browser_score = score_payload
                (state.output_dir / "browser_score.json").write_text(
                    json.dumps(score_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                state.received.update(state.expected)
                state.condition.notify_all()
                self._write_json({"ok": True, "received": sorted(state.received), "browser_score": score_payload})

        def _handle_capture_raw_rgba(self, parsed: Any) -> None:
            query = parse_qs(parsed.query)
            raw_nonce = str(_first_query_value(query, "nonce") or "")
            raw_view_id = str(_first_query_value(query, "view_id") or "view")
            view_id = _safe_name(raw_view_id)
            file_name = _safe_name(str(_first_query_value(query, "file_name") or f"{view_id}.rgba"))
            if not file_name.lower().endswith(".rgba"):
                file_name += ".rgba"
            width = int(_first_query_value(query, "width") or "0")
            height = int(_first_query_value(query, "height") or "0")
            if width <= 0 or height <= 0:
                self._write_json({"ok": False, "error": "invalid raw RGBA dimensions"}, status=400)
                return
            length = int(self.headers.get("Content-Length") or "0")
            image_bytes = self.rfile.read(length)
            expected_len = width * height * 4
            if len(image_bytes) != expected_len:
                self._write_json(
                    {"ok": False, "error": f"raw RGBA byte count mismatch: got {len(image_bytes)}, expected {expected_len}"},
                    status=400,
                )
                return

            with state.condition:
                if raw_nonce != state.active_nonce:
                    self._write_json({"ok": False, "error": "stale capture nonce"}, status=409)
                    return
                if state.output_dir is None:
                    self._write_json({"ok": False, "error": "no active output directory"}, status=409)
                    return
                output_path = state.output_dir / file_name
                output_path.write_bytes(image_bytes)
                sidecar = {
                    "format": "raw_rgba",
                    "nonce": raw_nonce,
                    "view_id": view_id,
                    "file_name": file_name,
                    "width": width,
                    "height": height,
                    "saved_path": str(output_path),
                }
                for key, values in query.items():
                    if key not in sidecar and values:
                        sidecar[key] = values[0]
                output_path.with_suffix(output_path.suffix + ".json").write_text(
                    json.dumps(sidecar, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                state.received.add(view_id)
                state.files_by_view[view_id] = str(output_path)
                state.condition.notify_all()
                self._write_json({"ok": True, "path": str(output_path), "received": sorted(state.received)})

        def _handle_reference_image(self, parsed: Any) -> None:
            query = parse_qs(parsed.query)
            path_text = _first_query_value(query, "path")
            if not path_text:
                self._write_json({"ok": False, "error": "missing reference image path"}, status=400)
                return
            path = Path(path_text)
            if not path.exists() or not path.is_file():
                self._write_json({"ok": False, "error": f"reference image not found: {path}"}, status=404)
                return
            data = path.read_bytes()
            content_type = "image/png" if path.suffix.lower() == ".png" else "application/octet-stream"
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8")) if raw else {}

        def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ThreadingHTTPServer((host, int(port)), Handler)


def _expected_view_ids(command: dict[str, Any]) -> list[str]:
    views = command.get("views")
    if not isinstance(views, list) or not views:
        return ["view_000"]
    ids: list[str] = []
    for index, raw_view in enumerate(views):
        view = raw_view if isinstance(raw_view, dict) else {}
        view_id = str(view.get("view_id") or view.get("id") or f"view_{index:03d}")
        ids.append(_safe_name(view_id))
    return ids


def _with_reference_image_urls(command: dict[str, Any], base_url: str) -> dict[str, Any]:
    browser_score = command.get("browser_score")
    if not isinstance(browser_score, dict):
        return command
    references = browser_score.get("reference_images")
    if not isinstance(references, list):
        return command
    command = dict(command)
    score_cfg = dict(browser_score)
    rewritten: list[Any] = []
    for raw in references:
        if not isinstance(raw, dict):
            rewritten.append(raw)
            continue
        entry = dict(raw)
        if not entry.get("url") and entry.get("path"):
            entry["url"] = f"{base_url}/material-fit/reference-image?path={quote(str(entry['path']), safe='')}"
        rewritten.append(entry)
    score_cfg["reference_images"] = rewritten
    command["browser_score"] = score_cfg
    return command


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False)) if value is not None else None


def _safe_name(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    return "".join(ch if ch in allowed else "_" for ch in value)[:160] or "capture.png"


def _first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def _build_candidate_overrides(files: list[str | Path]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for file_path in files:
        path = Path(file_path)
        value = str(path)
        overrides[path.name] = value
        overrides[path.stem] = value
        match = _VIEW_ID_RE.search(path.stem)
        if match:
            overrides[match.group(1)] = value
    return overrides
