from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_CAPTURE_DIR = Path(__file__).resolve().parent / "test_image"
DEFAULT_STATE_FILE = DEFAULT_CAPTURE_DIR / ".capture_region.json"
DEFAULT_PREFIX = "laya_candidate"


@dataclass(frozen=True)
class CaptureRegion:
    """Screen capture rectangle in desktop coordinates."""

    x: int
    y: int
    width: int
    height: int

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)


@dataclass(frozen=True)
class CaptureAnchor:
    """Capture region anchored to a Laya editor window's top-left corner.

    When ``enabled``, the absolute capture coordinates are recomputed at
    every ``capture_laya_region`` call by looking up the Laya window's
    *current* position via :func:`tools.material_fit.laya.window_focus.get_laya_window_rect`
    and adding ``(offset_x, offset_y)``. This makes the capture region
    survive the user dragging or resizing the Laya editor between runs.

    Width/height stay fixed: we still capture the same model area,
    just at wherever the Laya window happens to be now.

    If the Laya window cannot be found at capture time (Laya closed,
    title pattern stale), :func:`capture_laya_region` falls back to the
    last-known absolute region rather than raising — the caller's
    diagnostic ``anchor_resolution`` field tells them what happened so
    the UI can warn the user.
    """

    enabled: bool = False
    offset_x: int = 0
    offset_y: int = 0
    width: int = 0
    height: int = 0
    process_pattern: str = "LayaAirIDE"
    title_pattern: str = ""


def parse_region(value: str) -> CaptureRegion:
    """Parse `x,y,width,height` into a CaptureRegion."""

    parts = [part.strip() for part in value.replace("，", ",").split(",")]
    if len(parts) != 4:
        raise ValueError("region must be formatted as x,y,width,height")
    x, y, width, height = [int(float(part)) for part in parts]
    if width <= 0 or height <= 0:
        raise ValueError("region width and height must be positive")
    return CaptureRegion(x=x, y=y, width=width, height=height)


def load_last_region(state_file: str | Path = DEFAULT_STATE_FILE) -> CaptureRegion | None:
    path = Path(state_file)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return CaptureRegion(
        x=int(data["x"]),
        y=int(data["y"]),
        width=int(data["width"]),
        height=int(data["height"]),
    )


def save_last_region(region: CaptureRegion, state_file: str | Path = DEFAULT_STATE_FILE) -> None:
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(region), ensure_ascii=False, indent=2), encoding="utf-8")


def find_latest_candidate(capture_dir: str | Path = DEFAULT_CAPTURE_DIR, prefix: str = DEFAULT_PREFIX) -> Path | None:
    """Return the numerically latest `prefix_XX.png` candidate.

    A legacy `prefix.png` is returned only when no numbered candidate exists.
    """

    directory = Path(capture_dir)
    if not directory.exists():
        return None

    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)\.png$", re.IGNORECASE)
    numbered: list[tuple[int, Path]] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = pattern.match(path.name)
        if match:
            numbered.append((int(match.group(1)), path))
    if numbered:
        return max(numbered, key=lambda item: item[0])[1]
    legacy = directory / f"{prefix}.png"
    return legacy if legacy.exists() else None


def next_candidate_path(capture_dir: str | Path = DEFAULT_CAPTURE_DIR, prefix: str = DEFAULT_PREFIX) -> Path:
    directory = Path(capture_dir)
    directory.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)\.png$", re.IGNORECASE)
    max_index = 0
    for path in directory.iterdir():
        match = pattern.match(path.name)
        if match:
            max_index = max(max_index, int(match.group(1)))
    return directory / f"{prefix}_{max_index + 1:02d}.png"


def prune_old_captures(
    capture_dir: str | Path = DEFAULT_CAPTURE_DIR,
    prefix: str = DEFAULT_PREFIX,
    max_keep: int | None = None,
) -> list[Path]:
    """Delete oldest numbered ``prefix_NN.png`` captures past ``max_keep``.

    Auto-adjust appends a fresh ``laya_candidate_NN.png`` per iteration,
    so over many runs the capture pool grows without bound. Callers can
    pass ``max_keep`` to retain only the N most recent captures (ranked
    by the trailing index, which is monotonically increasing per
    :func:`next_candidate_path`). Returns the list of deleted paths so
    the caller can log/diagnose.

    ``max_keep`` of ``None`` or ``<= 0`` is a no-op so the legacy
    "keep everything" behavior remains the default.
    """

    if max_keep is None or max_keep <= 0:
        return []

    directory = Path(capture_dir)
    if not directory.exists():
        return []

    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)\.png$", re.IGNORECASE)
    numbered: list[tuple[int, Path]] = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = pattern.match(path.name)
        if match:
            numbered.append((int(match.group(1)), path))

    if len(numbered) <= max_keep:
        return []

    numbered.sort(key=lambda item: item[0])
    excess = len(numbered) - max_keep
    deleted: list[Path] = []
    for _, path in numbered[:excess]:
        try:
            path.unlink()
        except OSError:
            continue
        deleted.append(path)
    return deleted


