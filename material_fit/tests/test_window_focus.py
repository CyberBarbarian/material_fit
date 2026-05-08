"""Tests for :mod:`tools.material_fit.laya.window_focus`.

These tests exercise the platform-agnostic surface — pattern matching,
non-Windows graceful degradation, the FocusResult dataclass, and the
defensive boundaries we put around ctypes failures. The actual Win32
calls are stubbed; we never move real windows during tests.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.laya import window_focus  # noqa: E402
from tools.material_fit.laya.window_focus import (  # noqa: E402
    FocusResult,
    FocusTarget,
    _make_matcher,
    focus_laya_window,
)


# ---------------------------------------------------------------------
# pattern matching


def test_make_matcher_empty_string_matches_anything():
    m = _make_matcher("")
    assert m("anything") is True
    assert m("") is True
    assert m(None) is True  # type: ignore[arg-type]  — None defended in code


def test_make_matcher_substring_case_insensitive():
    m = _make_matcher("LayaAirIDE")
    assert m("LayaAirIDE") is True
    assert m("layaairide") is True
    assert m("LAYAAIRIDE") is True
    assert m("notepad") is False


def test_make_matcher_regex_pattern():
    m = _make_matcher(r"^layaair(ide|hub)$")
    assert m("LayaAirIDE") is True
    assert m("LayaAirHub") is True
    assert m("LayaAirEditor") is False


def test_make_matcher_invalid_regex_falls_back_to_substring():
    """``[unclosed`` is invalid regex; should still match by substring."""
    m = _make_matcher("[unclosed")
    assert m("here is [unclosed pattern") is True
    assert m("nothing here") is False


# ---------------------------------------------------------------------
# focus_laya_window — non-Windows path


def test_focus_laya_window_non_windows_returns_unsupported():
    with patch.object(sys, "platform", "linux"):
        result = focus_laya_window(FocusTarget(process_pattern="LayaAirIDE"))
    assert result.success is False
    assert result.reason == "unsupported_platform"
    assert result.platform == "linux"
    assert result.hwnd is None


def test_focus_laya_window_default_target_uses_layaairide():
    target = FocusTarget()
    assert target.process_pattern == "LayaAirIDE"
    assert target.title_pattern == ""


# ---------------------------------------------------------------------
# focus_laya_window — Windows path with stubbed enumeration


def _patch_windows_environment(windows: list[dict], focus_succeeds: bool = True):
    """Helper: stub out the win32 calls so we test pure decision logic."""
    return [
        patch.object(sys, "platform", "win32"),
        patch.object(window_focus, "_enumerate_visible_windows_win32", return_value=windows),
        patch.object(window_focus, "_bring_to_foreground_win32", return_value=focus_succeeds),
    ]


def test_focus_laya_window_finds_first_matching_process(monkeypatch):
    windows = [
        {"hwnd": 100, "title": "Chrome", "process": "chrome", "pid": 1},
        {"hwnd": 200, "title": "fish", "process": "LayaAirIDE", "pid": 2},
        {"hwnd": 300, "title": "effect", "process": "LayaAirIDE", "pid": 3},
    ]
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(window_focus, "_enumerate_visible_windows_win32", lambda: windows)
    monkeypatch.setattr(window_focus, "_bring_to_foreground_win32", lambda hwnd: True)

    result = focus_laya_window(
        FocusTarget(process_pattern="LayaAirIDE"),
        settle_ms=0,
    )
    assert result.success is True
    assert result.hwnd == 200
    assert result.title == "fish"
    assert result.process_name == "LayaAirIDE"


def test_focus_laya_window_title_pattern_disambiguates_multiple_layas(monkeypatch):
    """When the user has both 'fish' and 'effect' Laya projects open,
    a title_pattern must let them target the right one. This is the
    exact scenario the user reported."""
    windows = [
        {"hwnd": 200, "title": "fish", "process": "LayaAirIDE", "pid": 2},
        {"hwnd": 300, "title": "effect", "process": "LayaAirIDE", "pid": 3},
    ]
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(window_focus, "_enumerate_visible_windows_win32", lambda: windows)
    monkeypatch.setattr(window_focus, "_bring_to_foreground_win32", lambda hwnd: True)

    result = focus_laya_window(
        FocusTarget(process_pattern="LayaAirIDE", title_pattern="effect"),
        settle_ms=0,
    )
    assert result.success is True
    assert result.hwnd == 300
    assert result.title == "effect"


def test_focus_laya_window_no_match_returns_failure_with_candidates(monkeypatch):
    windows = [
        {"hwnd": 100, "title": "Notepad", "process": "Notepad", "pid": 1},
        {"hwnd": 200, "title": "Edge", "process": "msedge", "pid": 2},
    ]
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(window_focus, "_enumerate_visible_windows_win32", lambda: windows)
    monkeypatch.setattr(window_focus, "_bring_to_foreground_win32", lambda hwnd: True)

    result = focus_laya_window(
        FocusTarget(process_pattern="LayaAirIDE"),
        settle_ms=0,
    )
    assert result.success is False
    assert "LayaAirIDE" in result.reason
    assert result.hwnd is None
    # Candidates list helps the user see WHY no match (e.g., they
    # haven't started Laya, or it has a weird process name).
    assert any(c["process"] == "Notepad" for c in result.candidates_sample)


def test_focus_laya_window_setforeground_failure_reported(monkeypatch):
    """If SetForegroundWindow returns 0 (Windows blocked the focus
    switch), the result must reflect this so the user knows a manual
    click is needed."""
    windows = [
        {"hwnd": 200, "title": "fish", "process": "LayaAirIDE", "pid": 2},
    ]
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(window_focus, "_enumerate_visible_windows_win32", lambda: windows)
    monkeypatch.setattr(window_focus, "_bring_to_foreground_win32", lambda hwnd: False)

    result = focus_laya_window(
        FocusTarget(process_pattern="LayaAirIDE"),
        settle_ms=0,
    )
    assert result.success is False
    assert result.hwnd == 200  # we did find the window
    assert "blocked" in result.reason.lower() or "click" in result.reason.lower()


def test_focus_laya_window_enumeration_exception_handled(monkeypatch):
    """ctypes call raising must not crash the caller — our pipeline must
    keep running even if the focus subsystem misbehaves."""
    monkeypatch.setattr(sys, "platform", "win32")

    def boom():
        raise OSError("user32 not loaded")

    monkeypatch.setattr(window_focus, "_enumerate_visible_windows_win32", boom)

    result = focus_laya_window(
        FocusTarget(process_pattern="LayaAirIDE"),
        settle_ms=0,
    )
    assert result.success is False
    assert "user32 not loaded" in result.reason or "enumeration failed" in result.reason


def test_focus_laya_window_settle_ms_calls_sleep(monkeypatch):
    """settle_ms must translate into a sleep — Laya needs a window
    after the focus switch to push at least one fresh frame."""
    windows = [
        {"hwnd": 200, "title": "fish", "process": "LayaAirIDE", "pid": 2},
    ]
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(window_focus, "_enumerate_visible_windows_win32", lambda: windows)
    monkeypatch.setattr(window_focus, "_bring_to_foreground_win32", lambda hwnd: True)
    sleep_calls: list[float] = []
    focus_laya_window(
        FocusTarget(process_pattern="LayaAirIDE"),
        settle_ms=300,
        sleep_fn=lambda s: sleep_calls.append(s),
    )
    assert sleep_calls == [pytest.approx(0.300)]


def test_focus_result_to_dict_round_trip():
    r = FocusResult(success=True, reason="ok", hwnd=42, title="fish", process_name="LayaAirIDE")
    d = r.to_dict()
    assert d["success"] is True
    assert d["hwnd"] == 42
    assert d["title"] == "fish"
    assert d["process_name"] == "LayaAirIDE"
    assert "platform" in d  # always populated for diagnostics
