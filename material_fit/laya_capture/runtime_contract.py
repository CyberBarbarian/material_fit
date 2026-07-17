"""Run a profile-driven persistent Laya visual and speed contract."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .asset_profile import capture_command_from_profile, load_asset_profile, material_patch_from_lmat
from .managed_runtime import ManagedRuntimeRenderer
from .runtime_bridge import RuntimeCaptureBridge


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--reference-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--benchmark-iterations", type=int, default=10)
    parser.add_argument("--timeout-s", type=float, default=90.0)
    parser.add_argument("--node-modules", default="")
    args = parser.parse_args()

    profile_path = Path(args.profile).expanduser().resolve()
    reference_dir = Path(args.reference_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = load_asset_profile(profile_path)
    command = capture_command_from_profile(profile)
    references = _reference_images(command, reference_dir)

    renderer: ManagedRuntimeRenderer | None = None
    startup_started = time.perf_counter()
    report: dict[str, Any] = {
        "schema_version": 1,
        "asset_id": profile.get("asset_id"),
        "profile": str(profile_path),
        "project_root": profile["_project_root"],
        "scene": profile["_scene_path"],
        "reference_dir": str(reference_dir),
        "animation_mode": command.get("animation_mode"),
        "benchmark_iterations": max(0, int(args.benchmark_iterations)),
    }
    try:
        with RuntimeCaptureBridge(host="127.0.0.1", port=0) as bridge:
            renderer = ManagedRuntimeRenderer(
                profile_path=profile_path,
                server_url=bridge.base_url,
                state_dir=output_dir,
                timeout_s=float(args.timeout_s),
                node_modules=args.node_modules,
            )
            ready = renderer.start()
            startup_ms = (time.perf_counter() - startup_started) * 1000.0

            artifact_command = dict(command)
            artifact_command.pop("browser_score", None)
            artifact_command["return_images"] = True
            artifact_started = time.perf_counter()
            artifact_result = bridge.capture(
                artifact_command,
                output_dir=output_dir / "runtime_render",
                timeout_s=float(args.timeout_s),
            )
            artifact_ms = (time.perf_counter() - artifact_started) * 1000.0
            contact_sheet = _build_contact_sheet(
                [Path(path) for path in artifact_result.get("screenshots", [])],
                output_dir / "runtime_eight_views.png",
            )

            external_score_command = dict(command)
            external_score_command["return_images"] = False
            external_score_command["browser_score"] = {
                "enabled": True,
                "metric": "runtime_laya_canvas_mae",
                "rgb_weight": 1.0,
                "alpha_weight": 0.0,
                "reference_images": references,
            }
            external_result = bridge.capture(
                external_score_command,
                output_dir=output_dir / "external_reference_score",
                timeout_s=float(args.timeout_s),
            )

            self_references = [
                {"view_id": str(view["view_id"]), "path": str(path)}
                for view, path in zip(command["views"], artifact_result.get("screenshots", []), strict=True)
            ]
            score_command = dict(command)
            score_command["return_images"] = False
            score_command["browser_score"] = {
                "enabled": True,
                "metric": "runtime_laya_canvas_mae",
                "rgb_weight": 1.0,
                "alpha_weight": 0.0,
                "reference_images": self_references,
            }
            warm_started = time.perf_counter()
            warm_result = bridge.capture(
                score_command,
                output_dir=output_dir / "same_params_score",
                timeout_s=float(args.timeout_s),
            )
            warm_ms = (time.perf_counter() - warm_started) * 1000.0

            iteration_ms: list[float] = []
            scores: list[float] = []
            for index in range(max(0, int(args.benchmark_iterations))):
                started = time.perf_counter()
                result = bridge.capture(
                    score_command,
                    output_dir=output_dir / "benchmark" / f"iteration_{index:04d}",
                    timeout_s=float(args.timeout_s),
                )
                iteration_ms.append((time.perf_counter() - started) * 1000.0)
                score = result.get("browser_score", {}).get("fit_score")
                if score is not None:
                    scores.append(float(score))

            variant_reports = _capture_validation_variants(
                bridge=bridge,
                profile=profile,
                profile_dir=profile_path.parent,
                base_command=command,
                output_dir=output_dir,
                timeout_s=float(args.timeout_s),
            )

            report.update(
                {
                    "ok": True,
                    "renderer_ready": ready,
                    "startup_ms": startup_ms,
                    "artifact_capture_ms": artifact_ms,
                    "warmup_ms": warm_ms,
                    "artifact_pngs": artifact_result.get("screenshots", []),
                    "contact_sheet": str(contact_sheet),
                    "external_reference_score": external_result.get("browser_score"),
                    "validation_variants": variant_reports,
                    "same_params_score": warm_result.get("browser_score"),
                    "benchmark": _timing_summary(iteration_ms),
                    "score_min": min(scores) if scores else None,
                    "score_max": max(scores) if scores else None,
                    "iteration_png_count": len(list((output_dir / "benchmark").rglob("*.png"))),
                }
            )
    except Exception as exc:  # noqa: BLE001
        report.update({"ok": False, "error": str(exc)})
        raise
    finally:
        cleanup = renderer.stop() if renderer is not None else {"ok": True, "reason": "not_started"}
        report["renderer_cleanup"] = cleanup
        (output_dir / "runtime_contract_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _reference_images(command: dict[str, Any], reference_dir: Path) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for view in command["views"]:
        view_id = str(view["view_id"])
        candidates = [
            reference_dir / str(view.get("file_name") or ""),
            reference_dir / f"laya_{view_id}.png",
            reference_dir / f"{view_id}.png",
        ]
        path = next((candidate for candidate in candidates if candidate.name and candidate.is_file()), None)
        if path is None:
            raise FileNotFoundError(f"reference image missing for {view_id}: {reference_dir}")
        references.append({"view_id": view_id, "path": str(path)})
    return references


def _optional_material_patch(value: Any, profile_dir: Path) -> dict[str, Any] | None:
    if value is None or str(value).strip() == "":
        return None
    path = Path(str(value)).expanduser()
    path = (path if path.is_absolute() else profile_dir / path).resolve()
    return material_patch_from_lmat(path)


def _capture_validation_variants(
    *,
    bridge: RuntimeCaptureBridge,
    profile: dict[str, Any],
    profile_dir: Path,
    base_command: dict[str, Any],
    output_dir: Path,
    timeout_s: float,
) -> list[dict[str, Any]]:
    raw_variants = profile.get("validation_variants")
    if not isinstance(raw_variants, list):
        return []
    reports: list[dict[str, Any]] = []
    for index, raw_variant in enumerate(raw_variants):
        if not isinstance(raw_variant, dict):
            raise ValueError(f"validation variant {index} must be an object")
        name = str(raw_variant.get("name") or f"variant_{index}")
        raw_patch = raw_variant.get("material_patch")
        patch = json.loads(json.dumps(raw_patch)) if isinstance(raw_patch, dict) else _optional_material_patch(
            raw_variant.get("material"), profile_dir
        )
        if patch is None:
            raise ValueError(f"validation variant {name} is missing material or material_patch")
        if raw_variant.get("include_defines") is False:
            patch.pop("defines", None)
        command = dict(base_command)
        command["material_patch"] = patch
        command.pop("browser_score", None)
        command["return_images"] = True
        variant_dir = output_dir / f"runtime_{name}"
        started = time.perf_counter()
        result = bridge.capture(command, output_dir=variant_dir, timeout_s=timeout_s)
        capture_ms = (time.perf_counter() - started) * 1000.0
        sheet = _build_contact_sheet(
            [Path(path) for path in result.get("screenshots", [])],
            output_dir / f"runtime_{name}_eight_views.png",
        )
        variant_report: dict[str, Any] = {
            "name": name,
            "capture_ms": capture_ms,
            "pngs": result.get("screenshots", []),
            "contact_sheet": str(sheet),
            "material_value_count": len(patch.get("values", {})),
            "enabled_defines": patch.get("defines", {}).get("enabled", []) if isinstance(patch.get("defines"), dict) else [],
        }
        reference_value = raw_variant.get("reference_dir")
        if reference_value:
            reference_path = Path(str(reference_value)).expanduser()
            reference_path = (reference_path if reference_path.is_absolute() else profile_dir / reference_path).resolve()
            score_command = dict(command)
            score_command["return_images"] = False
            score_command["browser_score"] = {
                "enabled": True,
                "metric": "runtime_laya_canvas_mae",
                "rgb_weight": 1.0,
                "alpha_weight": 0.0,
                "reference_images": _reference_images(score_command, reference_path),
            }
            score_result = bridge.capture(
                score_command,
                output_dir=output_dir / f"{name}_external_reference_score",
                timeout_s=timeout_s,
            )
            variant_report["external_reference_dir"] = str(reference_path)
            variant_report["external_reference_score"] = score_result.get("browser_score")
        reports.append(variant_report)
    return reports


def _timing_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean_ms": statistics.fmean(values),
        "p50_ms": statistics.median(values),
        "p95_ms": ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
        "values_ms": values,
    }


def _build_contact_sheet(paths: list[Path], output_path: Path) -> Path:
    if not paths:
        raise ValueError("runtime capture returned no PNGs for contact sheet")
    images = [Image.open(path).convert("RGB") for path in paths]
    panel_width = 450
    panel_height = 272
    label_height = 24
    columns = 4
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * panel_width, rows * (panel_height + label_height)), (245, 247, 250))
    draw = ImageDraw.Draw(sheet)
    for index, (path, image) in enumerate(zip(paths, images, strict=True)):
        image.thumbnail((panel_width, panel_height), Image.Resampling.LANCZOS)
        row, column = divmod(index, columns)
        x = column * panel_width
        y = row * (panel_height + label_height)
        sheet.paste(image, (x + (panel_width - image.width) // 2, y))
        draw.text((x + 8, y + panel_height + 4), path.stem, fill=(25, 29, 36))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return output_path


if __name__ == "__main__":
    raise SystemExit(main())
