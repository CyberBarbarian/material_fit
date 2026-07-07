"""Persistent queue daemon for real Laya runtime capture.

The optimizer writes request JSON files into ``queue/`` and waits for matching
result JSON files under ``results/``. This daemon bridges that file-queue
contract to the existing runtime capture HTTP contract consumed by
``MaterialFitCapture.ts`` in a running Laya scene.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .capture_server import CaptureState, make_server, safe_name, with_reference_image_urls


@dataclass(frozen=True)
class QueuePaths:
    state_dir: Path
    queue_dir: Path
    result_dir: Path
    ready_file: Path
    inflight_dir: Path
    processed_dir: Path
    failed_dir: Path
    log_dir: Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Persistent file-queue daemon for Laya runtime capture.")
    parser.add_argument("--state-dir", default="", help="Queue state directory. Defaults to STATE_DIR env replacement.")
    parser.add_argument("--queue-dir", default="", help="Request directory. Defaults to <state-dir>/queue.")
    parser.add_argument("--result-dir", default="", help="Result directory. Defaults to <state-dir>/results.")
    parser.add_argument("--ready-file", default="", help="Ready marker. Defaults to <state-dir>/ready.json.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--poll-s", type=float, default=0.02)
    parser.add_argument("--once", action="store_true", help="Process one request and exit.")
    args = parser.parse_args()

    paths = build_paths(args)
    ensure_dirs(paths)
    write_ready(paths, args)
    print(f"[persistent-queue] ready state_dir={paths.state_dir} port={args.port}", flush=True)

    processed = 0
    try:
        while True:
            request_path = next_request(paths.queue_dir)
            if request_path is None:
                if args.once and processed > 0:
                    return 0
                time.sleep(max(float(args.poll_s), 0.001))
                continue
            process_request(request_path, paths=paths, host=args.host, port=int(args.port), timeout_s=float(args.timeout_s))
            processed += 1
            if args.once:
                return 0
    finally:
        remove_ready(paths)


def build_paths(args: argparse.Namespace) -> QueuePaths:
    state_dir = Path(str(args.state_dir or "")).expanduser()
    if not str(state_dir):
        raise ValueError("--state-dir is required")
    state_dir = state_dir.resolve()
    queue_dir = Path(str(args.queue_dir or state_dir / "queue")).expanduser().resolve()
    result_dir = Path(str(args.result_dir or state_dir / "results")).expanduser().resolve()
    ready_file = Path(str(args.ready_file or state_dir / "ready.json")).expanduser().resolve()
    return QueuePaths(
        state_dir=state_dir,
        queue_dir=queue_dir,
        result_dir=result_dir,
        ready_file=ready_file,
        inflight_dir=state_dir / "inflight",
        processed_dir=state_dir / "processed",
        failed_dir=state_dir / "failed",
        log_dir=state_dir / "logs",
    )


def ensure_dirs(paths: QueuePaths) -> None:
    for directory in (
        paths.state_dir,
        paths.queue_dir,
        paths.result_dir,
        paths.inflight_dir,
        paths.processed_dir,
        paths.failed_dir,
        paths.log_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def write_ready(paths: QueuePaths, args: argparse.Namespace) -> None:
    payload = {
        "ok": True,
        "state_dir": str(paths.state_dir),
        "queue_dir": str(paths.queue_dir),
        "result_dir": str(paths.result_dir),
        "host": str(args.host),
        "port": int(args.port),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    tmp = paths.ready_file.with_suffix(paths.ready_file.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(paths.ready_file)


def remove_ready(paths: QueuePaths) -> None:
    try:
        paths.ready_file.unlink()
    except FileNotFoundError:
        pass


def next_request(queue_dir: Path) -> Path | None:
    for path in sorted(queue_dir.glob("*.request.json")):
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def process_request(
    request_path: Path,
    *,
    paths: QueuePaths,
    host: str,
    port: int,
    timeout_s: float,
) -> None:
    request_id = request_path.name.removesuffix(".request.json")
    inflight_path = paths.inflight_dir / request_path.name
    result_path = paths.result_dir / f"{request_id}.result.json"
    failed_path = paths.failed_dir / request_path.name
    processed_path = paths.processed_dir / request_path.name
    try:
        request_path.replace(inflight_path)
        request = json.loads(inflight_path.read_text(encoding="utf-8-sig"))
        command = build_capture_command(request, host=host, port=port)
        output_dir = Path(str(command.get("output_dir") or paths.state_dir / "captures" / safe_name(request_id))).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        command["output_dir"] = str(output_dir)
        expected = {str(view["view_id"]) for view in command.get("views", []) if isinstance(view, dict)}
        state = CaptureState(command=command, output_dir=output_dir, expected=expected)
        server = make_server(host, port, state)
        run_server_until_done(server, state, timeout_s=timeout_s)
        payload = build_result_payload(state, output_dir=output_dir)
        write_json_atomic(result_path, payload)
        shutil.move(str(inflight_path), str(processed_path))
    except Exception as exc:  # noqa: BLE001
        error_payload = {
            "ok": False,
            "error": str(exc),
            "request_path": str(inflight_path if inflight_path.exists() else request_path),
        }
        write_json_atomic(result_path, error_payload)
        source = inflight_path if inflight_path.exists() else request_path
        if source.exists():
            shutil.move(str(source), str(failed_path))


def build_capture_command(request: dict[str, Any], *, host: str, port: int) -> dict[str, Any]:
    command = request.get("command")
    if not isinstance(command, dict):
        raise ValueError("queue request missing command object")
    command = json.loads(json.dumps(command, ensure_ascii=False))
    command["server_base_url"] = f"http://{host}:{port}"
    command["post_url"] = f"http://{host}:{port}/material-fit/capture-result"
    command.setdefault("nonce", request.get("request_id") or f"capture_{time.time_ns()}")
    return with_reference_image_urls(command, str(command["server_base_url"]))


def run_server_until_done(server: ThreadingHTTPServer, state: CaptureState, *, timeout_s: float) -> None:
    started = time.monotonic()
    server.timeout = 0.1
    score_cfg = state.command.get("browser_score")
    expects_browser_score = isinstance(score_cfg, dict) and score_cfg.get("enabled", True) is not False
    try:
        while True:
            server.handle_request()
            if state.browser_score is not None:
                return
            if not expects_browser_score and state.expected and state.received >= state.expected:
                return
            if time.monotonic() - started > timeout_s:
                missing = sorted(state.expected - state.received)
                score_wait = " browser_score" if expects_browser_score and state.browser_score is None else ""
                raise TimeoutError(f"timed out waiting for Laya capture{score_wait}; missing={missing}")
    finally:
        server.server_close()


def build_result_payload(state: CaptureState, *, output_dir: Path) -> dict[str, Any]:
    screenshots = sorted(str(path) for path in output_dir.glob("*.png"))
    payload: dict[str, Any] = {
        "ok": True,
        "output_dir": str(output_dir),
        "screenshots": screenshots,
        "received": sorted(state.received),
        "logs": state.logs,
    }
    if isinstance(state.browser_score, dict):
        payload["browser_score"] = state.browser_score
    return payload


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
