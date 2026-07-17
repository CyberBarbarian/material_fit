from __future__ import annotations

from pathlib import Path

from material_fit.laya_capture import managed_runtime


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        return 1


def test_linux_transient_webgl_startup_is_retried_once(monkeypatch, tmp_path: Path) -> None:
    attempts: list[int] = []
    stopped: list[int] = []

    def fake_spawn(**kwargs):
        attempt = len(attempts) + 1
        attempts.append(attempt)
        Path(kwargs["stdout_path"]).write_text(f"stdout-{attempt}", encoding="utf-8")
        Path(kwargs["stderr_path"]).write_text(f"stderr-{attempt}", encoding="utf-8")
        return _FakeProcess(1000 + attempt)

    def fake_wait(process, ready_file, *, stderr_path, timeout_s):
        del ready_file, stderr_path, timeout_s
        if process.pid == 1001:
            raise RuntimeError("CONTEXT_LOST_WEBGL statefirst")
        return {"ok": True, "pid": process.pid}

    def fake_stop(process):
        stopped.append(process.pid)
        return {"ok": True, "pid": process.pid}

    monkeypatch.setattr(managed_runtime, "_spawn_renderer", fake_spawn)
    monkeypatch.setattr(managed_runtime, "_wait_for_ready", fake_wait)
    monkeypatch.setattr(managed_runtime, "stop_owned_process_tree", fake_stop)
    monkeypatch.setattr(managed_runtime, "_is_transient_renderer_start_error", lambda error: True)
    monkeypatch.setattr(managed_runtime, "_renderer_start_attempts", lambda: 2)
    monkeypatch.setattr(managed_runtime.time, "sleep", lambda _: None)

    renderer = managed_runtime.ManagedRuntimeRenderer(
        profile_path=tmp_path / "profile.json",
        server_url="http://127.0.0.1:9000",
        state_dir=tmp_path / "state",
    )
    ready = renderer.start()

    assert ready == {"ok": True, "pid": 1002}
    assert attempts == [1, 2]
    assert stopped == [1001]
    assert (tmp_path / "state/runtime_renderer_stderr.attempt_1.log").read_text(encoding="utf-8") == "stderr-1"


def test_non_transient_startup_error_is_not_retried(monkeypatch, tmp_path: Path) -> None:
    attempts: list[int] = []

    def fake_spawn(**kwargs):
        attempts.append(1)
        return _FakeProcess(2001)

    monkeypatch.setattr(managed_runtime, "_spawn_renderer", fake_spawn)
    monkeypatch.setattr(
        managed_runtime,
        "_wait_for_ready",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("missing shader asset")),
    )
    monkeypatch.setattr(managed_runtime, "stop_owned_process_tree", lambda process: {"ok": True, "pid": process.pid})
    monkeypatch.setattr(managed_runtime, "_is_transient_renderer_start_error", lambda error: False)

    renderer = managed_runtime.ManagedRuntimeRenderer(
        profile_path=tmp_path / "profile.json",
        server_url="http://127.0.0.1:9000",
        state_dir=tmp_path / "state",
    )

    try:
        renderer.start()
    except RuntimeError as exc:
        assert "missing shader asset" in str(exc)
    else:
        raise AssertionError("expected non-transient startup failure")
    assert attempts == [1]


def test_linux_transient_webgl_startup_uses_bounded_four_attempts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    attempts: list[int] = []
    stopped: list[int] = []

    def fake_spawn(**kwargs):
        attempt = len(attempts) + 1
        attempts.append(attempt)
        Path(kwargs["stdout_path"]).write_text(f"stdout-{attempt}", encoding="utf-8")
        Path(kwargs["stderr_path"]).write_text(f"stderr-{attempt}", encoding="utf-8")
        return _FakeProcess(3000 + attempt)

    def fake_wait(process, ready_file, *, stderr_path, timeout_s):
        del process, ready_file, stderr_path, timeout_s
        raise RuntimeError("CONTEXT_LOST_WEBGL statefirst")

    def fake_stop(process):
        stopped.append(process.pid)
        return {"ok": True, "pid": process.pid}

    monkeypatch.setattr(managed_runtime, "_spawn_renderer", fake_spawn)
    monkeypatch.setattr(managed_runtime, "_wait_for_ready", fake_wait)
    monkeypatch.setattr(managed_runtime, "stop_owned_process_tree", fake_stop)
    monkeypatch.setattr(managed_runtime, "_is_transient_renderer_start_error", lambda error: True)
    monkeypatch.setattr(managed_runtime, "_renderer_start_attempts", lambda: 4)
    monkeypatch.setattr(managed_runtime.time, "sleep", lambda _: None)
    monkeypatch.delenv("MATERIAL_FIT_RENDERER_START_ATTEMPTS", raising=False)

    renderer = managed_runtime.ManagedRuntimeRenderer(
        profile_path=tmp_path / "profile.json",
        server_url="http://127.0.0.1:9000",
        state_dir=tmp_path / "state",
    )

    try:
        renderer.start()
    except RuntimeError as exc:
        assert "statefirst" in str(exc)
    else:
        raise AssertionError("expected bounded transient startup failure")
    assert attempts == [1, 2, 3, 4]
    assert stopped == [3001, 3002, 3003, 3004]
    for attempt in (1, 2, 3):
        assert (tmp_path / f"state/runtime_renderer_stderr.attempt_{attempt}.log").is_file()
