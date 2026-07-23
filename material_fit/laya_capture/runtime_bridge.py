from __future__ import annotations

import base64
import errno
import json
import re
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from .capture_quality import analyze_png_capture_quality


_VIEW_ID_RE = re.compile(r"(v\d{3}_yaw-?\d+(?:\.\d+)?_pitch-?\d+(?:\.\d+)?)")

# Chromium refuses HTTP requests to a small set of ports even when the local
# server is listening. Asking the OS for an ephemeral port can return 2049 or
# 6667 and make a healthy render fail with ``net::ERR_UNSAFE_PORT``. Dynamic
# bridges therefore bind from an explicit browser-safe range. The asset server
# uses 18080-18143, so this range is intentionally separate.
_DYNAMIC_SAFE_PORTS = range(18880, 18944)


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
    errors: list[dict[str, Any]] = field(default_factory=list)
    capture_quality: dict[str, dict[str, Any]] = field(default_factory=dict)
    browser_score: dict[str, Any] | None = None
    perceptual_scorer: Any | None = None
    perceptual_scorer_config: tuple[str, int, str, int, bool] | None = None


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
        browser_score_config = payload.get("browser_score")
        expect_browser_score = (
            isinstance(browser_score_config, dict)
            and browser_score_config.get("enabled") is True
        )

        with self._state.condition:
            self._state.command = payload
            self._state.active_nonce = nonce
            self._state.output_dir = output_path
            self._state.expected_order = expected_order
            self._state.expected = expected
            self._state.received = set()
            self._state.files_by_view = {}
            self._state.logs = []
            self._state.errors = []
            self._state.capture_quality = {}
            self._state.browser_score = None
            self._state.condition.notify_all()

            deadline = time.monotonic() + float(timeout_s)
            while (
                not expected.issubset(self._state.received)
                or (expect_browser_score and self._state.browser_score is None)
            ):
                if self._state.errors:
                    error = self._state.errors[0]
                    self._state.command = None
                    raise RuntimeError(f"Laya runtime capture failed: {error.get('reason') or error.get('error') or error}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    missing = sorted(expected - self._state.received)
                    self._state.command = None
                    score_state = "missing" if expect_browser_score and self._state.browser_score is None else "received"
                    raise RuntimeCaptureTimeout(
                        f"Timed out waiting for Laya runtime capture views: {missing}; browser_score={score_state}"
                    )
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
                "errors": list(self._state.errors),
                "capture_quality": copy_json(self._state.capture_quality),
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
        protocol_version = "HTTP/1.1"

        def handle(self) -> None:
            try:
                super().handle()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                self.close_connection = True

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._send_cors_headers()
            self.send_header("Content-Length", "0")
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
                        "errors": state.errors[-20:],
                        "capture_quality": state.capture_quality,
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
                if parsed.path == "/material-fit/capture-perceptual-score":
                    self._handle_capture_perceptual_score(parsed)
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
                        entry = dict(payload)
                        raw_nonce = str(entry.get("nonce") or "")
                        if raw_nonce and raw_nonce != state.active_nonce:
                            self._write_json(
                                {
                                    "ok": True,
                                    "ignored": True,
                                    "reason": "stale capture nonce",
                                }
                            )
                            return
                        state.logs.append(entry)
                        if str(entry.get("level") or "").lower() == "error":
                            state.errors.append(
                                {
                                    "kind": "runtime_log",
                                    "reason": str(entry.get("message") or entry.get("error") or entry),
                                    "payload": entry,
                                }
                            )
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
                quality = analyze_png_capture_quality(image_bytes, state.command.get("visual_quality_guard"))
                sidecar["capture_quality"] = quality
                state.capture_quality[view_id] = quality
                (state.output_dir / f"{output_path.stem}.json").write_text(
                    json.dumps(sidecar, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if not quality.get("ok", True):
                    error = {
                        "kind": "capture_quality",
                        "view_id": view_id,
                        "file_name": file_name,
                        "reason": quality.get("reason") or "capture_quality_failed",
                        "capture_quality": quality,
                    }
                    state.errors.append(error)
                    state.logs.append({"level": "error", **error})
                    state.condition.notify_all()
                    self._write_json({"ok": False, "error": error["reason"], "capture_quality": quality}, status=422)
                    return
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
                command = state.command if isinstance(state.command, dict) else {}
                if command.get("persist_browser_score", True) is not False:
                    (state.output_dir / "browser_score.json").write_text(
                        json.dumps(score_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                if command.get("return_images") is False:
                    state.received.update(state.expected)
                state.condition.notify_all()
                self._write_json({"ok": True, "received": sorted(state.received), "browser_score": score_payload})

        def _handle_capture_perceptual_score(self, parsed: Any) -> None:
            query = parse_qs(parsed.query)
            raw_nonce = str(_first_query_value(query, "nonce") or "")
            view_id = _safe_name(str(_first_query_value(query, "view_id") or "view"))
            width = int(_first_query_value(query, "width") or "0")
            height = int(_first_query_value(query, "height") or "0")
            if width <= 0 or height <= 0:
                self._write_json({"ok": False, "error": "invalid perceptual score dimensions"}, status=400)
                return

            with state.condition:
                if raw_nonce != state.active_nonce:
                    self._write_json({"ok": False, "error": "stale capture nonce"}, status=409)
                    return
                command = copy_json(state.command) if isinstance(state.command, dict) else {}
            score_config = command.get("browser_score")
            if not isinstance(score_config, dict):
                self._write_json({"ok": False, "error": "browser_score is not configured"}, status=409)
                return
            reference = _reference_for_view(score_config, view_id)
            reference_path = reference.get("path") if isinstance(reference, dict) else None
            if not reference_path:
                self._write_json(
                    {"ok": False, "error": f"reference path is missing for view {view_id}"},
                    status=409,
                )
                return

            length = int(self.headers.get("Content-Length") or "0")
            image_bytes = self.rfile.read(length)
            expected_len = width * height * 4
            if len(image_bytes) != expected_len:
                self._write_json(
                    {
                        "ok": False,
                        "error": f"raw RGBA length {len(image_bytes)} != expected {expected_len}",
                    },
                    status=400,
                )
                return

            scorer = _get_perceptual_scorer(state, score_config)
            result = scorer.score_rgba(
                reference_path,
                image_bytes,
                width=width,
                height=height,
            ).as_dict()
            result["view_id"] = view_id
            self._write_json({"ok": True, **result})

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

    class Server(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    class DynamicServer(Server):
        # Windows permits two listeners to bind the same port when
        # SO_REUSEADDR is enabled.  A port-zero bridge must reserve its chosen
        # safe port exclusively so concurrent drivers receive distinct URLs.
        allow_reuse_address = False

    requested_port = int(port)
    if requested_port != 0:
        return Server((host, requested_port), Handler)

    last_error: OSError | None = None
    for candidate_port in _DYNAMIC_SAFE_PORTS:
        try:
            return DynamicServer((host, candidate_port), Handler)
        except OSError as exc:
            if exc.errno not in {errno.EADDRINUSE, 10048}:
                raise
            last_error = exc
    raise OSError(
        errno.EADDRINUSE,
        f"no available browser-safe runtime bridge port in "
        f"{_DYNAMIC_SAFE_PORTS.start}-{_DYNAMIC_SAFE_PORTS.stop - 1}",
    ) from last_error


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
        if not entry.get("confidence_mask_url") and entry.get("confidence_mask_path"):
            entry["confidence_mask_url"] = (
                f"{base_url}/material-fit/reference-image?"
                f"path={quote(str(entry['confidence_mask_path']), safe='')}"
            )
        rewritten.append(entry)
    score_cfg["reference_images"] = rewritten
    command["browser_score"] = score_cfg
    return command


def _reference_for_view(score_config: dict[str, Any], view_id: str) -> dict[str, Any] | None:
    references = score_config.get("reference_images")
    if not isinstance(references, list):
        return None
    for reference in references:
        if isinstance(reference, dict) and str(reference.get("view_id") or "") == view_id:
            return reference
    if len(references) == 1 and isinstance(references[0], dict):
        return references[0]
    return None


def _get_perceptual_scorer(state: _RuntimeCaptureState, score_config: dict[str, Any]) -> Any:
    from material_fit.vision.dists_score import (
        DEFAULT_DISTS_DEVICE,
        DEFAULT_DISTS_IMAGE_SIZE,
        DEFAULT_DISTS_RESIDUAL_SKETCH_SIZE,
        DEFAULT_DISTS_RESIDUAL_SKETCH_TABLES,
        DEFAULT_DISTS_TORCH_THREADS,
    )

    metric = str(score_config.get("metric") or "").strip()
    image_size = int(score_config.get("perceptual_image_size") or DEFAULT_DISTS_IMAGE_SIZE)
    device = str(score_config.get("perceptual_device") or DEFAULT_DISTS_DEVICE)
    torch_threads = int(
        score_config.get("perceptual_torch_threads") or DEFAULT_DISTS_TORCH_THREADS
    )
    emit_residual_features = bool(
        score_config.get("perceptual_emit_residual_features", False)
    )
    residual_sketch_size = int(
        score_config.get("perceptual_residual_sketch_size")
        or DEFAULT_DISTS_RESIDUAL_SKETCH_SIZE
    )
    residual_sketch_tables = int(
        score_config.get("perceptual_residual_sketch_tables")
        or DEFAULT_DISTS_RESIDUAL_SKETCH_TABLES
    )
    scorer_class = _perceptual_scorer_class(metric)
    signature = (
        metric,
        image_size,
        device,
        torch_threads,
        emit_residual_features,
        residual_sketch_size,
        residual_sketch_tables,
    )
    with state.condition:
        if state.perceptual_scorer is None or state.perceptual_scorer_config != signature:
            scorer_kwargs = {
                "image_size": image_size,
                "device": device,
                "torch_threads": torch_threads,
            }
            if metric in {
                "foreground_dists_v1",
                "foreground_dists_material_v1",
                "foreground_dists_aligned_rgb_v3",
                "foreground_dists_aligned_rgb_v4",
                "foreground_dists_aligned_rgb_v5",
                "foreground_dists_aligned_rgb_v6",
            }:
                scorer_kwargs["emit_residual_features"] = emit_residual_features
                scorer_kwargs["residual_sketch_size"] = residual_sketch_size
                scorer_kwargs["residual_sketch_tables"] = residual_sketch_tables
            if metric == "foreground_dists_aligned_rgb_v3":
                from material_fit.vision.dists_score import (
                    DISTS_ALIGNED_RGB_V3_DISTS_WEIGHT,
                    DISTS_ALIGNED_RGB_V3_DESCRIPTOR_WEIGHT,
                    DISTS_ALIGNED_RGB_V3_PIXEL_WEIGHT,
                )

                scorer_kwargs.update(
                    {
                        "metric": metric,
                        "dists_weight": DISTS_ALIGNED_RGB_V3_DISTS_WEIGHT,
                        "aligned_rgb_weight": DISTS_ALIGNED_RGB_V3_PIXEL_WEIGHT,
                        "local_contrast_weight": 0.0,
                        "material_descriptor_weight": (
                            DISTS_ALIGNED_RGB_V3_DESCRIPTOR_WEIGHT
                        ),
                        "residual_contract": (
                            "weighted_dists_normalized_rgb_and_material_descriptor_v3"
                        ),
                    }
                )
            elif metric in {
                "foreground_dists_aligned_rgb_v4",
                "foreground_dists_aligned_rgb_v5",
            }:
                from material_fit.vision.dists_score import (
                    DISTS_ALIGNED_RGB_V5_DISTS_WEIGHT,
                    DISTS_ALIGNED_RGB_V5_PIXEL_WEIGHT,
                )

                scorer_kwargs.update(
                    {
                        "metric": metric,
                        "dists_weight": DISTS_ALIGNED_RGB_V5_DISTS_WEIGHT,
                        "aligned_rgb_weight": DISTS_ALIGNED_RGB_V5_PIXEL_WEIGHT,
                        "local_contrast_weight": 0.0,
                        "material_descriptor_weight": 4.0,
                        "residual_contract": (
                            "perceptual_first_dists_normalized_rgb_and_material_descriptor_v5"
                        ),
                    }
                )
            state.perceptual_scorer = scorer_class(
                **scorer_kwargs,
            )
            state.perceptual_scorer_config = signature
        return state.perceptual_scorer


def _perceptual_scorer_class(metric: str) -> Any:
    if metric == "foreground_dists_v1":
        from material_fit.vision.dists_score import ForegroundDISTSScorer

        return ForegroundDISTSScorer
    if metric == "foreground_dists_material_v1":
        from material_fit.vision.dists_score import ForegroundDISTSMaterialScorer

        return ForegroundDISTSMaterialScorer
    if metric in {
        "foreground_dists_aligned_rgb_v3",
        "foreground_dists_aligned_rgb_v4",
        "foreground_dists_aligned_rgb_v5",
        "foreground_dists_aligned_rgb_v6",
    }:
        from material_fit.vision.dists_score import ForegroundDISTSAlignedRGBScorer

        return ForegroundDISTSAlignedRGBScorer
    raise ValueError(f"unsupported server-side perceptual metric: {metric!r}")


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
