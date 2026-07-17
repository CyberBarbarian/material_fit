"""Artifact validation and private audit reports for shared Stage 1 runs."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image

from material_fit.assets.material_stage1 import MaterialStage1AssetSpec
from material_fit.experiments import material_phase05_recovery as phase05
from material_fit.laya import lmat_io
from material_fit.optimizer.structured_material_space import (
    STRUCTURED_MATERIAL_PARAM_NAMES,
    STRUCTURED_SCENE_PARAM_NAMES,
    structured_material_coordinates,
)


STAGE1_SEARCH_PARAM_NAMES = (
    *STRUCTURED_MATERIAL_PARAM_NAMES,
    *STRUCTURED_SCENE_PARAM_NAMES,
)
STAGE1_SCORE_READBACK_WIDTH = 720


def _artifact_resolution(
    directory: Path,
    views: list[dict[str, Any]],
) -> list[int]:
    sizes: set[tuple[int, int]] = set()
    for view in views:
        path = directory / str(view["file_name"])
        if not path.is_file():
            raise FileNotFoundError(f"missing Stage 1 artifact PNG: {path}")
        with Image.open(path) as image:
            sizes.add((int(image.width), int(image.height)))
    if len(sizes) != 1:
        raise RuntimeError(f"inconsistent Stage 1 artifact sizes in {directory}: {sorted(sizes)}")
    width, height = next(iter(sizes))
    return [width, height]


def _optimizer_score_resolution(
    profile: dict[str, Any],
    *,
    requested_width: int,
    requested_height: int,
) -> tuple[int, int]:
    """Resolve a bounded score size without changing the asset aspect ratio."""

    profile_width = max(int(profile.get("width") or STAGE1_SCORE_READBACK_WIDTH), 1)
    profile_height = max(int(profile.get("height") or profile_width), 1)
    width = max(int(requested_width), 1)
    height = int(requested_height)
    if height <= 0:
        height = max(int(round(width * profile_height / profile_width)), 1)
    return width, height


def _discrete_alignment_report(
    *,
    asset: MaterialStage1AssetSpec,
    alignment: dict[str, Any],
    original_start: dict[str, Any],
    aligned_start: dict[str, Any],
    target: dict[str, Any],
    target_patch: dict[str, Any],
    aligned_patch: dict[str, Any],
) -> dict[str, Any]:
    original_params = lmat_io.extract_params(original_start)
    aligned_params = lmat_io.extract_params(aligned_start)
    continuous_differences = {
        name: {"original": original_params.get(name), "aligned": aligned_params.get(name)}
        for name in STAGE1_SEARCH_PARAM_NAMES
        if original_params.get(name) != aligned_params.get(name)
    }
    target_state = lmat_io.extract_discrete_state(target)
    aligned_state = lmat_io.extract_discrete_state(aligned_start)
    target_textures = lmat_io.extract_textures(target)
    original_textures = lmat_io.extract_textures(original_start)
    aligned_textures = lmat_io.extract_textures(aligned_start)
    expected_changes = sorted(
        key
        for key, value in target_state.items()
        if lmat_io.extract_discrete_state(original_start).get(key) != value
    )
    state_match = target_state == aligned_state
    patch_match = (
        target_patch.get("defines") == aligned_patch.get("defines")
        and target_patch.get("render_states") == aligned_patch.get("render_states")
    )
    passed = bool(
        not continuous_differences
        and state_match
        and patch_match
        and original_textures == aligned_textures
        and target_textures == original_textures
        and alignment.get("changed_keys") == expected_changes
    )
    return {
        "contract": "stage1_discrete_aligned_base_v1",
        "passed": passed,
        "asset_id": asset.asset_id,
        "start_material_path": str(asset.start_material_path),
        "target_material_path_private_audit_only": str(asset.target_material_path),
        "alignment": alignment,
        "expected_changed_discrete_keys": expected_changes,
        "continuous_search_values_preserved": not continuous_differences,
        "continuous_differences": continuous_differences,
        "target_discrete_state": target_state,
        "aligned_discrete_state": aligned_state,
        "runtime_patch_matches_target": patch_match,
        "start_textures_preserved": original_textures == aligned_textures,
        "target_and_start_textures_equal": target_textures == original_textures,
    }


def _discrete_search_space_report(
    *,
    asset: MaterialStage1AssetSpec,
    start_patch: dict[str, Any],
    candidates: list[dict[str, Any]],
    start_candidate: dict[str, Any],
) -> dict[str, Any]:
    candidate_ids = [str(candidate.get("candidate_id")) for candidate in candidates]
    includes_original_y_only = any(
        candidate["defines"]["enabled"] == ["NORMALMAP_Y_INVERT"]
        for candidate in candidates
    )
    blend_values = sorted(
        {candidate["render_states"]["s_BlendSrc"] for candidate in candidates}
    )
    passed = bool(
        len(candidates) == 16
        and len(candidate_ids) == len(set(candidate_ids))
        and start_candidate["candidate_id"] in set(candidate_ids)
        and includes_original_y_only
        and blend_values == [0, 1]
    )
    return {
        "contract": "stage1_target_independent_discrete_space_v1",
        "passed": passed,
        "asset_id": asset.asset_id,
        "start_material_path": str(asset.start_material_path),
        "start_patch": copy.deepcopy(start_patch),
        "start_candidate": copy.deepcopy(start_candidate),
        "candidate_count": len(candidates),
        "candidate_ids": candidate_ids,
        "includes_original_y_invert_only_state": includes_original_y_only,
        "searched_render_state_values": {"s_BlendSrc": blend_values},
        "target_material_or_state_used_to_build_space": False,
        "continuous_values_copied_from_target": False,
        "textures_copied_from_target": False,
    }


def _discrete_recovery_report(
    *,
    start_candidate: dict[str, Any],
    target_candidate: dict[str, Any],
    best_candidate: dict[str, Any],
    best_score: float | None,
    target_discrete_audit_score: float | None,
    success_score: float,
) -> dict[str, Any]:
    exact = best_candidate["candidate_id"] == target_candidate["candidate_id"]
    scores_valid = best_score is not None and target_discrete_audit_score is not None
    score_delta = (
        abs(float(best_score) - float(target_discrete_audit_score))
        if scores_valid
        else None
    )
    visually_equivalent = bool(scores_valid and score_delta <= 1.0e-5)
    passed = bool(
        scores_valid
        and float(best_score) >= success_score
        and (exact or visually_equivalent)
    )
    return {
        "contract": "private_stage1_discrete_recovery_audit_v1",
        "passed": passed,
        "optimizer_visible": False,
        "start_candidate": copy.deepcopy(start_candidate),
        "target_candidate_private_audit_only": copy.deepcopy(target_candidate),
        "best_candidate": copy.deepcopy(best_candidate),
        "recovered_exact_target_state": exact,
        "recovered_target_visual_equivalence_class": visually_equivalent,
        "best_score": best_score,
        "best_continuous_with_target_discrete_score": target_discrete_audit_score,
        "score_delta": score_delta,
        "scores_valid": scores_valid,
        "equivalence_tolerance": 1.0e-5,
        "inactive_state_note": (
            "PNG-only fitting cannot identify dormant hard-state values such as "
            "s_BlendSrc while s_Blend is disabled."
        ),
    }


def _finite_score(payload: dict[str, Any] | None) -> float | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("score")
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _optimizer_boundary_report(
    config: dict[str, Any],
    *,
    private_dir: Path,
    target_material_path: Path,
) -> dict[str, Any]:
    base = phase05._optimizer_boundary_report(config, private_dir=private_dir)
    serialized = json.dumps(config, ensure_ascii=False).lower()
    forbidden = {
        "target_material_path": str(target_material_path.resolve()).lower(),
        "target_material_name": target_material_path.name.lower(),
        "private_audit": "private_audit",
    }
    hits = list(base.get("hits", []))
    hits.extend(name for name, token in forbidden.items() if token and token in serialized)
    return {
        "contract": "stage1_optimizer_png_only_input_boundary_v1",
        "passed": not hits,
        "hits": sorted(set(hits)),
        "target_png_paths_allowed": True,
        "start_material_allowed": True,
        "target_material_or_continuous_params_available": False,
        "parent_target_capture_finished_before_optimizer_start": True,
        "base_report": base,
    }


def _runtime_patch_report(
    *,
    start_patch: dict[str, Any],
    best_candidate: dict[str, Any] | None,
    start_result: dict[str, Any],
    best_result: dict[str, Any],
) -> dict[str, Any]:
    start_defines = start_patch.get("defines", {})
    start_states = start_patch.get("render_states", {})
    best_defines = (
        best_candidate.get("defines", start_defines)
        if isinstance(best_candidate, dict)
        else start_defines
    )
    best_states = copy.deepcopy(start_states)
    if isinstance(best_candidate, dict):
        best_states.update(best_candidate.get("render_states", {}))
    rows: dict[str, Any] = {}
    for label, result, expected_defines, expected_states in (
        ("start", start_result, start_defines, start_states),
        ("best", best_result, best_defines, best_states),
    ):
        patch = result.get("browser_score", {}).get("material_patch", {})
        count = int(patch.get("render_state_count", 0))
        enabled = patch.get("enabled_defines", patch.get("enabledDefines", []))
        applied_states = patch.get(
            "applied_render_states",
            patch.get("appliedRenderStates", {}),
        )
        expected_blend_src = expected_states.get("s_BlendSrc")
        observed_blend_src = (
            applied_states.get("s_BlendSrc")
            if isinstance(applied_states, dict)
            else None
        )
        define_match = sorted(enabled or []) == sorted(expected_defines.get("enabled", []))
        blend_match = observed_blend_src == expected_blend_src
        rows[label] = {
            "applied": bool(patch.get("applied")),
            "render_state_count": count,
            "enabled_defines": enabled,
            "expected_enabled_defines": expected_defines.get("enabled", []),
            "applied_render_states": applied_states,
            "expected_s_BlendSrc": expected_blend_src,
            "define_match": define_match,
            "blend_src_match": blend_match,
            "passed": bool(patch.get("applied")) and define_match and blend_match,
        }
    return {
        "contract": "runtime_dynamic_discrete_patch_v2",
        "passed": all(row["passed"] for row in rows.values()),
        "captures": rows,
    }


def _parameter_audit(
    target_params: dict[str, Any],
    start_params: dict[str, Any],
    best_params: dict[str, Any],
) -> dict[str, Any]:
    coordinates = structured_material_coordinates(target_params, material_only=False)
    rows: dict[str, Any] = {}
    for coordinate in coordinates:
        span = max(float(coordinate.high) - float(coordinate.low), 1.0e-12)
        target = float(coordinate.read(target_params))
        start = float(coordinate.read(start_params))
        best = float(coordinate.read(best_params))
        rows[coordinate.coordinate_id] = {
            "target": target,
            "start": start,
            "best": best,
            "start_normalized_abs_error": abs(start - target) / span,
            "best_normalized_abs_error": abs(best - target) / span,
        }
    start_mean = sum(row["start_normalized_abs_error"] for row in rows.values()) / len(rows)
    best_mean = sum(row["best_normalized_abs_error"] for row in rows.values()) / len(rows)
    return {
        "contract": "private_stage1_parameter_audit_v1",
        "optimizer_visible": False,
        "coordinate_count": len(rows),
        "start_mean_normalized_abs_error": start_mean,
        "best_mean_normalized_abs_error": best_mean,
        "improved": best_mean < start_mean,
        "coordinates": rows,
    }


def _require_shared_space(params: dict[str, Any], asset_id: str, *, role: str) -> None:
    material = structured_material_coordinates(params, material_only=True)
    all_coordinates = structured_material_coordinates(params, material_only=False)
    scene = [row for row in all_coordinates if row.param_name in STRUCTURED_SCENE_PARAM_NAMES]
    if len(material) != 40 or len(scene) != 6:
        raise RuntimeError(
            f"{asset_id} {role} does not satisfy the shared 40+6 contract: "
            f"material={len(material)} scene={len(scene)}"
        )


def _write_profile(asset: MaterialStage1AssetSpec, path: Path) -> Path:
    payload = copy.deepcopy(asset.profile)
    payload["project_root"] = str(asset.project_root)
    payload["scene"] = str(asset.scene_path)
    _write_json(path, payload)
    return path


def _write_optimizer_profile(
    source: Path,
    output: Path,
    *,
    width: int,
    height: int,
) -> Path:
    payload = _read_json(source)
    payload["width"] = max(int(width), 64)
    payload["height"] = max(int(height), 64)
    payload["online_score_surrogate"] = {
        "enabled": True,
        "role": "proposal_ranking_only",
        "final_artifacts_use_source_profile": True,
    }
    _write_json(output, payload)
    return output


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
