from __future__ import annotations

import argparse
import base64
import json
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from .capture_quality import analyze_png_capture_quality, default_visual_quality_guard


@dataclass
class CaptureState:
    command: dict[str, Any]
    output_dir: Path
    expected: set[str]
    received: set[str] = field(default_factory=set)
    logs: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    capture_quality: dict[str, dict[str, Any]] = field(default_factory=dict)
    browser_score: dict[str, Any] | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Local command/result server for Laya multi-view capture.")
    parser.add_argument("--unity-metadata", help="Unity multi-view metadata JSON used to seed yaw/pitch views.")
    parser.add_argument("--command-json", help="Explicit command JSON. Overrides values inferred from metadata.")
    parser.add_argument("--output-dir", required=True, help="Directory where posted PNG files are saved.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--camera-name", default="")
    parser.add_argument("--target-name", default="model")
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--center", default="", help="Optional target center: x,y,z")
    parser.add_argument("--target-size", default="", help="Optional target size: x,y,z")
    parser.add_argument("--distance-scale", type=float, default=2.2)
    parser.add_argument("--min-distance", type=float, default=1.0)
    parser.add_argument("--fov", type=float, default=None)
    parser.add_argument("--use-orthographic", choices=["auto", "true", "false"], default="auto")
    parser.add_argument("--orthographic-vertical-size", type=float, default=None)
    parser.add_argument("--capture-mode", choices=["auto", "orbit_camera", "rotate_target"], default="auto")
    parser.add_argument("--yaw-offset", type=float, default=0.0)
    parser.add_argument("--pitch-offset", type=float, default=0.0)
    parser.add_argument("--target-yaw-sign", type=float, default=-1.0, help="Yaw sign used by rotate_target mode.")
    parser.add_argument("--target-pitch-sign", type=float, default=-1.0, help="Pitch sign used by rotate_target mode.")
    parser.add_argument("--material-patch-json", help="JSON file with runtime material_patch payload or raw param dict.")
    parser.add_argument("--opaque-background", action="store_true", help="Do not force capture camera clearColor alpha to 0.")
    parser.add_argument("--keep-transparent-rgb", action="store_true", help="Do not zero RGB where alpha is 0.")
    parser.add_argument("--no-alpha-from-rgb", action="store_true", help="Do not preserve additive RGB-only glow by deriving alpha from RGB.")
    parser.add_argument("--alpha-from-rgb-threshold", type=float, default=1.0, help="Minimum RGB value used when deriving alpha for RGB-only glow.")
    parser.add_argument("--alpha-source", choices=["silhouette_mask", "alpha_from_rgb", "render_alpha"], default="render_alpha")
    parser.add_argument("--mask-alpha-mode", choices=["binary", "soft"], default="binary")
    parser.add_argument("--mask-alpha-threshold", type=float, default=1.0)
    parser.add_argument("--flip-y", action="store_true", help="Flip readback pixels vertically before encoding PNG.")
    parser.add_argument("--linear-render-texture", action="store_true", help="Use a non-sRGB RenderTexture for runtime capture.")
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--no-wait", action="store_true", help="Serve forever until interrupted.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    command = build_command(args, output_dir)
    (output_dir / "runtime_capture_command.json").write_text(
        json.dumps(command, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    expected = {str(view["view_id"]) for view in command.get("views", [])}
    state = CaptureState(command=command, output_dir=output_dir, expected=expected)

    server = make_server(args.host, args.port, state)
    print(f"[capture-server] serving http://{args.host}:{args.port}", flush=True)
    print(f"[capture-server] output_dir={output_dir}", flush=True)
    print(f"[capture-server] nonce={command['nonce']} expected_views={len(expected)}", flush=True)

    if args.no_wait:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0

    started = time.monotonic()
    server.timeout = 0.2
    while True:
        server.handle_request()
        if state.errors:
            (output_dir / "capture_error.json").write_text(
                json.dumps({"received": sorted(state.received), "errors": state.errors, "logs": state.logs}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[capture-server] failed; error={state.errors[0].get('reason') or state.errors[0].get('error')}", flush=True)
            return 3
        if expected and state.received >= expected:
            print(f"[capture-server] completed {len(state.received)}/{len(expected)} views", flush=True)
            return 0
        if time.monotonic() - started > args.timeout_sec:
            missing = sorted(expected - state.received)
            (output_dir / "capture_timeout.json").write_text(
                json.dumps({"received": sorted(state.received), "missing": missing, "logs": state.logs}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[capture-server] timeout; missing={missing}", flush=True)
            return 2


def build_command(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    metadata = read_json(Path(args.unity_metadata)) if args.unity_metadata else {}
    explicit = read_json(Path(args.command_json)) if args.command_json else {}
    views = explicit.get("views") or views_from_metadata(metadata)
    width = args.width or explicit.get("width") or metadata.get("imageWidth") or 900
    height = args.height or explicit.get("height") or metadata.get("imageHeight") or 700
    center = parse_vec3(args.center) or explicit.get("center")
    target_size = parse_vec3(args.target_size) or explicit.get("target_size") or metadata.get("targetSize")
    use_orthographic = explicit.get("use_orthographic", metadata.get("useOrthographic", False))
    material_patch = build_material_patch(args, explicit)
    if args.use_orthographic != "auto":
        use_orthographic = args.use_orthographic == "true"
    command: dict[str, Any] = {
        "enabled": True,
        "nonce": f"capture_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}",
        "server_base_url": f"http://{args.host}:{args.port}",
        "post_url": f"http://{args.host}:{args.port}/material-fit/capture-result",
        "camera_name": args.camera_name or explicit.get("camera_name", ""),
        "target_name": args.target_name or explicit.get("target_name", ""),
        "width": int(width),
        "height": int(height),
        "use_orthographic": bool(use_orthographic),
        "capture_mode": explicit.get("capture_mode", args.capture_mode),
        "distance_scale": float(explicit.get("distance_scale", args.distance_scale)),
        "min_distance": float(explicit.get("min_distance", args.min_distance)),
        "yaw_offset": float(explicit.get("yaw_offset", args.yaw_offset)),
        "pitch_offset": float(explicit.get("pitch_offset", args.pitch_offset)),
        "target_yaw_sign": float(explicit.get("target_yaw_sign", args.target_yaw_sign)),
        "target_pitch_sign": float(explicit.get("target_pitch_sign", args.target_pitch_sign)),
        "transparent_background": not bool(getattr(args, "opaque_background", False)),
        "zero_transparent_rgb": not bool(getattr(args, "keep_transparent_rgb", False)),
        "alpha_from_rgb": not bool(getattr(args, "no_alpha_from_rgb", False)),
        "alpha_from_rgb_threshold": float(getattr(args, "alpha_from_rgb_threshold", 1.0)),
        "alpha_source": getattr(args, "alpha_source", "render_alpha") or "render_alpha",
        "mask_alpha_mode": getattr(args, "mask_alpha_mode", "binary"),
        "mask_alpha_threshold": float(getattr(args, "mask_alpha_threshold", 1.0)),
        "flip_y": bool(getattr(args, "flip_y", False)),
        "render_texture_srgb": not bool(getattr(args, "linear_render_texture", False)),
        "views": views,
        "output_dir": str(output_dir),
    }
    if "visual_quality_guard" not in explicit:
        command["visual_quality_guard"] = default_visual_quality_guard()
    if material_patch:
        command["material_patch"] = material_patch
    fov = args.fov if args.fov is not None else explicit.get("fov", metadata.get("fieldOfView"))
    if fov is not None:
        command["fov"] = float(fov)
    orthographic_vertical_size = args.orthographic_vertical_size or explicit.get("orthographic_vertical_size")
    if orthographic_vertical_size is not None:
        command["orthographic_vertical_size"] = float(orthographic_vertical_size)
    if center is not None:
        command["center"] = center
    if target_size is not None:
        command["target_size"] = target_size
    command.update({k: v for k, v in explicit.items() if k not in {"views"}})
    command["views"] = views
    return with_reference_image_urls(command, str(command["server_base_url"]))


def build_material_patch(args: argparse.Namespace, explicit: dict[str, Any]) -> dict[str, Any]:
    if isinstance(explicit.get("material_patch"), dict):
        return explicit["material_patch"]
    patch_path = getattr(args, "material_patch_json", "") or ""
    if not patch_path:
        return {}
    payload = read_json(Path(patch_path))
    if isinstance(payload.get("material_patch"), dict):
        return payload["material_patch"]
    if isinstance(payload.get("values"), dict):
        return payload
    if isinstance(payload, dict):
        return {"target_name": getattr(args, "target_name", "") or explicit.get("target_name", ""), "values": payload}
    return {}


def views_from_metadata(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    raw_views = metadata.get("views") if isinstance(metadata.get("views"), list) else []
    views: list[dict[str, Any]] = []
    for index, view in enumerate(raw_views):
        yaw = float(view.get("yaw", 0.0))
        pitch = float(view.get("pitch", 0.0))
        view_id = f"v{index:03d}_yaw{format_angle(yaw)}_pitch{format_angle(pitch)}"
        views.append(
            {
                "view_id": view_id,
                "yaw": yaw,
                "pitch": pitch,
                "file_name": f"laya_{view_id}.png",
            }
        )
    if not views:
        views.append({"view_id": "v000_yaw0_pitch0", "yaw": 0.0, "pitch": 0.0, "file_name": "laya_v000_yaw0_pitch0.png"})
    return views


def make_server(host: str, port: int, state: CaptureState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/material-fit/capture-command":
                query = parse_qs(parsed.query)
                last_nonce = query.get("last_nonce", [""])[0]
                payload = state.command if last_nonce != state.command.get("nonce") else {"enabled": False, "nonce": last_nonce}
                self.write_json(payload)
                return
            if parsed.path == "/material-fit/status":
                self.write_json(
                    {
                        "expected": sorted(state.expected),
                        "received": sorted(state.received),
                        "logs": state.logs[-20:],
                        "errors": state.errors[-20:],
                        "capture_quality": state.capture_quality,
                        "browser_score": state.browser_score,
                    }
                )
                return
            if parsed.path == "/material-fit/reference-image":
                self.handle_reference_image(parsed)
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/material-fit/capture-raw-rgba":
                    self.handle_capture_raw_rgba(parsed)
                    return
                payload = self.read_json_body()
                if parsed.path == "/material-fit/capture-result":
                    self.handle_capture_result(payload)
                    return
                if parsed.path == "/material-fit/capture-score":
                    self.handle_capture_score(payload)
                    return
                if parsed.path == "/material-fit/capture-log":
                    state.logs.append(payload)
                    self.write_json({"ok": True})
                    return
            except Exception as exc:  # noqa: BLE001
                self.write_json({"ok": False, "error": str(exc)}, status=500)
                return
            self.send_error(404)

        def handle_capture_result(self, payload: dict[str, Any]) -> None:
            if not self.validate_nonce(str(payload.get("nonce") or "")):
                return
            view_id = safe_name(str(payload.get("view_id") or "view"))
            file_name = safe_name(str(payload.get("file_name") or f"{view_id}.png"))
            if not file_name.lower().endswith(".png"):
                file_name += ".png"
            raw = str(payload.get("png_base64") or "")
            image_bytes = base64.b64decode(raw)
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
                self.write_json({"ok": False, "error": error["reason"], "capture_quality": quality}, status=422)
                return
            state.received.add(view_id)
            self.write_json({"ok": True, "path": str(output_path), "received": sorted(state.received)})

        def handle_capture_score(self, payload: dict[str, Any]) -> None:
            if not self.validate_nonce(str(payload.get("nonce") or "")):
                return
            browser_score = payload.get("browser_score")
            if not isinstance(browser_score, dict):
                self.write_json({"ok": False, "error": "missing browser_score"}, status=400)
                return
            state.browser_score = dict(browser_score)
            state.browser_score.setdefault("enabled", True)
            if state.command.get("persist_browser_score", True) is not False:
                (state.output_dir / "browser_score.json").write_text(
                    json.dumps(state.browser_score, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            state.received.update(state.expected)
            self.write_json({"ok": True, "received": sorted(state.received), "browser_score": state.browser_score})

        def handle_capture_raw_rgba(self, parsed: Any) -> None:
            query = parse_qs(parsed.query)
            if not self.validate_nonce(str(first_query_value(query, "nonce") or "")):
                return
            view_id = safe_name(str(first_query_value(query, "view_id") or "view"))
            file_name = safe_name(str(first_query_value(query, "file_name") or f"{view_id}.rgba"))
            if not file_name.lower().endswith(".rgba"):
                file_name += ".rgba"
            width = int(first_query_value(query, "width") or "0")
            height = int(first_query_value(query, "height") or "0")
            if width <= 0 or height <= 0:
                self.write_json({"ok": False, "error": "invalid raw RGBA dimensions"}, status=400)
                return
            length = int(self.headers.get("Content-Length") or "0")
            image_bytes = self.rfile.read(length)
            expected_len = width * height * 4
            if len(image_bytes) != expected_len:
                self.write_json(
                    {"ok": False, "error": f"raw RGBA byte count mismatch: got {len(image_bytes)}, expected {expected_len}"},
                    status=400,
                )
                return
            output_path = state.output_dir / file_name
            output_path.write_bytes(image_bytes)
            state.received.add(view_id)
            sidecar = {
                "format": "raw_rgba",
                "nonce": str(first_query_value(query, "nonce") or ""),
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
            self.write_json({"ok": True, "path": str(output_path), "received": sorted(state.received)})

        def validate_nonce(self, raw_nonce: str) -> bool:
            expected_nonce = str(state.command.get("nonce") or "")
            if expected_nonce and raw_nonce != expected_nonce:
                self.write_json({"ok": False, "error": "stale capture nonce"}, status=409)
                return False
            return True

        def handle_reference_image(self, parsed: Any) -> None:
            query = parse_qs(parsed.query)
            path_text = first_query_value(query, "path")
            if not path_text:
                self.write_json({"ok": False, "error": "missing reference image path"}, status=400)
                return
            path = Path(path_text)
            if not path.exists() or not path.is_file():
                self.write_json({"ok": False, "error": f"reference image not found: {path}"}, status=404)
                return
            data = path.read_bytes()
            content_type = "image/png" if path.suffix.lower() == ".png" else "application/octet-stream"
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8")) if raw else {}

        def write_json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def parse_vec3(text: str) -> list[float] | None:
    if not text:
        return None
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise ValueError(f"expected x,y,z vector, got {text!r}")
    return [float(part) for part in parts]


def format_angle(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".").replace("-", "m").replace(".", "p")


def safe_name(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    return "".join(ch if ch in allowed else "_" for ch in value)[:160] or "capture.png"


def with_reference_image_urls(command: dict[str, Any], base_url: str) -> dict[str, Any]:
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


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


if __name__ == "__main__":
    raise SystemExit(main())
