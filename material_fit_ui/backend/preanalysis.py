"""Pre-analysis pipeline.

Given a project's ``inputs`` block, parse the Unity and Laya shaders, build
a Unity↔Laya parameter mapping, and predict which stages of the existing
adjustment plan apply. Results are persisted to ``preanalysis.json`` under
the project directory and surfaced to the UI.

Mapping pipeline (in priority order)
------------------------------------

1. **Manual override** — entries from ``project.json.manual_param_mapping``.
   Highest priority; user-curated, never overridden by anything else.
2. **Curated dictionary** — hand-rolled translations for common Unity
   shaders (Standard / URP Lit / Toon) into the Laya FishStandard idiom.
3. **Exact normalized name** — strip ``_``/``u_`` prefix, lowercase,
   alphanumeric-only; if both sides collapse to the same key it counts as
   ``exact``.
4. **Type-aware fuzzy** — for the leftovers we run a token similarity score,
   but require type compatibility (Color↔Color, Float/Range/Int↔scalar,
   Vector↔Vector, 2D↔2D, Cube↔Cube) and threshold ≥0.85. This is a deliberate
   tightening from the previous 0.6 threshold which produced false positives
   like ``_ColorScale (Range)`` ↔ ``u_BaseColor (Color)``.
5. ``unity_only`` / ``laya_only`` — leftovers on either side; the UI lets the
   user manually pair them and saves the result back as a manual override.

The mapping is **also** persisted into ``project.json.effective_param_mapping``
so the runtime ``fit_material.py`` can use it for value anchoring (currently
disabled there because the bare exact-name path was unreachable across engines).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .case_loader import LoaderConfig, _to_rel_posix
from .project_store import get_project, project_paths


def run_preanalysis(project_id: str, config: LoaderConfig | None = None) -> dict[str, Any]:
    config = config or LoaderConfig()
    project = get_project(project_id, config)
    inputs = project.get("inputs") or {}
    manual_mapping = project.get("manual_param_mapping") or {}

    laya_shader_path = inputs.get("laya_shader_path") or ""
    unity_shader_path = inputs.get("unity_shader_path") or ""
    laya_lmat_path = inputs.get("laya_material_lmat_path") or ""

    if not laya_shader_path:
        raise ValueError("preanalysis requires inputs.laya_shader_path")

    laya_info = _parse_laya(laya_shader_path)
    unity_info = _parse_unity(unity_shader_path) if unity_shader_path else None
    laya_material_params = _read_lmat_params(laya_lmat_path) if laya_lmat_path else {}
    unity_material_params = _read_unity_params(inputs.get("unity_material_params_path") or "")

    mapping_rows = _build_param_mapping(unity_info, laya_info, manual_mapping=manual_mapping)
    stage_plan = _predict_stage_plan(laya_info)

    coverage = _compute_coverage(mapping_rows)
    initial_recommendations = _initial_recommendations(
        unity_material_params=unity_material_params,
        laya_material_params=laya_material_params,
        mapping=mapping_rows,
        laya_param_meta={p["name"]: p for p in laya_info["params"]},
    )

    payload: dict[str, Any] = {
        "project_id": project_id,
        "ran_at": _now_iso(),
        "unity_shader": unity_info,
        "laya_shader": laya_info,
        "laya_material_params": laya_material_params,
        "unity_material_params": unity_material_params,
        "param_mapping": mapping_rows,
        "stage_plan": stage_plan,
        "coverage": coverage,
        "initial_recommendations": initial_recommendations,
        "warnings": _collect_warnings(unity_info, laya_info, mapping_rows, inputs),
    }

    paths = project_paths(project_id, config)
    paths.preanalysis_json.parent.mkdir(parents=True, exist_ok=True)
    paths.preanalysis_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    rel_pre = _to_rel_posix(paths.preanalysis_json, config.project_root)
    from .project_store import patch_project

    patch_project(project_id, {"preanalysis_path": rel_pre}, config=config)
    return payload


def get_preanalysis(project_id: str, config: LoaderConfig | None = None) -> dict[str, Any] | None:
    config = config or LoaderConfig()
    paths = project_paths(project_id, config)
    if not paths.preanalysis_json.exists():
        return None
    try:
        return json.loads(paths.preanalysis_json.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _parse_laya(path: str) -> dict[str, Any]:
    from tools.material_fit.laya.shader_parser import parse_laya_shader, shader_info_to_dict

    info = parse_laya_shader(path)
    return shader_info_to_dict(info)


def _parse_unity(path: str) -> dict[str, Any]:
    from tools.material_fit.unity.shader_parser import parse_unity_shaderlab

    info = parse_unity_shaderlab(path)
    return {
        "path": str(info.path),
        "name": info.name,
        "params": [param.__dict__ for param in info.params],
        "defines": [],
    }


def _read_lmat_params(path: str) -> dict[str, Any]:
    if not path:
        return {}
    try:
        from tools.material_fit.laya import lmat_io

        material = lmat_io.load_lmat(path)
        return lmat_io.extract_params(material)
    except Exception:
        return {}


def _read_unity_params(path: str) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("params"), dict):
        return data["params"]
    if isinstance(data, dict) and isinstance(data.get("properties"), dict):
        return data["properties"]
    return data if isinstance(data, dict) else {}


def _build_param_mapping(
    unity_info: dict[str, Any] | None,
    laya_info: dict[str, Any],
    *,
    manual_mapping: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    laya_params = laya_info.get("params", [])
    laya_by_name = {p["name"]: p for p in laya_params}
    if not unity_info:
        return [
            {
                "unity_name": None,
                "unity_type": None,
                "laya_name": p["name"],
                "laya_type": p.get("param_type"),
                "status": "laya_only",
                "score": 0.0,
                "reason": "no Unity shader provided",
            }
            for p in laya_params
        ]

    manual_mapping = manual_mapping or {}
    rows: list[dict[str, Any]] = []
    seen_laya: set[str] = set()
    laya_norm_index = {_normalize(p["name"]): p for p in laya_params}

    for u in unity_info.get("params", []):
        u_name = u["name"]
        u_norm = _normalize(u_name)

        # 1. manual override (user-curated, highest priority)
        manual_target = manual_mapping.get(u_name)
        if manual_target == "":
            seen_laya.add("__skipped__")
            rows.append(_pair(u, None, status="manual_skip", score=1.0, reason="user marked as no mapping"))
            continue
        if manual_target and manual_target in laya_by_name:
            laya = laya_by_name[manual_target]
            seen_laya.add(laya["name"])
            rows.append(_pair(u, laya, status="manual", score=1.0, reason="user-defined mapping"))
            continue

        # 2. curated dictionary
        curated = _curated_pair(u_norm, laya_norm_index)
        if curated is not None and curated["name"] not in seen_laya:
            laya = curated
            seen_laya.add(laya["name"])
            rows.append(_pair(u, laya, status="curated", score=0.95, reason="curated cross-engine dictionary"))
            continue

        # 3. exact normalized
        if u_norm in laya_norm_index and laya_norm_index[u_norm]["name"] not in seen_laya:
            laya = laya_norm_index[u_norm]
            if _types_compatible(u.get("param_type"), laya.get("param_type")):
                seen_laya.add(laya["name"])
                rows.append(_pair(u, laya, status="exact", score=1.0, reason="normalized name match (type compatible)"))
                continue
            # name matches but types disagree — surface clearly, don't auto-pair
            rows.append(_pair(
                u, None, status="unity_only", score=0.0,
                reason=f"name matches Laya `{laya['name']}` but types incompatible ({u.get('param_type')} vs {laya.get('param_type')})",
            ))
            continue

        # 4. type-aware fuzzy
        candidates: list[tuple[dict[str, Any], float]] = []
        for laya in laya_params:
            if laya["name"] in seen_laya:
                continue
            if not _types_compatible(u.get("param_type"), laya.get("param_type")):
                continue
            score = _name_score(u_norm, _normalize(laya["name"]))
            if score >= 0.85:
                candidates.append((laya, score))
        candidates.sort(key=lambda item: item[1], reverse=True)
        if candidates:
            laya, score = candidates[0]
            seen_laya.add(laya["name"])
            rows.append(_pair(u, laya, status="fuzzy", score=score, reason="type-compatible name similarity ≥0.85"))
            continue

        rows.append(_pair(u, None, status="unity_only", score=0.0, reason="no type-compatible Laya counterpart"))

    for laya in laya_params:
        if laya["name"] in seen_laya:
            continue
        rows.append(_pair(None, laya, status="laya_only", score=0.0, reason="not paired with any Unity property"))
    return rows


def _pair(
    unity: dict[str, Any] | None,
    laya: dict[str, Any] | None,
    *,
    status: str,
    score: float,
    reason: str,
) -> dict[str, Any]:
    return {
        "unity_name": unity["name"] if unity else None,
        "unity_type": unity.get("param_type") if unity else None,
        "laya_name": laya["name"] if laya else None,
        "laya_type": laya.get("param_type") if laya else None,
        "status": status,
        "score": round(float(score), 3),
        "reason": reason,
    }


def _types_compatible(unity_type: str | None, laya_type: str | None) -> bool:
    """Return True if a Unity ShaderLab type and a Laya uniformMap type can
    sensibly hold each other's values."""

    if not unity_type or not laya_type:
        return True  # missing info — be permissive, surface to user later
    u = unity_type.lower()
    l = laya_type.lower()

    scalar = {"float", "range", "int"}
    color = {"color"}
    vector = {"vector"}
    tex2d = {"2d"}
    cube = {"cube"}

    def family(t: str) -> str:
        if t in scalar:
            return "scalar"
        if t in color:
            return "color"
        if t in vector:
            return "vector"
        if t in tex2d:
            return "tex2d"
        if t in cube:
            return "cube"
        return t

    fu, fl = family(u), family(l)
    if fu == fl:
        return True
    # Color↔Vector is genuinely interchangeable (vec4 = RGBA = color).
    if {fu, fl} == {"color", "vector"}:
        return True
    return False


