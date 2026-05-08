"""End-to-end check that ``fit_material._run_auto_adjustment`` actually
routes through the requested ``--optimizer`` strategy.

Without these tests, the wire-up between ``fit_material`` (the
production CLI used by the UI's ``job_manager``) and the new
``optimizer.strategy`` module would be silently broken — the unit
tests in ``test_strategy.py`` confirm the strategies *themselves* are
correct, but only an end-to-end run can confirm that:

* ``--optimizer cma_warm`` hands prior iterations into the warm-start.
* ``decision.json`` for each iteration is tagged with the optimizer
  name, which the UI surfaces.
* ``auto_adjust_result.json`` records the optimizer + cma_es config
  used, so research-time comparisons across runs are unambiguous.

The renderer and image diff are mocked because:

1. We don't have a Laya Editor available in CI / from this session.
2. We want the test to converge in milliseconds, not minutes.

The mocks return synthetic but *structurally realistic* analysis
output (with all material_channels keys populated), exactly matching
what ``analyze_image_diff`` produces on a real run. The strategies do
not see the difference.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit import fit_material  # noqa: E402
from tools.material_fit.optimizer.strategy import CmaesStrategyConfig  # noqa: E402
from tools.material_fit.shared.models import ShaderParam  # noqa: E402


# --------------------------------------------------------------------
# Fixtures


def _shader_params() -> list[ShaderParam]:
    return [
        ShaderParam("u_BaseColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_Gamma_Power", "Range", default=1.0, range_min=0.05, range_max=10.0),
        ShaderParam("u_Metallic", "Range", default=0.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_Smoothness", "Range", default=1.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_OcclusionStrength", "Range", default=1.0, range_min=0.0, range_max=10.0),
        ShaderParam("u_DiffuseThreshold", "Range", default=0.5, range_min=0.0, range_max=1.0),
        ShaderParam("u_DiffuseSmoothness", "Range", default=0.1, range_min=0.0, range_max=1.0),
        ShaderParam("u_ShadowColor", "Color", default=[0, 0, 0, 1]),
        ShaderParam("u_SpecularColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_SpecularIntensity", "Float", default=1.0),
        ShaderParam("u_FresnelColor", "Color", default=[1, 0, 0, 0]),
        ShaderParam("u_FresnelIntensity", "Float", default=1.0),
        ShaderParam("u_AdjustHue", "Float", default=0.0),
        ShaderParam("u_AdjustSaturation", "Float", default=0.0),
        ShaderParam("u_AdjustLightness", "Float", default=0.0),
        ShaderParam("u_ContrastScale", "Float", default=0.0),
    ]


def _initial_params() -> dict[str, object]:
    return {
        "u_BaseColor": [0.32, 0.27, 0.07, 1.0],
        "u_Gamma_Power": 2.2,
        "u_Metallic": 0.0,
        "u_Smoothness": 1.0,
        "u_OcclusionStrength": 1.0,
        "u_DiffuseThreshold": 0.5,
        "u_DiffuseSmoothness": 0.1,
        "u_ShadowColor": [0, 0, 0, 1],
        "u_SpecularColor": [1, 1, 1, 1],
        "u_SpecularIntensity": 1.0,
        "u_FresnelColor": [1, 0, 0, 0],
        "u_FresnelIntensity": 1.0,
        "u_AdjustHue": 0.0,
        "u_AdjustSaturation": 0.0,
        "u_AdjustLightness": 0.0,
        "u_ContrastScale": 0.0,
    }


def _fake_analysis() -> dict:
    """Synthetic analyze_image_diff output mirroring the real shape."""
    channel = {
        "rgb_bias_candidate_minus_reference": [0.05, 0.0, -0.05],
        "luma_bias_candidate_minus_reference": 0.04,
        "saturation_bias_candidate_minus_reference": 0.0,
        "contrast_bias_candidate_minus_reference": 0.0,
        "rgb_mae": 0.10,
        "edge_minus_center_luma_bias": 0.0,
    }
    return {
        "score": 0.10,
        "material_channels": {
            "base_color_main_texture": dict(channel),
            "shadow_occlusion": dict(channel),
            "metallic_smoothness_specular": dict(channel),
            "environment_reflection_matcap": dict(channel),
            "fresnel_rim": dict(channel),
            "emission": dict(channel),
            "color_grading_hsv_contrast": dict(channel),
            "center_vs_edge_balance": dict(channel),
        },
    }


class _StubDriver:
    """Stand-in for ``RenderDriver`` that records calls and returns
    ``{"screenshots": [...]}`` so the candidate_override flow keeps
    working."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.calls: list[tuple[int, dict]] = []

    def render_candidate(self, iteration: int, params: dict) -> dict:
        self.calls.append((iteration, params))
        return {"screenshots": [], "iteration": iteration}

    def capture_candidate(self, iteration: int, params: dict) -> dict:
        self.calls.append((iteration, params))
        return {"screenshots": [], "iteration": iteration}