def select_region_interactively() -> CaptureRegion:
    """Let the user drag a rectangle on screen using a transparent Tk overlay."""

    import tkinter as tk

    root = tk.Tk()
    root.title("Select Laya capture region")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.28)
    root.configure(bg="black")

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    canvas = tk.Canvas(root, width=screen_width, height=screen_height, cursor="crosshair", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        screen_width // 2,
        36,
        text="拖拽选择 Laya 截图区域；松开鼠标确认；按 Esc 取消",
        fill="white",
        font=("Microsoft YaHei UI", 16, "bold"),
    )

    start: dict[str, int] = {}
    selected: dict[str, CaptureRegion] = {}
    rect_id: dict[str, int | None] = {"value": None}

    def on_down(event: tk.Event) -> None:
        start["x"] = int(event.x_root)
        start["y"] = int(event.y_root)
        if rect_id["value"] is not None:
            canvas.delete(rect_id["value"])
        rect_id["value"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#00ff66", width=3)

    def on_drag(event: tk.Event) -> None:
        if rect_id["value"] is None:
            return
        canvas.coords(rect_id["value"], start["x"], start["y"], event.x_root, event.y_root)

    def on_up(event: tk.Event) -> None:
        x1, y1 = start.get("x", int(event.x_root)), start.get("y", int(event.y_root))
        x2, y2 = int(event.x_root), int(event.y_root)
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        width = right - left
        height = bottom - top
        if width >= 4 and height >= 4:
            selected["region"] = CaptureRegion(left, top, width, height)
            root.quit()

    def on_cancel(_event: tk.Event | None = None) -> None:
        root.quit()

    canvas.bind("<ButtonPress-1>", on_down)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_up)
    root.bind("<Escape>", on_cancel)
    root.mainloop()
    root.destroy()

    region = selected.get("region")
    if not region:
        raise RuntimeError("capture region selection was cancelled")
    return region


def capture_region(region: CaptureRegion, output_path: str | Path) -> Path:
    """Capture a desktop rectangle to a PNG file."""

    from PIL import ImageGrab

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        image = ImageGrab.grab(bbox=region.bbox, all_screens=True)
    except TypeError:
        image = ImageGrab.grab(bbox=region.bbox)
    image.save(path)
    return path


def resolve_anchored_region(
    anchor: CaptureAnchor,
    fallback: CaptureRegion | None,
) -> tuple[CaptureRegion | None, dict[str, Any]]:
    """Compute the absolute :class:`CaptureRegion` for an anchored config.

    Looks up the Laya window's current rect; if found, returns
    ``(window.left + offset_x, window.top + offset_y, width, height)``.
    If not found, falls back to ``fallback`` so the caller still gets
    *something* to capture rather than crashing — the second element
    of the return tuple records what actually happened so UIs can warn
    the user about a stale anchor.
    """

    diagnostic: dict[str, Any] = {
        "anchor_enabled": anchor.enabled,
        "process_pattern": anchor.process_pattern,
        "title_pattern": anchor.title_pattern,
        "offset": {"x": anchor.offset_x, "y": anchor.offset_y},
        "size": {"width": anchor.width, "height": anchor.height},
    }
    try:
        # Local import keeps ``screen_capture`` portable on platforms
        # where window_focus isn't useful (it returns None on non-Win).
        from tools.material_fit.laya.window_focus import (
            FocusTarget,
            get_laya_window_rect,
        )
    except ImportError as exc:  # noqa: BLE001
        diagnostic["status"] = "import_failed"
        diagnostic["reason"] = f"failed to import window_focus: {exc}"
        return fallback, diagnostic

    rect = get_laya_window_rect(
        FocusTarget(
            process_pattern=anchor.process_pattern,
            title_pattern=anchor.title_pattern,
        )
    )
    if rect is None:
        diagnostic["status"] = "window_not_found"
        diagnostic["reason"] = (
            "could not find a Laya window matching the configured "
            "process/title pattern; falling back to last absolute region"
        )
        diagnostic["fallback_used"] = fallback is not None
        return fallback, diagnostic

    abs_x = int(rect.left) + int(anchor.offset_x)
    abs_y = int(rect.top) + int(anchor.offset_y)
    width = int(anchor.width) if anchor.width > 0 else (fallback.width if fallback else 0)
    height = int(anchor.height) if anchor.height > 0 else (fallback.height if fallback else 0)
    if width <= 0 or height <= 0:
        diagnostic["status"] = "invalid_size"
        diagnostic["reason"] = "anchor width/height must be positive"
        return fallback, diagnostic

    diagnostic["status"] = "anchored"
    diagnostic["window_rect"] = rect.to_dict()
    diagnostic["resolved_absolute"] = {"x": abs_x, "y": abs_y, "width": width, "height": height}
    return CaptureRegion(x=abs_x, y=abs_y, width=width, height=height), diagnostic


