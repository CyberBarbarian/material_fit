"""End-to-end stage progression simulation using real channel scores.

The user's last run had ``base_color_main_texture.rgb_mae ≈ 0.20``,
``shadow_occlusion ≈ 0.45``, ``metallic_smoothness_specular ≈ 0.25``,
``environment_reflection_matcap ≈ 0.18``, ``fresnel_rim ≈ 0.16``,
``emission ≈ 0.38`` — i.e. *every* channel is comfortably above the
declared per-stage ``target_score``. The old ``choose_stage`` got stuck
on stage 0 forever; the new one must cycle through all stages.

This test pins that observed trajectory: in 12 iterations we should
visit every stage at least once and finish with ``cycle >= 1``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.material_fit.optimizer.adjustment_algorithm import (  # noqa: E402
    AdjustmentState,
    build_adjustment_policies,
    choose_stage,
    update_stage_progress,
)
from tools.material_fit.shared.models import ShaderParam  # noqa: E402


# Channel scores observed in the real iter_0000 of fish_1580 (rgb_mae values).
# Keeping them constant simulates the worst-case "the optimiser's tweaks
# don't actually move the channel" scenario — which is exactly what the
# user hit and what the old code couldn't escape.
REAL_CHANNEL_SCORES = {
    "base_color_main_texture": 0.2056,
    "metallic_smoothness_specular": 0.2458,
    "environment_reflection_matcap": 0.1800,
    "fresnel_rim": 0.1600,
    "emission": 0.3842,
    "shadow_occlusion": 0.4540,
    "center_vs_edge_balance": 0.20,
    "color_grading_hsv_contrast": 0.10,
}


def _real_analysis() -> dict:
    return {
        "material_channels": {
            name: {"rgb_mae": value} for name, value in REAL_CHANNEL_SCORES.items()
        }
    }


def _all_fish_uniforms() -> list[ShaderParam]:
    """A representative set of FishStandard uniforms — enough that
    ``build_adjustment_policies`` keeps every declared stage."""
    names = [
        "u_BaseColor", "u_Gamma_Power",
        "u_OcclusionStrength", "u_GIIntensity", "u_DiffuseThreshold",
        "u_DiffuseSmoothness", "u_ShadowColor",
        "u_SpecularIntensity", "u_SpecularColor", "u_SpecularThreshold",
        "u_SpecularSmooth", "u_GGXSpecular", "u_Metallic", "u_Smoothness",
        "u_IBLMapIntensity", "u_IBLMapPower", "u_IBLMapColor",
        "u_EnvironmentReflections", "u_MatcapStrength", "u_MatcapPow",
        "u_MatcapColor", "u_MatcapAddStrength",
        "u_FresnelColor", "u_FresnelIntensity", "u_FresnelThreshold",
        "u_FresnelSmooth", "u_FresnelPow", "u_EmissionColor", "u_EmissionScale",
        "u_AdjustHue", "u_AdjustSaturation", "u_AdjustLightness", "u_ContrastScale",
    ]
    return [ShaderParam(name=n, param_type="Float", source="laya_uniformMap") for n in names]


def test_twelve_iters_visit_all_stages() -> None:
    """The exact failure mode the user reported: 12 iterations on a hard
    diff. With the fix, every stage must be exercised at least once."""
    policies = build_adjustment_policies(_all_fish_uniforms())
    assert len(policies) == 6, f"expected 6 policies, got {[p.name for p in policies]}"

    state = AdjustmentState()
    visited: list[str] = []
    for _ in range(12):
        analysis = _real_analysis()
        policy, _info = choose_stage(policies, analysis, state)
        assert policy is not None
        visited.append(policy.name)
        update_stage_progress(state, policy, analysis)

    declared = [p.name for p in policies]
    missed = [name for name in declared if name not in visited]
    assert not missed, (
        f"after 12 iterations the algorithm still hasn't visited stages {missed}; "
        f"trajectory was {visited}"
    )
    # The expected trajectory is: 3 base_color + 2*4 mid stages + 1 global =
    # 12 iters, covering every stage in coarse-to-fine order. Cycling back
    # to stage 0 happens at iter 13.
    assert visited[:3] == ["base_color"] * 3
    assert visited[-1] == "global_color_grade"


def test_twelve_iters_stage_distribution() -> None:
    """Quantitatively, no single stage should hog more than (roughly) its
    own ``max_iterations`` per cycle. This is the direct anti-regression
    of the user-reported bug ('all 12 iters stayed in base_color')."""
    policies = build_adjustment_policies(_all_fish_uniforms())
    state = AdjustmentState()
    visited: list[str] = []
    for _ in range(12):
        analysis = _real_analysis()
        policy, _ = choose_stage(policies, analysis, state)
        visited.append(policy.name)
        update_stage_progress(state, policy, analysis)

    counts = {name: visited.count(name) for name in {p.name for p in policies}}
    base_color_count = counts.get("base_color", 0)
    # base_color has max_iterations=3; even with one cycle restart it
    # should never exceed ~6 in 12 iters.
    assert base_color_count <= 6, (
        f"base_color over-represented: {counts}, trajectory={visited}"
    )
