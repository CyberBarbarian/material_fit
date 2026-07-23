"""Legal discrete material states and candidate transport helpers."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from material_fit.laya import lmat_io


DISCRETE_CANDIDATE_PARAM = "__material_fit_discrete_candidate__"
BROWSER_SCORE_OVERRIDE_PARAM = "__material_fit_browser_score_override__"
MANAGED_STAGE1_DEFINES = ("NORMALMAP", "NORMALMAP_Y_INVERT", "RIMSMOOTHNESS")
NORMAL_MODES: dict[str, tuple[str, ...]] = {
    "flat": (),
    "legacy_y_invert_only": ("NORMALMAP_Y_INVERT",),
    "normal": ("NORMALMAP",),
    "normal_y_invert": ("NORMALMAP", "NORMALMAP_Y_INVERT"),
}
SAFE_BLEND_SRC_VALUES = (0, 1)


def build_legal_discrete_candidates(start_patch: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build the target-independent 4 x 2 x 2 Stage 1 hard-state space."""

    raw_defines = start_patch.get("defines")
    define_patch = raw_defines if isinstance(raw_defines, Mapping) else {}
    managed = tuple(str(name) for name in define_patch.get("managed", MANAGED_STAGE1_DEFINES))
    missing = sorted(set(MANAGED_STAGE1_DEFINES) - set(managed))
    if missing:
        raise ValueError(f"start patch cannot manage required Stage 1 defines: {missing}")

    raw_states = start_patch.get("render_states")
    render_states = raw_states if isinstance(raw_states, Mapping) else {}
    start_blend_src = _effective_blend_src(render_states)
    blend_values = list(SAFE_BLEND_SRC_VALUES)
    if start_blend_src not in blend_values:
        blend_values.append(start_blend_src)

    candidates: list[dict[str, Any]] = []
    for normal_mode, normal_defines in NORMAL_MODES.items():
        for rim_smooth in (False, True):
            enabled = list(normal_defines)
            if rim_smooth:
                enabled.append("RIMSMOOTHNESS")
            for blend_src in blend_values:
                candidate_id = (
                    f"normal={normal_mode}|rim={int(rim_smooth)}|blend_src={blend_src}"
                )
                candidates.append(
                    {
                        "contract": "material_discrete_candidate_v1",
                        "candidate_id": candidate_id,
                        "axes": {
                            "normal_mode": normal_mode,
                            "rim_smooth": rim_smooth,
                            "blend_src": blend_src,
                        },
                        "defines": {
                            "managed": list(managed),
                            "enabled": enabled,
                        },
                        "render_states": {"s_BlendSrc": copy.deepcopy(blend_src)},
                    }
                )
    return candidates


def normalize_discrete_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    candidate_id = str(value.get("candidate_id") or "").strip()
    if not candidate_id:
        raise ValueError("discrete candidate is missing candidate_id")
    raw_defines = value.get("defines")
    if not isinstance(raw_defines, Mapping):
        raise ValueError(f"discrete candidate {candidate_id!r} has no defines object")
    managed = tuple(dict.fromkeys(str(name) for name in raw_defines.get("managed", ())))
    enabled = tuple(dict.fromkeys(str(name) for name in raw_defines.get("enabled", ())))
    if not set(enabled).issubset(managed):
        raise ValueError(f"discrete candidate {candidate_id!r} enables unmanaged defines")
    if set(managed) != set(MANAGED_STAGE1_DEFINES):
        raise ValueError(f"discrete candidate {candidate_id!r} has an unsafe managed define set")
    raw_states = value.get("render_states")
    if not isinstance(raw_states, Mapping):
        raise ValueError(f"discrete candidate {candidate_id!r} has no render_states object")
    unknown_states = sorted(set(raw_states) - {"s_BlendSrc"})
    if unknown_states:
        raise ValueError(f"discrete candidate {candidate_id!r} changes unsafe states: {unknown_states}")
    blend_src = raw_states.get("s_BlendSrc")
    if blend_src not in SAFE_BLEND_SRC_VALUES:
        raise ValueError(f"discrete candidate {candidate_id!r} has unsafe s_BlendSrc={blend_src!r}")

    raw_axes = value.get("axes")
    axes = copy.deepcopy(dict(raw_axes)) if isinstance(raw_axes, Mapping) else {}
    return {
        "contract": "material_discrete_candidate_v1",
        "candidate_id": candidate_id,
        "axes": axes,
        "defines": {"managed": list(managed), "enabled": list(enabled)},
        "render_states": {"s_BlendSrc": copy.deepcopy(blend_src)},
    }