@pytest.fixture
def patched_pipeline(monkeypatch, tmp_path):
    """Stub out image diff + driver and pre-build minimal disk state.

    Returns ``(output_dir, laya_material_path)`` so each test can call
    ``fit_material._run_auto_adjustment`` with the right paths.
    """

    fake_pair = {"reference": str(tmp_path / "ref.png"), "candidate": str(tmp_path / "cand.png")}
    (tmp_path / "ref.png").write_bytes(b"")
    (tmp_path / "cand.png").write_bytes(b"")

    monkeypatch.setattr(
        fit_material,
        "_collect_image_pairs",
        lambda *args, **kwargs: [fake_pair],
    )
    monkeypatch.setattr(
        fit_material,
        "analyze_image_diff",
        lambda config: _fake_analysis(),
    )

    laya_material_path = tmp_path / "stub.lmat"
    laya_material_path.write_text("{}", encoding="utf-8")  # never read in dry-run path

    return tmp_path, laya_material_path


# --------------------------------------------------------------------
# Tests


def _run(
    *,
    output_dir: Path,
    laya_material_path: Path,
    optimizer: str,
    iterations: int,
    cma_es_config: CmaesStrategyConfig | None = None,
) -> dict:
    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    return fit_material._run_auto_adjustment(
        config={},
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=laya_material_path,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=iterations,
        target_score=0.99,  # impossible to satisfy → run all iterations
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer=optimizer,
        cma_es_config=cma_es_config,
    )


def test_fit_material_runs_heuristic_branch(patched_pipeline):
    output_dir, lmat = patched_pipeline
    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="heuristic",
        iterations=3,
    )
    assert result["status"] == "max_iterations_reached"
    assert result["optimizer"] == "heuristic"
    assert result["cma_es_config"] is None
    assert result["warm_start_history_size"] == 0
    assert len(result["iterations"]) == 3
    for entry in result["iterations"]:
        assert entry["decision"]["optimizer"] == "heuristic"


def test_fit_material_runs_cma_cold_branch(patched_pipeline):
    output_dir, lmat = patched_pipeline
    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="cma_cold",
        iterations=4,
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )
    assert result["status"] == "max_iterations_reached"
    assert result["optimizer"] == "cma_cold"
    assert result["cma_es_config"]["mode"] == "cold"
    assert result["cma_es_config"]["population_size"] == 4
    assert len(result["iterations"]) == 4
    last_decision = result["iterations"][-1]["decision"]
    assert last_decision["optimizer"] == "cma_es"
    cma_info = last_decision["cma_es"]
    assert cma_info["warm_started"] is False
    # 4 propose() calls → 3 told fitnesses (the last ask still pending)
    assert cma_info["evaluations"] == 3