def _name_score(a: str, b: str) -> float:
    """Token-aware similarity in [0, 1]. Higher means more similar."""

    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        shorter = min(len(a), len(b))
        longer = max(len(a), len(b))
        return shorter / longer
    # character-set Jaccard (very lightweight)
    set_a, set_b = set(a), set(b)
    inter = set_a & set_b
    union = set_a | set_b
    return len(inter) / max(len(union), 1)


def _normalize(name: str) -> str:
    name = (name or "").lower()
    if name.startswith("u_"):
        name = name[2:]
    if name.startswith("_"):
        name = name[1:]
    return "".join(ch for ch in name if ch.isalnum())


# ---------------------------------------------------------------------------
# Curated cross-engine dictionary.
#
# Keys are the *normalized* (lowercase, alphanumeric-only, prefix-stripped)
# Unity property names. Values are tuples of acceptable normalized Laya
# uniformMap names, in preference order. The first one that actually exists in
# the parsed Laya shader wins.
#
# Sources: Unity Standard, URP Lit / SimpleLit, common Toon shaders, observed
# Laya Engine FishStandard / Effect / Stylized shaders. Keep entries here
# **only if the semantic meaning is unambiguous** — anything fuzzy should fall
# through to type-aware name match so the user can audit it in the UI.
# ---------------------------------------------------------------------------
_CURATED_DICT: dict[str, tuple[str, ...]] = {
    "color":            ("basecolor", "albedocolor", "maincolor", "tintcolor", "color"),
    "basecolor":        ("basecolor", "albedocolor", "color"),
    "tintcolor":        ("basecolor", "tintcolor", "color"),
    "maintex":          ("albedotexture", "maintexture", "diffusetexture", "basecolortexture"),
    "albedo":           ("albedotexture", "maintexture", "basecolortexture"),
    "albedotex":        ("albedotexture", "basecolortexture"),
    "metallic":         ("metallic",),
    "smoothness":       ("smoothness",),
    "glossiness":       ("smoothness",),
    "roughness":        ("smoothness",),  # smoothness = 1 - roughness, but it's the same channel
    "metallicgloss":    ("metallicglosstexture", "metallictexture"),
    "metallictex":      ("metallictexture",),
    "metallicremapmin": ("metallicremapmin",),
    "metallicremapmax": ("metallicremapmax",),
    "smoothnessremapmin": ("smoothnessremapmin",),
    "smoothnessremapmax": ("smoothnessremapmax",),
    "bumpmap":          ("normaltexture", "bumptexture"),
    "normalmap":        ("normaltexture", "bumptexture"),
    "bumpscale":        ("bumpscale", "normalstrength"),
    "normalscale":      ("bumpscale", "normalstrength"),
    "occlusionmap":     ("occlusiontexture",),
    "occlusionstrength": ("occlusionstrength",),
    "emissioncolor":    ("emissioncolor",),
    "emissionmap":      ("emissiontexture", "emissionmap"),
    "emissionintensity": ("emissionintensity", "emissionpower"),
    "emissionpower":    ("emissionpower", "emissionintensity"),
    "cutoff":           ("cutoff", "alphacutoff"),
    "alphacutoff":      ("cutoff", "alphacutoff"),
    "alpha":            ("alpha",),
    "specularhighlights": ("specularhighlights",),
    "specularcolor":    ("specularcolor",),
    "rimcolor":         ("rimcolor",),  # only paired if such a name exists
    "rimpower":         ("rimpower",),
    "rimintensity":     ("rimintensity",),
    "fresnel":          ("fresnelintensity", "fresnelpower"),
    "fresnelpower":     ("fresnelpower",),
    "fresnelintensity": ("fresnelintensity",),
    "matcap":           ("matcaptexture", "matcap"),
    "matcaptex":        ("matcaptexture",),
    "matcapintensity":  ("matcapintensity",),
}