def find_candidate_for_patch(
    candidates: Sequence[Mapping[str, Any]],
    patch: Mapping[str, Any],
) -> dict[str, Any]:
    raw_defines = patch.get("defines")
    defines = raw_defines if isinstance(raw_defines, Mapping) else {}
    enabled = set(str(name) for name in defines.get("enabled", ()))
    raw_states = patch.get("render_states")
    states = raw_states if isinstance(raw_states, Mapping) else {}
    blend_src = _effective_blend_src(states)
    for raw_candidate in candidates:
        candidate = normalize_discrete_candidate(raw_candidate)
        if (
            set(candidate["defines"]["enabled"]) == enabled
            and candidate["render_states"]["s_BlendSrc"] == blend_src
        ):
            return candidate
    raise ValueError(
        "start material discrete state is outside the legal search space: "
        f"defines={sorted(enabled)}, s_BlendSrc={blend_src!r}"
    )


def _effective_blend_src(states: Mapping[str, Any]) -> Any:
    """Canonicalize an unsafe blend factor only when blending is disabled."""

    blend_src = states.get("s_BlendSrc", SAFE_BLEND_SRC_VALUES[0])
    if states.get("s_Blend") in (0, False) and blend_src not in SAFE_BLEND_SRC_VALUES:
        return SAFE_BLEND_SRC_VALUES[0]
    return blend_src


