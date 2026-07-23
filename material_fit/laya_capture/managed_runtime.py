"""Owned lifecycle for one profile-driven persistent Laya renderer."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class ManagedRuntimeRenderer:
    def __init__(
        self,
        *,
        profile_path: str | Path,
        server_url: str,
        state_dir: str | Path,
        timeout_s: float = 30.0,
        node_modules: str | Path | None = None,
    ) -> None:
        self.profile_path = Path(profile_path).expanduser().resolve()
        self.server_url = str(server_url)
        self.state_dir = Path(state_dir).expanduser().resolve()
        self.timeout_s = float(timeout_s)
        self.node_modules = Path(node_modules).expanduser().resolve() if node_modules else None
        self.process: subprocess.Popen[str] | None = None
        self.ready: dict[str, Any] | None = None
        self.cleanup_report: dict[str, Any] | None = None

    def start(self) -> dict[str, Any]:
        if self.process is not None and self.process.poll() is None and self.ready is not None:
            return self.ready
        self.state_dir.mkdir(parents=True, exist_ok=True)
        ready_file = self.state_dir / "runtime_renderer_ready.json"
        max_attempts = _renderer_start_attempts()
        for attempt in range(1, max_attempts + 1):
            ready_file.unlink(missing_ok=True)
            self.ready = None
            self.process = _spawn_renderer(
                profile_path=self.profile_path,
                server_url=self.server_url,
                ready_file=ready_file,
                stdout_path=self.state_dir / "runtime_renderer_stdout.log",
                stderr_path=self.state_dir / "runtime_renderer_stderr.log",
                node_modules=self.node_modules,
            )
            _write_json(
                self.state_dir / "runtime_renderer_pid.json",
                {
                    "pid": self.process.pid,
                    "profile": str(self.profile_path),
                    "server_url": self.server_url,
                    "attempt": attempt,
                },
            )
            try:
                self.ready = _wait_for_ready(
                    self.process,
                    ready_file,
                    stderr_path=self.state_dir / "runtime_renderer_stderr.log",
                    timeout_s=self.timeout_s,
                )
                return self.ready
            except Exception as exc:
                self.stop()
                if attempt >= max_attempts or not _is_transient_renderer_start_error(exc):
                    raise
                _archive_failed_attempt(self.state_dir, attempt)
                time.sleep(2.0)
        raise AssertionError("unreachable renderer startup state")

    def stop(self) -> dict[str, Any]:
        self.cleanup_report = stop_owned_process_tree(self.process)
        self.process = None
        _write_json(self.state_dir / "runtime_renderer_cleanup.json", self.cleanup_report)
        return self.cleanup_report

    def __enter__(self) -> "ManagedRuntimeRenderer":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()


def _spawn_renderer(
    *,
    profile_path: Path,
    server_url: str,
    ready_file: Path,
    stdout_path: Path,
    stderr_path: Path,
    node_modules: Path | None,
) -> subprocess.Popen[str]:
    repo_root = Path(__file__).resolve().parents[2]
    runner = repo_root / "material_fit" / "laya_capture" / "run_runtime_renderer.js"
    modules = node_modules or repo_root / "node_modules"
    if not any((modules / package).is_dir() for package in ("playwright", "playwright-chromium")):
        raise FileNotFoundError(
            f"Playwright is not installed under NODE_PATH: {modules}. Run npm ci."
        )
    node = shutil.which("node")
    if not node:
        local_node = repo_root / ".runtime" / "node" / "bin" / "node"
        if local_node.is_file():
            node = str(local_node)
    if not node:
        raise FileNotFoundError("node is not available on PATH")
    env = dict(os.environ)
    env["NODE_PATH"] = str(modules)
    env["PYTHON"] = sys.executable
    command = [
        node,
        str(runner),
        "--assetProfile",
        str(profile_path),
        "--server",
        server_url,
        "--readyFile",
        str(ready_file),
    ]
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    stdout = stdout_path.open("w", encoding="utf-8")
    stderr = stderr_path.open("w", encoding="utf-8")
    try:
        return subprocess.Popen(
            command,
            cwd=repo_root,
            env=env,
            stdout=stdout,
            stderr=stderr,
            text=True,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    finally:
        stdout.close()
        stderr.close()


def _wait_for_ready(
    process: subprocess.Popen[str],
    ready_file: Path,
    *,
    stderr_path: Path,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if ready_file.is_file():
            return json.loads(ready_file.read_text(encoding="utf-8-sig"))
        exit_code = process.poll()
        if exit_code is not None:
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
            raise RuntimeError(f"runtime renderer exited with {exit_code}: {stderr[-2000:]}")
        time.sleep(0.05)
    raise TimeoutError(f"runtime renderer did not become ready within {timeout_s:.1f}s")


def _is_transient_renderer_start_error(error: BaseException) -> bool:
    if os.name == "nt":
        return False
    message = str(error)
    return "CONTEXT_LOST_WEBGL" in message or "statefirst" in message


def _renderer_start_attempts() -> int:
    if os.name == "nt":
        return 1
    raw = os.environ.get("MATERIAL_FIT_RENDERER_START_ATTEMPTS", "4")
    try:
        parsed = int(raw)
    except ValueError:
        parsed = 4
    return min(max(parsed, 1), 6)


def _archive_failed_attempt(state_dir: Path, attempt: int) -> None:
    for name in (
        "runtime_renderer_stdout.log",
        "runtime_renderer_stderr.log",
        "runtime_renderer_pid.json",
        "runtime_renderer_cleanup.json",
    ):
        source = state_dir / name
        if not source.exists():
            continue
        target = source.with_name(f"{source.stem}.attempt_{attempt}{source.suffix}")
        source.replace(target)


def stop_owned_process_tree(process: subprocess.Popen[str] | None) -> dict[str, Any]:
    if process is None:
        return {"ok": True, "reason": "not_started"}
    pid = int(process.pid)
    if process.poll() is None:
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            return {
                "ok": process.poll() is not None,
                "pid": pid,
                "exit_code": process.poll(),
                "taskkill_exit_code": completed.returncode,
            }
        os.killpg(pid, 15)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(pid, 9)
            process.wait(timeout=5)
    return {"ok": process.poll() is not None, "pid": pid, "exit_code": process.poll()}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