def _curated_pair(
    u_norm: str,
    laya_norm_index: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Look up a normalized Unity name in the curated dict and return the
    first Laya param whose normalized name appears in the candidate tuple.
    Returns ``None`` if no curated mapping or the candidates aren't present."""

    candidates = _CURATED_DICT.get(u_norm)
    if not candidates:
        return None
    for cand in candidates:
        laya = laya_norm_index.get(cand)
        if laya:
            return laya
    return None


def _predict_stage_plan(laya_info: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from tools.material_fit.optimizer.adjustment_algorithm import build_adjustment_policies
        from tools.material_fit.shared.models import ShaderParam

        params = [
            ShaderParam(
                name=p["name"],
                display_name=p.get("display_name", p["name"]),
                param_type=p.get("param_type", ""),
                default=p.get("default"),
                range_min=p.get("range_min"),
                range_max=p.get("range_max"),
                hidden=p.get("hidden"),
            )
            for p in laya_info.get("params", [])
        ]
        policies = build_adjustment_policies(params)
        return [
            {
                "name": pol.name,
                "description": pol.description,
                "channels": pol.channels,
                "params": pol.params,
                "max_iterations": pol.max_iterations,
                "target_score": pol.target_score,
            }
            for pol in policies
        ]
    except Exception as exc:  # noqa: BLE001
        return [{"name": "_error", "description": f"failed to build policies: {exc}", "channels": [], "params": [], "max_iterations": 0, "target_score": 0.0}]


def _compute_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    matched_kinds = {"manual", "curated", "exact", "fuzzy"}
    total_unity = sum(1 for r in rows if r["unity_name"])
    matched = sum(1 for r in rows if r["status"] in matched_kinds and r["unity_name"])
    return {
        "unity_total": total_unity,
        "unity_mapped": matched,
        "unity_unmapped": total_unity - matched,
        "laya_total": sum(1 for r in rows if r["laya_name"]),
        "laya_only": sum(1 for r in rows if r["status"] == "laya_only"),
        "ratio": (matched / total_unity) if total_unity else 0.0,
        "by_status": {
            "manual": sum(1 for r in rows if r["status"] == "manual"),
            "curated": sum(1 for r in rows if r["status"] == "curated"),
            "exact": sum(1 for r in rows if r["status"] == "exact"),
            "fuzzy": sum(1 for r in rows if r["status"] == "fuzzy"),
            "manual_skip": sum(1 for r in rows if r["status"] == "manual_skip"),
            "unity_only": sum(1 for r in rows if r["status"] == "unity_only"),
            "laya_only": sum(1 for r in rows if r["status"] == "laya_only"),
        },
    }


def _initial_recommendations(
    *,
    unity_material_params: dict[str, Any],
    laya_material_params: dict[str, Any],
    mapping: list[dict[str, Any]],
    laya_param_meta: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Suggested initial values: only paired rows that we trust enough to apply."""

    trusted = {"manual", "curated", "exact"}
    out: list[dict[str, Any]] = []
    for row in mapping:
        if row["status"] not in trusted:
            continue
        u_name = row["unity_name"]
        l_name = row["laya_name"]
        if not u_name or not l_name:
            continue
        if u_name not in unity_material_params:
            continue
        unity_value = unity_material_params[u_name]
        laya_value = laya_material_params.get(l_name)
        meta = laya_param_meta.get(l_name, {})
        out.append(
            {
                "laya_param": l_name,
                "unity_param": u_name,
                "current_laya_value": laya_value,
                "suggested_value": unity_value,
                "status": row["status"],
                "type": meta.get("param_type"),
                "range": [meta.get("range_min"), meta.get("range_max")],
            }
        )
    return out


def _collect_warnings(
    unity_info: dict[str, Any] | None,
    laya_info: dict[str, Any],
    mapping: list[dict[str, Any]],
    inputs: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if not unity_info:
        warnings.append("Unity 着色器未提供，将无法做参数对照映射，仅按 Laya 侧默认 stage plan 调参。")
    if not laya_info.get("params"):
        warnings.append("Laya shader 解析未得到任何参数，请检查 uniformMap 块是否存在。")
    fuzzy_count = sum(1 for r in mapping if r["status"] == "fuzzy")
    if fuzzy_count:
        warnings.append(
            f"{fuzzy_count} 个参数仅靠名称模糊匹配（已要求类型兼容且相似度≥0.85），仍建议人工复核或在表格里改成 manual。"
        )
    unity_only = sum(1 for r in mapping if r["status"] == "unity_only")
    if unity_only:
        warnings.append(
            f"{unity_only} 个 Unity 属性没有自动找到 Laya 对应——可在表格里手动配对，或添加到 curated 字典。"
        )
    if not inputs.get("unity_reference_image_path"):
        warnings.append("没有 Unity 参考图，自动调参无法进行图像差异分析；至少需要一张参考图。")
    if not inputs.get("laya_capture_region"):
        warnings.append("Laya 截图区域未配置；勾选 capture_screen_after_apply 时必须提供。")
    if not inputs.get("laya_material_lmat_path"):
        warnings.append("没有 Laya .lmat 写入目标，自动调参无法应用材质修改。")
    return warnings


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now().isoformat(timespec="seconds")
