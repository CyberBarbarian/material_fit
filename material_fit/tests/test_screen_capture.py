"""Unit tests for :mod:`tools.material_fit.vision.screen_capture`.

These cover the E-012 changes:

* :func:`prune_old_captures` deletes oldest numbered captures past
  ``max_keep`` and is a no-op when ``max_keep`` is ``None`` / ``0``.
* :func:`capture_laya_region` honors an explicit ``output_path``
  (skipping the rolling pool entirely) and reports the fact in the
  diagnostic dict so callers know which slot was written.
* :func:`capture_laya_region` honors ``max_keep`` for the rolling
  pool path, pruning oldest files after each successful write.
* The probe-style fixed-path mode does NOT prune, so passing
  ``max_keep=2`` while writing ``preflight/baseline.png`` does not
  delete the rolling-pool captures sitting next to it.

We monkey-patch ``capture_region`` so the tests don't need a real
display server (Pillow's ``ImageGrab`` is unavailable in CI).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.material_fit.vision import screen_capture as sc


# ---------------------------------------------------------------------
# Helpers


def _touch_capture(path: Path, _region) -> Path:
    """Replacement for ``capture_region`` that writes a 1-byte PNG.

    Avoids any GUI dependency and gives us a real on-disk file so the
    pruning logic has something to delete.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG magic; enough for a file
    return path


@pytest.fixture
def capture_region(tmp_path: Path) -> Path:
    return sc.CaptureRegion(x=0, y=0, width=10, height=10)