def capture_laya_region(
    *,
    region: CaptureRegion | None = None,
    reuse_last: bool = False,
    capture_dir: str | Path = DEFAULT_CAPTURE_DIR,
    state_file: str | Path | None = None,
    prefix: str = DEFAULT_PREFIX,
    dry_run: bool = False,
    anchor: CaptureAnchor | None = None,
    output_path: str | Path | None = None,
    max_keep: int | None = None,
) -> dict[str, Any]:
    """Capture a desktop region as a PNG.

    ``output_path``
        When provided, write directly to this path (overwriting any
        existing file). Use this for fixed-name slots like the refresh
        probe's ``baseline.png``/``probe.png``/``restored.png``: those
        callers want exactly one file per slot, not a rolling
        ``laya_candidate_NN.png`` pool. The rolling-pool pruning is
        also skipped in this mode (a fixed-name file is its own
        retention policy).

    ``max_keep``
        Only meaningful when ``output_path`` is ``None`` (i.e., the
        caller is appending to the rolling ``prefix_NN.png`` pool).
        After the new capture is written, deletes any oldest numbered
        captures past ``max_keep`` so the auto-adjust loop doesn't
        leak gigabytes of historical screenshots over weeks of runs.
        ``None`` (default) preserves legacy "keep everything"
        behavior. The list of deleted paths is exposed in the return
        dict's ``pruned`` key for diagnostics.
    """
    directory = Path(capture_dir)
    state_path = Path(state_file) if state_file else directory / ".capture_region.json"

    # If an anchor is enabled, it OVERRIDES any explicit absolute
    # region — the whole point of anchoring is that the user's stored
    # absolute coords go stale the moment the Laya window moves.
    anchor_resolution: dict[str, Any] | None = None
    if anchor is not None and anchor.enabled:
        fallback = region
        if fallback is None and reuse_last:
            fallback = load_last_region(state_path)
        anchored_region, anchor_resolution = resolve_anchored_region(anchor, fallback)
        if anchored_region is not None:
            region = anchored_region
            reuse_last = False  # we just resolved it fresh; don't override

    selected_region = region
    source = "explicit"
    if selected_region is None and reuse_last:
        selected_region = load_last_region(state_path)
        source = "last"
    if selected_region is None:
        selected_region = select_region_interactively()
        source = "interactive"
    if anchor_resolution is not None:
        if anchor_resolution.get("status") == "anchored":
            source = "anchored"
        else:
            source = "anchor_fallback"

    save_last_region(selected_region, state_path)

    pruned: list[Path] = []
    if output_path is not None:
        resolved_output = Path(output_path)
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        used_fixed_path = True
    else:
        resolved_output = next_candidate_path(directory, prefix)
        used_fixed_path = False

    if not dry_run:
        capture_region(selected_region, resolved_output)
        if not used_fixed_path and max_keep is not None and max_keep > 0:
            pruned = prune_old_captures(directory, prefix, max_keep)

    return {
        "status": "ok",
        "output_path": str(resolved_output),
        "region": asdict(selected_region),
        "region_source": source,
        "reuse_last": reuse_last,
        "state_file": str(state_path),
        "dry_run": dry_run,
        "anchor_resolution": anchor_resolution,
        "fixed_output_path": used_fixed_path,
        "max_keep": max_keep,
        "pruned": [str(p) for p in pruned],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a selected desktop region as the latest Laya candidate image")
    parser.add_argument("--region", default="", help="Capture rectangle formatted as x,y,width,height")
    parser.add_argument("--reuse-last", action="store_true", help="Use the last saved capture rectangle; ask once if missing")
    parser.add_argument("--output-dir", default=str(DEFAULT_CAPTURE_DIR), help="Directory to save laya_candidate_XX.png")
    parser.add_argument("--state-file", default="", help="Region state JSON path; defaults to <output-dir>/.capture_region.json")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="Candidate image filename prefix")
    parser.add_argument("--dry-run", action="store_true", help="Resolve region/output path without taking a screenshot")
    parser.add_argument(
        "--max-keep",
        type=int,
        default=0,
        help=(
            "If > 0, after writing this capture also prune the rolling "
            "prefix_NN.png pool down to this many most-recent files."
        ),
    )
    parser.add_argument(
        "--output-path",
        default="",
        help=(
            "Force writing to this exact path instead of the rolling "
            "prefix_NN.png pool (used by callers like the refresh "
            "probe that want a fixed slot)."
        ),
    )
    args = parser.parse_args()

    explicit_region = parse_region(args.region) if args.region else None
    result = capture_laya_region(
        region=explicit_region,
        reuse_last=args.reuse_last,
        capture_dir=args.output_dir,
        state_file=args.state_file or None,
        prefix=args.prefix,
        dry_run=args.dry_run,
        output_path=args.output_path or None,
        max_keep=args.max_keep if args.max_keep > 0 else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())