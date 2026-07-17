from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from material_fit.experiments import fish_core_experiment as core


class _FakeProcess:
    def __init__(self, pid: int = 43210, *, returncode: int | None = None) -> None:
        self.pid = pid
        self._returncode = returncode

    def poll(self) -> int | None:
        return self._returncode


def _install_failed_startup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    expected_pid_file: Path,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    process = _FakeProcess()

    def fake_popen(*args: Any, **kwargs: Any) -> _FakeProcess:
        captured["popen_args"] = args
        captured["popen_kwargs"] = kwargs
        return process

    def fail_wait(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("readiness failed")

    def fake_terminate(proc: _FakeProcess, *, pid_file: Path | None = None) -> None:
        captured["terminated_process"] = proc
        captured["pid_file"] = pid_file
        assert pid_file == expected_pid_file
        assert pid_file.read_text(encoding="ascii") == f"{process.pid}\n"
        pid_file.unlink()

    monkeypatch.setattr(core.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(core, "_wait_for_file", fail_wait)
    monkeypatch.setattr(core, "_terminate_process", fake_terminate)
    return captured


def test_queue_startup_failure_terminates_owned_process_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    captured = _install_failed_startup(monkeypatch, expected_pid_file=run_dir / "queue.pid")

    with pytest.raises(RuntimeError, match="readiness failed"):
        core._start_queue(repo_root=tmp_path, run_dir=run_dir, cap_port=9185, env={})

    assert captured["terminated_process"].pid == 43210
    assert not (run_dir / "queue.pid").exists()
    assert captured["popen_kwargs"] | core._process_group_popen_kwargs() == captured["popen_kwargs"]


def test_renderer_startup_failure_terminates_owned_process_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    captured = _install_failed_startup(monkeypatch, expected_pid_file=run_dir / "renderer.pid")
    selected = {
        "laya_project_dir": tmp_path / "project",
        "scene_path": tmp_path / "project/assets/resources/game.ls",
    }

    with pytest.raises(RuntimeError, match="readiness failed"):
        core._start_renderer(
            repo_root=tmp_path,
            run_dir=run_dir,
            cap_port=9185,
            width=900,
            height=700,
            engine_root=tmp_path / "engine",
            selected=selected,
            env={},
            headed=False,
        )

    assert captured["terminated_process"].pid == 43210
    assert not (run_dir / "renderer.pid").exists()
    assert captured["popen_kwargs"] | core._process_group_popen_kwargs() == captured["popen_kwargs"]


def test_linux_renderer_uses_short_tmpdir_for_chromium_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "linux-renderer-run"
    captured = _install_failed_startup(monkeypatch, expected_pid_file=run_dir / "renderer.pid")
    monkeypatch.setattr(core.sys, "platform", "linux")
    monkeypatch.setattr(core, "_resolve_node_executable", lambda: "node")
    selected = {
        "laya_project_dir": tmp_path / "project",
        "scene_path": tmp_path / "project/assets/resources/game.ls",
    }

    with pytest.raises(RuntimeError, match="readiness failed"):
        core._start_renderer(
            repo_root=tmp_path,
            run_dir=run_dir,
            cap_port=9185,
            width=900,
            height=700,
            engine_root=tmp_path / "engine",
            selected=selected,
            env={},
            headed=False,
        )

    renderer_env = captured["popen_kwargs"]["env"]
    assert renderer_env["TMPDIR"] == "/tmp"
    assert renderer_env["TMP"] == "/tmp"
    assert renderer_env["TEMP"] == "/tmp"


def test_terminate_process_removes_stale_pid_file_for_exited_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "renderer.pid"
    pid_file.write_text("43210\n", encoding="ascii")

    core._terminate_process(_FakeProcess(returncode=0), pid_file=pid_file)  # type: ignore[arg-type]

    assert not pid_file.exists()


def test_process_group_launch_contract_matches_platform() -> None:
    kwargs = core._process_group_popen_kwargs()

    if os.name == "nt":
        assert kwargs == {"creationflags": core.subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        assert kwargs == {"start_new_session": True}