@pytest.fixture
def patched_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``capture_region`` (the GDI / Pillow grab) with a stub.

    We capture by file path, not by pixels, so the tests don't care
    what's in the PNG. The stub respects the same signature so the
    production code path is exercised verbatim.
    """

    def stub(region, output_path):
        return _touch_capture(Path(output_path), region)

    monkeypatch.setattr(sc, "capture_region", stub)


# ---------------------------------------------------------------------
# prune_old_captures


def test_prune_old_captures_keeps_latest_n(tmp_path: Path) -> None:
    for i in range(1, 8):  # 7 numbered files
        (tmp_path / f"laya_candidate_{i:02d}.png").write_bytes(b"x")
    (tmp_path / "unrelated.png").write_bytes(b"x")  # must NOT be touched

    deleted = sc.prune_old_captures(tmp_path, "laya_candidate", max_keep=3)

    assert len(deleted) == 4
    survivors = sorted(p.name for p in tmp_path.glob("laya_candidate_*.png"))
    assert survivors == [
        "laya_candidate_05.png",
        "laya_candidate_06.png",
        "laya_candidate_07.png",
    ]
    assert (tmp_path / "unrelated.png").exists()


def test_prune_noop_when_max_keep_none_or_zero(tmp_path: Path) -> None:
    for i in range(1, 6):
        (tmp_path / f"laya_candidate_{i:02d}.png").write_bytes(b"x")

    assert sc.prune_old_captures(tmp_path, "laya_candidate", max_keep=None) == []
    assert sc.prune_old_captures(tmp_path, "laya_candidate", max_keep=0) == []
    assert len(list(tmp_path.glob("laya_candidate_*.png"))) == 5


def test_prune_noop_when_already_under_cap(tmp_path: Path) -> None:
    for i in range(1, 4):
        (tmp_path / f"laya_candidate_{i:02d}.png").write_bytes(b"x")

    deleted = sc.prune_old_captures(tmp_path, "laya_candidate", max_keep=10)

    assert deleted == []
    assert len(list(tmp_path.glob("laya_candidate_*.png"))) == 3


def test_prune_handles_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    assert sc.prune_old_captures(missing, "laya_candidate", max_keep=3) == []


def test_prune_ignores_non_matching_filenames(tmp_path: Path) -> None:
    (tmp_path / "laya_candidate.png").write_bytes(b"x")  # legacy unnumbered
    (tmp_path / "laya_candidate_3.png").write_bytes(b"x")
    (tmp_path / "other_42.png").write_bytes(b"x")

    deleted = sc.prune_old_captures(tmp_path, "laya_candidate", max_keep=1)

    # Only the one numbered file is in scope; both the legacy
    # unnumbered file and the foreign-prefix file survive.
    assert deleted == []
    assert (tmp_path / "laya_candidate.png").exists()
    assert (tmp_path / "other_42.png").exists()


# ---------------------------------------------------------------------
# capture_laya_region: explicit output_path bypasses the rolling pool


def test_capture_with_output_path_writes_fixed_slot_only(
    tmp_path: Path,
    patched_capture: None,
    capture_region,
) -> None:
    fixed = tmp_path / "preflight" / "baseline.png"
    pool_dir = tmp_path / "test_image"
    pool_dir.mkdir()

    result = sc.capture_laya_region(
        region=capture_region,
        capture_dir=pool_dir,
        output_path=fixed,
        prefix="laya_candidate",
    )

    assert fixed.exists()
    # No laya_candidate_NN.png was created in the rolling pool.
    assert list(pool_dir.glob("laya_candidate_*.png")) == []
    assert result["output_path"] == str(fixed)
    assert result["fixed_output_path"] is True
    assert result["pruned"] == []


def test_capture_with_output_path_overwrites_existing_file(
    tmp_path: Path,
    patched_capture: None,
    capture_region,
) -> None:
    fixed = tmp_path / "preflight" / "baseline.png"
    fixed.parent.mkdir(parents=True)
    fixed.write_bytes(b"old-content")
    assert fixed.read_bytes() == b"old-content"

    sc.capture_laya_region(
        region=capture_region,
        capture_dir=tmp_path / "test_image",
        output_path=fixed,
        prefix="laya_candidate",
    )

    # Stub overwrote the file with the PNG magic; assert it's not the
    # old content anymore.
    assert fixed.read_bytes() != b"old-content"


def test_capture_with_output_path_does_not_prune_pool(
    tmp_path: Path,
    patched_capture: None,
    capture_region,
) -> None:
    pool = tmp_path / "test_image"
    pool.mkdir()
    for i in range(1, 6):
        (pool / f"laya_candidate_{i:02d}.png").write_bytes(b"x")

    fixed = tmp_path / "preflight" / "probe.png"

    result = sc.capture_laya_region(
        region=capture_region,
        capture_dir=pool,
        output_path=fixed,
        prefix="laya_candidate",
        max_keep=2,  # would prune to 2 if rolling pool were active
    )

    # Probe-style write does not touch the rolling pool — that's the
    # whole point of the fixed-path mode.
    assert len(list(pool.glob("laya_candidate_*.png"))) == 5
    assert result["pruned"] == []


# ---------------------------------------------------------------------
# capture_laya_region: max_keep on the rolling pool


def test_capture_rolling_pool_prunes_after_write(
    tmp_path: Path,
    patched_capture: None,
    capture_region,
) -> None:
    pool = tmp_path / "test_image"
    pool.mkdir()
    for i in range(1, 6):  # seed pool with 5 files
        (pool / f"laya_candidate_{i:02d}.png").write_bytes(b"x")

    result = sc.capture_laya_region(
        region=capture_region,
        capture_dir=pool,
        prefix="laya_candidate",
        max_keep=3,
    )

    # New capture lands at index 6, then 4 oldest get pruned to keep 3.
    survivors = sorted(p.name for p in pool.glob("laya_candidate_*.png"))
    assert survivors == [
        "laya_candidate_04.png",
        "laya_candidate_05.png",
        "laya_candidate_06.png",
    ]
    assert result["max_keep"] == 3
    assert len(result["pruned"]) == 3  # 01, 02, 03


def test_capture_rolling_pool_no_prune_when_max_keep_none(
    tmp_path: Path,
    patched_capture: None,
    capture_region,
) -> None:
    pool = tmp_path / "test_image"
    pool.mkdir()
    for i in range(1, 6):
        (pool / f"laya_candidate_{i:02d}.png").write_bytes(b"x")

    sc.capture_laya_region(
        region=capture_region,
        capture_dir=pool,
        prefix="laya_candidate",
        max_keep=None,  # legacy behavior
    )

    assert len(list(pool.glob("laya_candidate_*.png"))) == 6  # 5 + new


def test_capture_rolling_pool_no_prune_when_max_keep_zero(
    tmp_path: Path,
    patched_capture: None,
    capture_region,
) -> None:
    pool = tmp_path / "test_image"
    pool.mkdir()
    for i in range(1, 6):
        (pool / f"laya_candidate_{i:02d}.png").write_bytes(b"x")

    sc.capture_laya_region(
        region=capture_region,
        capture_dir=pool,
        prefix="laya_candidate",
        max_keep=0,
    )

    assert len(list(pool.glob("laya_candidate_*.png"))) == 6


def test_capture_dry_run_does_not_prune(
    tmp_path: Path,
    patched_capture: None,
    capture_region,
) -> None:
    pool = tmp_path / "test_image"
    pool.mkdir()
    for i in range(1, 6):
        (pool / f"laya_candidate_{i:02d}.png").write_bytes(b"x")

    result = sc.capture_laya_region(
        region=capture_region,
        capture_dir=pool,
        prefix="laya_candidate",
        max_keep=2,
        dry_run=True,
    )

    # Dry-run should not have touched the disk.
    assert len(list(pool.glob("laya_candidate_*.png"))) == 5
    assert result["pruned"] == []
    assert result["dry_run"] is True