def test_fit_material_cma_warm_loads_history_from_disk(patched_pipeline):
    """Pre-seed iter_0000..iter_0002 on disk and verify cma_warm picks
    them up as warm-start prior."""
    output_dir, lmat = patched_pipeline
    # Manually create 3 prior iterations the way the heuristic would.
    auto_dir = output_dir / "auto_adjust"
    auto_dir.mkdir(parents=True, exist_ok=True)
    for i, fit_score in enumerate([0.40, 0.45, 0.55]):
        iter_dir = auto_dir / f"iter_{i:04d}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        cand_dir = iter_dir / "candidate"
        cand_dir.mkdir(parents=True, exist_ok=True)
        params = dict(_initial_params())
        params["u_Gamma_Power"] = 2.2 + 0.1 * i
        (cand_dir / "params.json").write_text(json.dumps(params), encoding="utf-8")
        decision = {
            "iteration": i,
            "fit_score_before": fit_score,
            "diff_score_before": 1.0 - fit_score,
            "decision": {"optimizer": "heuristic", "stop_reason": "continue"},
        }
        (iter_dir / "decision.json").write_text(json.dumps(decision), encoding="utf-8")

    # Now run CMA-ES warm starting from iter_0003.
    # We need to advance the AdjustmentState's iteration counter to 3 so
    # _run_auto_adjustment creates iter_0003.json (it always uses
    # state.iteration). Easiest path: run heuristic once first to land
    # at iteration 1, then re-run cma_warm — but the simpler thing is
    # just to delete existing dir and feed the history through
    # _load_warm_start_history's logic by leaving iter_000{0..2}.
    # _run_auto_adjustment starts state.iteration at 0, but the
    # iter_dir = auto_dir / iter_0000 already exists with prior data.
    # That's actually fine — fit_material happily writes into the same
    # dir, just overwriting decision.json. To avoid mixing histories
    # we put cma_warm output into a fresh subdir:
    fresh_output = output_dir / "warm_run"
    fresh_output.mkdir(parents=True, exist_ok=True)
    fresh_auto = fresh_output / "auto_adjust"
    fresh_auto.mkdir(parents=True, exist_ok=True)
    # Copy the 3 prior iters into the fresh output dir so
    # _load_warm_start_history finds them.
    import shutil
    for i in range(3):
        shutil.copytree(auto_dir / f"iter_{i:04d}", fresh_auto / f"iter_{i:04d}")

    driver = _StubDriver(fresh_output)
    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    result = fit_material._run_auto_adjustment(
        config={},
        project_root=output_dir,
        output_dir=fresh_output,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=2,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_warm",
        cma_es_config=CmaesStrategyConfig(mode="warm", seed=11, population_size=4, warm_start_iters=12),
    )
    assert result["optimizer"] == "cma_warm"
    assert result["warm_start_history_size"] == 3, (
        f"Expected the 3 pre-seeded iter_000{{0..2}} to be folded into the WS-CMA-ES "
        f"warm-start, got {result['warm_start_history_size']}"
    )
    last_decision = result["iterations"][-1]["decision"]
    assert last_decision["optimizer"] == "cma_es"
    assert last_decision["cma_es"]["warm_started"] is True


def test_fit_material_unknown_optimizer_returns_configuration_error(patched_pipeline):
    output_dir, lmat = patched_pipeline
    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="bogus_alg",
        iterations=2,
    )
    assert result["status"] == "configuration_error"
    assert "unknown optimizer" in result["reason"].lower()


def test_fit_material_cma_warm_with_no_history_falls_back_to_cold(patched_pipeline):
    output_dir, lmat = patched_pipeline
    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="cma_warm",
        iterations=2,
        cma_es_config=CmaesStrategyConfig(mode="warm", seed=0, population_size=4),
    )
    # Optimizer field still records what user asked for, for audit.
    assert result["optimizer"] == "cma_warm"
    assert result["warm_start_history_size"] == 0
    last_decision = result["iterations"][-1]["decision"]
    assert last_decision["cma_es"]["warm_started"] is False, (
        "WS-CMA-ES with empty history must fall back to cold rather than crash"
    )