def compress_observationally_equivalent_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    start_candidate: Mapping[str, Any],
    start_patch: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select target-independent representatives of dormant hard states."""

    normalized = [normalize_discrete_candidate(row) for row in candidates]
    normalized_start = normalize_discrete_candidate(start_candidate)
    candidate_ids = {row["candidate_id"] for row in normalized}
    if normalized_start["candidate_id"] not in candidate_ids:
        raise ValueError("start candidate is outside the legal discrete space")

    raw_states = start_patch.get("render_states")
    states = raw_states if isinstance(raw_states, Mapping) else {}
    blend_state_known = "s_Blend" in states
    blend_enabled = bool(states.get("s_Blend")) if blend_state_known else True

    groups: dict[tuple[str, bool, int | None], list[dict[str, Any]]] = {}
    for candidate in normalized:
        enabled = set(candidate["defines"]["enabled"])
        if "NORMALMAP" not in enabled:
            normal_key = "normal_off"
        elif "NORMALMAP_Y_INVERT" in enabled:
            normal_key = "normal_y_invert"
        else:
            normal_key = "normal"
        key = (
            normal_key,
            "RIMSMOOTHNESS" in enabled,
            candidate["render_states"]["s_BlendSrc"] if blend_enabled else None,
        )
        groups.setdefault(key, []).append(candidate)

    representatives: list[dict[str, Any]] = []
    group_report: list[dict[str, Any]] = []
    start_id = normalized_start["candidate_id"]
    for key, members in groups.items():
        representative = next(
            (row for row in members if row["candidate_id"] == start_id),
            members[0],
        )
        representatives.append(copy.deepcopy(representative))
        group_report.append(
            {
                "equivalence_key": {
                    "normal_response": key[0],
                    "rim_smooth": key[1],
                    "blend_src": key[2] if key[2] is not None else "inactive",
                },
                "representative_candidate_id": representative["candidate_id"],
                "member_candidate_ids": [row["candidate_id"] for row in members],
            }
        )

    report = {
        "contract": "stage1_target_independent_observation_equivalence_v1",
        "target_information_used": False,
        "legal_candidate_count": len(normalized),
        "representative_candidate_count": len(representatives),
        "start_candidate_preserved": any(
            row["candidate_id"] == start_id for row in representatives
        ),
        "blend_state_known": blend_state_known,
        "blend_enabled": blend_enabled,
        "rules": {
            "normal_y_invert_is_dormant_without_normalmap": True,
            "blend_src_is_dormant_when_blending_disabled": not blend_enabled,
        },
        "groups": group_report,
    }
    return representatives, report


def attach_discrete_candidate(
    params: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    result = {
        str(name): copy.deepcopy(value)
        for name, value in params.items()
        if str(name) != DISCRETE_CANDIDATE_PARAM
    }
    result[DISCRETE_CANDIDATE_PARAM] = normalize_discrete_candidate(candidate)
    return result


def split_discrete_candidate(
    params: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    continuous = {
        str(name): copy.deepcopy(value)
        for name, value in params.items()
        if str(name) not in {DISCRETE_CANDIDATE_PARAM, BROWSER_SCORE_OVERRIDE_PARAM}
    }
    raw_candidate = params.get(DISCRETE_CANDIDATE_PARAM)
    candidate = (
        normalize_discrete_candidate(raw_candidate)
        if isinstance(raw_candidate, Mapping)
        else None
    )
    return continuous, candidate


def merge_candidate_into_material_patch(
    patch: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(patch)) if isinstance(patch, Mapping) else {}
    if candidate is None:
        return result
    normalized = normalize_discrete_candidate(candidate)
    result["defines"] = copy.deepcopy(normalized["defines"])
    raw_states = result.get("render_states")
    states = copy.deepcopy(dict(raw_states)) if isinstance(raw_states, Mapping) else {}
    states.update(copy.deepcopy(normalized["render_states"]))
    result["render_states"] = states
    result["discrete_candidate_id"] = normalized["candidate_id"]
    return result


def write_candidate_lmat_with_discrete_state(
    source_path: str | Path,
    output_path: str | Path,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    continuous, candidate = split_discrete_candidate(params)
    if candidate is None:
        raise ValueError("candidate params do not contain a discrete state")
    source = lmat_io.load_lmat(source_path)
    rewritten = lmat_io.apply_params(source, continuous, allow_missing_keys=True)
    props = lmat_io.get_props(rewritten)

    managed = set(candidate["defines"]["managed"])
    existing = [str(name) for name in props.get("defines", ()) if str(name) not in managed]
    props["defines"] = existing + list(candidate["defines"]["enabled"])
    for name, value in candidate["render_states"].items():
        if name not in props:
            raise lmat_io.LmatWriteError(f"source material has no discrete state {name!r}")
        props[name] = copy.deepcopy(value)

    lmat_io.save_lmat(rewritten, output_path)
    reloaded = lmat_io.load_lmat(output_path)
    shape_differences = [
        row
        for row in lmat_io.diff_shapes(source, reloaded)
        if not row.startswith("SHAPE props.defines:")
    ]
    if shape_differences:
        Path(output_path).unlink(missing_ok=True)
        raise lmat_io.LmatWriteError(
            "Discrete candidate changed material structure:\n  "
            + "\n  ".join(shape_differences)
        )
    return candidate


__all__ = [
    "BROWSER_SCORE_OVERRIDE_PARAM",
    "DISCRETE_CANDIDATE_PARAM",
    "MANAGED_STAGE1_DEFINES",
    "NORMAL_MODES",
    "SAFE_BLEND_SRC_VALUES",
    "attach_discrete_candidate",
    "build_legal_discrete_candidates",
    "compress_observationally_equivalent_candidates",
    "find_candidate_for_patch",
    "merge_candidate_into_material_patch",
    "normalize_discrete_candidate",
    "split_discrete_candidate",
    "write_candidate_lmat_with_discrete_state",
]
