"""Bring the Laya editor window to the foreground before a screen capture.

Background — why this module exists
-----------------------------------

Most game editors (Unity, Laya, Unreal) **throttle or pause rendering when
their window is not the foreground**, to save GPU. This means our pipeline
of "write .lmat → wait → screenshot" silently degrades into "write .lmat →
sleep → screenshot a stale frame" the moment the user alt-tabs to the IDE
or browser. The refresh_probe (E-007) caught this — three captures all
showed the same frozen mecha because Laya never re-rendered while the
browser had focus.

Fix: every time we are about to capture, programmatically bring the Laya
window to the foreground using ``SetForegroundWindow``, wait a couple
hundred milliseconds for Laya to push at least one fresh frame, then
capture. Same trick is needed before writing the .lmat (so Laya is
focused when its file watcher fires).

Why this is non-trivial on Windows
----------------------------------

``SetForegroundWindow`` is restricted: it only works when the calling
process *already* owns the foreground window, OR was launched by it,
OR a few other narrow cases. The well-known workaround is to call
``AttachThreadInput`` to attach our thread to the foreground thread's
input queue, then ``BringWindowToTop`` + ``SetForegroundWindow`` while
attached. Detach immediately after.

The Laya window is identified by ``(process_name, title)``. Both can
be substrings or regex patterns; both are optional. Default
``process_pattern="LayaAirIDE"`` covers the case observed in this
project. Title pattern is needed when multiple Laya projects are open
(e.g., "fish" and "effect" simultaneously) so we focus the right one.
**Important**: the title pattern must match the title bar of the
Laya editor window — this is the *Laya project* name, NOT the id of
the project in our UI. They are usually different (e.g. UI project
id ``fish_1580`` while the Laya editor is open in a project called
``effect`` that includes ``assets/resources/play/fish/1580/...``).

Cross-platform
--------------

This module is Windows-only. On macOS/Linux it returns a friendly
"unsupported" :class:`FocusResult` with ``success=False`` and never
raises, so the rest of the pipeline can keep working (just without the
focus benefit).
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------
# Public types


@dataclass(frozen=True)
class FocusTarget:
    """How to identify the Laya editor window to focus.

    Both fields are case-insensitive. Each accepts either a substring or
    a regex (we try regex first; if it fails to compile we fall back to
    substring). Empty string means "match any".

    If both are non-empty, both must match. The first window found in
    the OS's enumeration order wins.
    """

    process_pattern: str = "LayaAirIDE"
    title_pattern: str = ""


@dataclass
class FocusResult:
    """Outcome of a single :func:`focus_laya_window` call."""

    success: bool
    reason: str
    hwnd: int | None = None
    title: str | None = None
    process_name: str | None = None
    candidates_sample: list[dict[str, Any]] = field(default_factory=list)
    platform: str = sys.platform

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WindowRect:
    """The bounding rectangle of a window in absolute screen pixel coords.

    ``left, top`` is the top-left corner; ``right, bottom`` is exclusive
    bottom-right (Win32 convention). Width = right - left, height =
    bottom - top.

    Used by the "anchor capture region to Laya window" feature in
    ``screen_capture`` so the user can drag/resize the Laya editor
    window between auto-adjust runs without invalidating the capture
    region — the region is stored as offsets from the window's
    top-left, and the absolute coordinates are recomputed every
    capture from the live :class:`WindowRect`.
    """

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def to_dict(self) -> dict[str, int]:
        return {"left": self.left, "top": self.top, "right": self.right, "bottom": self.bottom}


# ---------------------------------------------------------------------
# Public API


def focus_laya_window(
    target: FocusTarget | None = None,
    *,
    settle_ms: int = 250,
    sleep_fn=time.sleep,
) -> FocusResult:
    """Find and bring the Laya editor window to the foreground.

    Returns a :class:`FocusResult`. ``success=False`` is non-fatal —
    the caller should continue but record the failure so the user can
    diagnose (e.g., "Laya window was minimized and Windows refused to
    raise it; please click the Laya window once").

    On non-Windows platforms always returns ``success=False`` with
    ``reason='unsupported_platform'``.
    """

    target = target or FocusTarget()
    if not sys.platform.startswith("win"):
        return FocusResult(
            success=False,
            reason="unsupported_platform",
            platform=sys.platform,
        )

    try:
        hwnd, title, proc_name, candidates = _find_window_win32(target)
    except Exception as exc:  # noqa: BLE001
        return FocusResult(
            success=False,
            reason=f"window enumeration failed: {type(exc).__name__}: {exc}",
        )

    if hwnd is None:
        return FocusResult(
            success=False,
            reason=(
                f"no visible top-level window matched process={target.process_pattern!r}"
                + (f" + title={target.title_pattern!r}" if target.title_pattern else "")
            ),
            candidates_sample=candidates[:20],
        )

    try:
        ok = _bring_to_foreground_win32(hwnd)
    except Exception as exc:  # noqa: BLE001
        return FocusResult(
            success=False,
            reason=f"SetForegroundWindow raised: {type(exc).__name__}: {exc}",
            hwnd=hwnd,
            title=title,
            process_name=proc_name,
        )

    if settle_ms > 0:
        sleep_fn(max(settle_ms, 0) / 1000.0)

    return FocusResult(
        success=ok,
        reason="ok" if ok else (
            "SetForegroundWindow returned 0; Windows may have blocked the focus "
            "switch (try clicking the Laya window once, or shorten the time "
            "between probe runs)"
        ),
        hwnd=hwnd,
        title=title,
        process_name=proc_name,
    )


def list_visible_windows() -> list[dict[str, Any]]:
    """Diagnostic helper: list all visible top-level windows + process names."""
    if not sys.platform.startswith("win"):
        return []
    return _enumerate_visible_windows_win32()


def get_laya_window_rect(target: FocusTarget | None = None) -> WindowRect | None:
    """Find the Laya editor window matching ``target`` and return its
    bounding rectangle in absolute screen coords. Returns ``None`` if
    not found, or on non-Windows platforms.

    Used by the screen capture path's "anchor to window" mode: when the
    user has marked the capture region as relative to the Laya window,
    we call this every capture to find where the window currently
    lives, then add the stored offsets to get fresh absolute coords.

    Note: this does NOT raise the window to the foreground. Pair it
    with :func:`focus_laya_window` if you need both.
    """
    target = target or FocusTarget()
    if not sys.platform.startswith("win"):
        return None
    try:
        hwnd, _title, _proc, _candidates = _find_window_win32(target)
    except Exception:  # noqa: BLE001
        return None
    if hwnd is None:
        return None
    try:
        return _get_window_rect_win32(hwnd)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------
# Win32 plumbing (only imported on Windows)


def _user32():
    import ctypes
    return ctypes.WinDLL("user32", use_last_error=True)


def _kernel32():
    import ctypes
    return ctypes.WinDLL("kernel32", use_last_error=True)


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SW_RESTORE = 9
_SW_SHOWNORMAL = 1
_SW_SHOW = 5


def _get_window_title(hwnd: int) -> str:
    import ctypes
    user32 = _user32()
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_process_name(pid: int) -> str:
    """Return the .exe stem (e.g., 'LayaAirIDE') for a given PID, or ''."""
    import ctypes
    from ctypes import wintypes

    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        ok = kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        )
        if not ok:
            return ""
        return Path(buf.value).stem  # 'C:\\...\\LayaAirIDE.exe' → 'LayaAirIDE'
    finally:
        kernel32.CloseHandle(handle)


def _enumerate_visible_windows_win32() -> list[dict[str, Any]]:
    import ctypes
    from ctypes import wintypes

    user32 = _user32()
    results: list[dict[str, Any]] = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(  # noqa: N806 — Win32 naming
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    @EnumWindowsProc
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _get_window_title(hwnd)
        if not title:
            return True
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = _get_process_name(int(pid.value))
        results.append({
            "hwnd": int(hwnd),
            "title": title,
            "process": proc,
            "pid": int(pid.value),
        })
        return True

    user32.EnumWindows(callback, 0)
    return results


def _make_matcher(pattern: str):
    """Build a callable(text) -> bool. Tries regex first, falls back to
    case-insensitive substring."""
    pattern = (pattern or "").strip()
    if not pattern:
        return lambda _text: True
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        return lambda text: bool(regex.search(text or ""))
    except re.error:
        lc = pattern.lower()
        return lambda text: lc in (text or "").lower()


def _find_window_win32(
    target: FocusTarget,
) -> tuple[int | None, str | None, str | None, list[dict[str, Any]]]:
    candidates = _enumerate_visible_windows_win32()
    process_match = _make_matcher(target.process_pattern)
    title_match = _make_matcher(target.title_pattern)
    for entry in candidates:
        if process_match(entry["process"]) and title_match(entry["title"]):
            return entry["hwnd"], entry["title"], entry["process"], candidates
    return None, None, None, candidates


def _get_window_rect_win32(hwnd: int) -> WindowRect:
    """Return the visible bounding rect of ``hwnd`` in screen pixels.

    Uses ``DwmGetWindowAttribute`` with ``DWMWA_EXTENDED_FRAME_BOUNDS``
    when available — that returns the *visible* bounds excluding the
    invisible drop-shadow margin that ``GetWindowRect`` includes on
    Win10+. Falls back to ``GetWindowRect`` if the DWM call is not
    available (e.g. classic theme).
    """
    import ctypes
    from ctypes import wintypes

    user32 = _user32()

    # Try DwmGetWindowAttribute first — gives the rect users actually see.
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    except OSError:
        dwmapi = None

    if dwmapi is not None:
        rect = wintypes.RECT()
        try:
            hr = dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            if hr == 0:
                return WindowRect(
                    left=int(rect.left),
                    top=int(rect.top),
                    right=int(rect.right),
                    bottom=int(rect.bottom),
                )
        except (AttributeError, OSError):
            pass

    # Fallback: GetWindowRect (includes drop shadow on Win10+).
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise OSError(f"GetWindowRect failed for hwnd={hwnd}")
    return WindowRect(
        left=int(rect.left),
        top=int(rect.top),
        right=int(rect.right),
        bottom=int(rect.bottom),
    )


def _bring_to_foreground_win32(hwnd: int) -> bool:
    """Restore (if minimized) and SetForegroundWindow.

    Uses the AttachThreadInput trick to bypass Windows' standard
    SetForegroundWindow restrictions. As a last resort, simulates an
    Alt key press, which makes Windows think the user just did
    something and lifts the foreground-set restriction.
    """
    import ctypes
    from ctypes import wintypes

    user32 = _user32()
    kernel32 = _kernel32()

    user32.ShowWindow(hwnd, _SW_RESTORE)

    fg_hwnd = user32.GetForegroundWindow()
    if int(fg_hwnd or 0) == int(hwnd):
        return True

    fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    current_thread = kernel32.GetCurrentThreadId()

    attached_fg = False
    attached_target = False
    try:
        if fg_thread and fg_thread != current_thread:
            attached_fg = bool(user32.AttachThreadInput(current_thread, fg_thread, True))
        if target_thread and target_thread != current_thread:
            attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))

        user32.BringWindowToTop(hwnd)
        user32.ShowWindow(hwnd, _SW_SHOW)
        success = bool(user32.SetForegroundWindow(hwnd))
        if not success:
            # Last-ditch: simulate ALT key down/up so Windows lifts the
            # SetForegroundWindow restriction, then try again.
            _send_alt_keypress()
            success = bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached_fg:
            user32.AttachThreadInput(current_thread, fg_thread, False)
        if attached_target:
            user32.AttachThreadInput(current_thread, target_thread, False)

    if success:
        return True
    # Confirm via GetForegroundWindow in case SFW returned 0 but the
    # window actually came up (race conditions are common here).
    return int(user32.GetForegroundWindow() or 0) == int(hwnd)


def _send_alt_keypress() -> None:
    import ctypes
    from ctypes import wintypes

    user32 = _user32()
    VK_MENU = 0x12  # ALT
    KEYEVENTF_KEYUP = 0x0002
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)


__all__ = [
    "FocusResult",
    "FocusTarget",
    "WindowRect",
    "focus_laya_window",
    "get_laya_window_rect",
    "list_visible_windows",
]
