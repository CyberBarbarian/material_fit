"""Validate a checkout before starting a real material-fit experiment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from material_fit.assets.fish_scene import resolve_fish_scene_assets
from material_fit.assets.material_stage1 import resolve_material_stage1_asset
from material_fit.assets.stage2_unity_references import (
    audit_stage2_unity_references,
    resolve_stage2_unity_references,
)
from material_fit.experiments.stage1_profiles import (
    JOINT_PROFILE_V30,
    JOINT_PROFILE_V42,
    JOINT_PROFILE_V85,
    JOINT_PROFILE_V86,
    joint_profile_policy,
)


ENGINE_FILES = {
    "laya.core.js": "d3b3cd2a0b9f88d5ab350ea11f291f96187189d3fafb39d4e8b35c216ad2058d",
    "laya.webgl_2D.js": "bb509d2d6e6c0d6428a12fb6ba5bab9cb1a9028b7fa4272592608d14fac29eca",
    "laya.d3.js": "c69439733372cd0541d0c0d3a19b1d48b302407728929c938653396f816ea538",
    "laya.webgl_3D.js": "6bbcfa639c97f97bba0f6234bceef6eb7a82395cd9b9a97f1b2e2e5cfce20b02",
    "laya.ani.js": "38a38ff70dc18a81c724d2c02cd79676eab4c9932eb45795c82d74849a923c09",
    "laya.particleCommon.js": "ff1739e819a77d10e328c995e445626f261d5bab54563237abe44c295ae37fd6",
    "laya.particle3D.js": "2e017e4f2ed4dae482acb189d6fcbdaffcee34f422f6be1a93dd3e867e602fee",
    "laya.trailCommon.js": "2ef54a59ace2cb3c2d1d3346b09749ce2948ee832a20a04eaa7d598267007b60",
    "laya.trail3D.js": "76c06bf63e17310627821813b9b0d9b65a9eaa7a41c446ed03c5abbc5bc4e78f",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_checkout(Path(args.repo_root))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for check in report["checks"]:
            status = "OK" if check["ok"] else "FAIL"
            print(f"[{status}] {check['name']}: {check['detail']}")
        print("checkout is ready" if report["ok"] else "checkout is not ready")
    return 0 if report["ok"] else 1


def inspect_checkout(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve()
    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "python",
            sys.version_info >= (3, 10),
            f"{platform.python_version()} at {sys.executable}",
        )
    )

    perceptual_packages = ("DISTS_pytorch", "lpips", "torch", "torchvision")
    missing_perceptual = [
        package
        for package in perceptual_packages
        if importlib.util.find_spec(package) is None
    ]
    perceptual_detail = (
        ", ".join(missing_perceptual)
        if missing_perceptual
        else ", ".join(
            f"{package} {importlib.metadata.version(package)}"
            for package in perceptual_packages
        )
    )
    checks.append(
        _check(
            "stage2-perceptual",
            not missing_perceptual,
            perceptual_detail,
        )
    )

    node_executable = _node_executable(root)
    node = _run([node_executable, "--version"], cwd=root)
    node_major = _version_major(node["stdout"])
    checks.append(
        _check(
            "node",
            node["returncode"] == 0 and node_major >= 18,
            node["stdout"] or node["stderr"] or "node was not found",
        )
    )

    package_path = root / "node_modules" / "playwright" / "package.json"
    package_version = "missing"
    if package_path.is_file():
        package_version = str(json.loads(package_path.read_text(encoding="utf-8"))["version"])
    checks.append(_check("playwright-package", package_version == "1.61.1", package_version))

    browser = _run(
        [node_executable, "scripts/check_playwright.js"],
        cwd=root,
        timeout=45,
    )
    checks.append(
        _check(
            "chromium",
            browser["returncode"] == 0,
            browser["stdout"] or browser["stderr"] or "browser failed its launch check",
        )
    )

    engine_root = root / "vendor" / "layaair-3.4.0" / "libs"
    engine_errors = []
    for name, expected in ENGINE_FILES.items():
        path = engine_root / name
        if not path.is_file():
            engine_errors.append(f"missing {name}")
        elif _sha256(path) != expected:
            engine_errors.append(f"hash mismatch {name}")
    checks.append(
        _check(
            "laya-engine",
            not engine_errors,
            ", ".join(engine_errors) if engine_errors else "LayaAir 3.4.0 vendored runtime",
        )
    )

    try:
        assets = resolve_fish_scene_assets(root)
        asset_detail = assets.asset_set_name
        asset_ok = True
    except Exception as exc:  # noqa: BLE001 - doctor reports every failed contract
        asset_detail = str(exc)
        asset_ok = False
    checks.append(_check("fish-assets", asset_ok, asset_detail))

    for asset_id in ("turtle", "crocodile"):
        try:
            asset = resolve_material_stage1_asset(root, asset_id)
            required = (
                asset.project_root,
                asset.scene_path,
                asset.shader_path,
                asset.start_material_path,
                asset.target_material_path,
            )
            missing = [str(path) for path in required if not path.exists()]
            detail = "all runtime files present" if not missing else ", ".join(missing)
            ok = not missing
        except Exception as exc:  # noqa: BLE001 - doctor reports every failed contract
            detail = str(exc)
            ok = False
        checks.append(_check(f"{asset_id}-assets", ok, detail))

    try:
        profiles = [
            joint_profile_policy(profile)["runtime_profile"]
            for profile in (
                JOINT_PROFILE_V30,
                JOINT_PROFILE_V42,
                JOINT_PROFILE_V85,
                JOINT_PROFILE_V86,
            )
        ]
        profile_detail = f"{len(profiles)} verified policy snapshots"
        profile_ok = True
    except Exception as exc:  # noqa: BLE001 - doctor reports every failed contract
        profile_detail = str(exc)
        profile_ok = False
    checks.append(_check("stage1-policy", profile_ok, profile_detail))

    stage2_reports: list[dict[str, Any]] = []
    stage2_errors: list[str] = []
    for asset_id in ("crocodile", "fish", "turtle"):
        try:
            reference_set = resolve_stage2_unity_references(root, asset_id)
            report = audit_stage2_unity_references(reference_set)
            stage2_reports.append(report)
            if not report["passed"]:
                stage2_errors.extend(str(value) for value in report["structural_errors"])
        except Exception as exc:  # noqa: BLE001 - doctor reports every failed contract
            stage2_errors.append(f"{asset_id}: {exc}")
    geometry_ready_count = sum(bool(report["geometry_ready"]) for report in stage2_reports)
    stage2_detail = (
        ", ".join(stage2_errors)
        if stage2_errors
        else f"3 structurally valid sets; {geometry_ready_count}/3 geometry-ready"
    )
    checks.append(_check("stage2-unity-references", not stage2_errors and len(stage2_reports) == 3, stage2_detail))
    return {
        "schema_version": 1,
        "repo_root": str(root),
        "platform": platform.platform(),
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
    }


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": str(detail).strip()}


def _run(command: list[str], *, cwd: Path, timeout: float = 20) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc)}


def _version_major(raw: str) -> int:
    try:
        return int(raw.strip().lstrip("v").split(".", 1)[0])
    except (TypeError, ValueError):
        return -1


def _node_executable(root: Path) -> str:
    local = root / ".runtime" / "node" / "bin" / "node"
    if local.is_file():
        return str(local)
    return "node"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
