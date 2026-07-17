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

import argparse
import json
import sys
import threading
import time
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from tools.material_fit import fit_material  # noqa: E402
    from tools.material_fit.optimizer.strategy import CmaesStrategyConfig  # noqa: E402
    from tools.material_fit.shared.models import ShaderParam  # noqa: E402
except ModuleNotFoundError:
    import material_fit as material_fit_package  # noqa: E402
    from material_fit import fit_material  # noqa: E402
    from material_fit.optimizer.strategy import CmaesStrategyConfig  # noqa: E402
    from material_fit.shared.models import ShaderParam  # noqa: E402

    tools_package = types.ModuleType("tools")
    tools_package.__path__ = []  # type: ignore[attr-defined]
    tools_package.material_fit = material_fit_package
    sys.modules.setdefault("tools", tools_package)
    sys.modules.setdefault("tools.material_fit", material_fit_package)

from material_fit.optimizer.structured_fish_space import FishSearchCoordinate


# --------------------------------------------------------------------
# Fixtures


def test_searchable_proposal_quantization_suppresses_jitter_and_preserves_metadata() -> None:
    coordinate = FishSearchCoordinate(
        "u_GammaPower",
        None,
        "material_scalar",
        0.0,
        10.0,
        0.1,
    )
    metadata = {"candidate_id": "normal_y_invert"}
    first, first_audit = fit_material._quantize_searchable_proposal(
        {
            "u_GammaPower": 5.00031,
            "u_LockedValue": 7.25,
            "__material_fit_discrete_candidate__": metadata,
        },
        coordinates=[coordinate],
        normalized_step=0.0001,
    )
    second, second_audit = fit_material._quantize_searchable_proposal(
        {
            "u_GammaPower": 5.00033,
            "u_LockedValue": 7.25,
            "__material_fit_discrete_candidate__": metadata,
        },
        coordinates=[coordinate],
        normalized_step=0.0001,
    )

    assert first["u_GammaPower"] == second["u_GammaPower"] == pytest.approx(5.0)
    assert first["u_LockedValue"] == second["u_LockedValue"] == pytest.approx(7.25)
    assert first["__material_fit_discrete_candidate__"] == metadata
    assert second["__material_fit_discrete_candidate__"] == metadata
    assert first_audit["changed_coordinate_count"] == 1
    assert second_audit["changed_coordinate_count"] == 1


def test_decision_can_override_proposal_quantization_step() -> None:
    assert fit_material._proposal_quantization_step_for_decision({}, 0.0001) == pytest.approx(
        0.0001
    )
    assert fit_material._proposal_quantization_step_for_decision(
        {"proposal_quantization_normalized_step": 0.001},
        0.0001,
    ) == pytest.approx(0.001)
    with pytest.raises(ValueError):
        fit_material._proposal_quantization_step_for_decision(
            {"proposal_quantization_normalized_step": 0.02},
            0.0001,
        )


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


def test_initial_params_override_is_strict_handoff_boundary() -> None:
    base = {
        "u_TexPower": 1.0,
        "u_MainTex_ST": [1.0, 1.0, 0.0, 0.0],
    }

    applied = fit_material._apply_initial_params_override(
        base,
        {
            "u_TexPower": 2.5,
            "u_MainTex_ST": [1.0, 1.0, 0.0, 0.0],
        },
        source="stage_a/best/params.json",
    )

    assert applied == {
        "u_TexPower": 2.5,
        "u_MainTex_ST": [1.0, 1.0, 0.0, 0.0],
    }
    assert base["u_TexPower"] == 1.0

    with pytest.raises(ValueError, match="unknown"):
        fit_material._apply_initial_params_override(base, {"u_NewParam": 1.0}, source="bad.json")

    with pytest.raises(ValueError, match="shape"):
        fit_material._apply_initial_params_override(base, {"u_MainTex_ST": [1.0, 1.0]}, source="bad.json")


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


def _fake_multiview_result(fit_score: float = 0.10) -> dict:
    analysis = _fake_analysis()
    diff_score = 1.0 - fit_score
    return {
        "strategy_analysis": analysis,
        "multiview_analysis": {
            "summary": {
                "mean_diff_score": diff_score,
                "mean_fit_score": fit_score,
                "optimization_fit_score": fit_score,
                "optimization_fit_score_source": "test_fake",
            },
            "views": [
                {
                    "pair_index": 0,
                    "view_id": "test_view",
                    "diff_score": diff_score,
                    "fit_score": fit_score,
                }
            ],
        },
    }


def _browser_score_render_result(
    iteration: int,
    fit_score: float,
    *,
    foreground_sum: int = 60000,
    worst_fit_score: float | None = None,
) -> dict:
    diff_score = 1.0 - fit_score
    worst_diff_score = 1.0 - worst_fit_score if worst_fit_score is not None else diff_score
    views = [
        {
            "view_id": "v000_yaw0_pitch0",
            "fit_score": fit_score,
            "diff_score": diff_score,
            "foreground_weight_sum": foreground_sum,
        }
    ]
    if worst_fit_score is not None:
        views.append(
            {
                "view_id": "v002_yaw90_pitch0",
                "fit_score": worst_fit_score,
                "diff_score": worst_diff_score,
                "foreground_weight_sum": foreground_sum,
            }
        )
    return {
        "status": "ok",
        "iteration": iteration,
        "screenshots": [],
        "browser_score": {
            "enabled": True,
            "metric": "browser_fast_rgba_mae_v1",
            "fit_score": fit_score,
            "score": fit_score,
            "diff_score": diff_score,
            "worst_diff_score": worst_diff_score,
            "view_count": len(views),
            "views": views,
        },
    }


def test_browser_score_result_builds_strategy_payload() -> None:
    render_result = {
        "status": "ok",
        "persistent_result": {
            "browser_score": {
                "enabled": True,
                "metric": "browser_fast_rgba_mae_v1",
                "fit_score": 0.82,
                "diff_score": 0.18,
                "views": [
                    {
                        "view_id": "v000_yaw0_pitch0",
                        "fit_score": 0.82,
                        "diff_score": 0.18,
                    }
                ],
            }
        },
    }

    payload = fit_material._browser_score_analysis_payload(render_result)

    assert payload["fit_score"] == pytest.approx(0.82)
    assert payload["diff_score"] == pytest.approx(0.18)
    assert payload["pair"]["view_id"] == "browser_score"
    assert payload["analysis"]["optimization_fit_score_source"] == "browser_score"
    assert payload["analysis"]["fit_score"] == pytest.approx(0.82)
    assert payload["multiview_analysis"]["summary"]["optimization_fit_score"] == pytest.approx(0.82)
    assert payload["multiview_analysis"]["summary"]["optimization_fit_score_source"] == "browser_score"


def test_browser_score_payload_can_optimize_mean_worst_blend() -> None:
    render_result = {
        "status": "ok",
        "browser_score": {
            "enabled": True,
            "metric": "browser_fast_rgba_mae_v1",
            "fit_score": 0.90,
            "diff_score": 0.10,
            "worst_diff_score": 0.14,
            "views": [
                {"view_id": "v000", "fit_score": 0.94, "diff_score": 0.06},
                {"view_id": "v090", "fit_score": 0.86, "diff_score": 0.14},
            ],
        },
    }

    payload = fit_material._browser_score_analysis_payload(
        render_result,
        config={
            "browser_score_objective": {
                "mode": "mean_worst_blend",
                "worst_view_weight": 0.5,
            }
        },
    )

    assert payload["diff_score"] == pytest.approx(0.12)
    assert payload["fit_score"] == pytest.approx(0.88)
    summary = payload["multiview_analysis"]["summary"]
    assert summary["mean_diff_score"] == pytest.approx(0.10)
    assert summary["worst_diff_score"] == pytest.approx(0.14)
    assert summary["optimization_diff_score"] == pytest.approx(0.12)
    assert summary["optimization_fit_score"] == pytest.approx(0.88)
    assert summary["optimization_fit_score_source"] == "browser_score_mean_worst_blend"


def test_browser_score_payload_can_optimize_reference_foreground_mae(tmp_path: Path) -> None:
    from PIL import Image

    ref_dir = tmp_path / "ref"
    cand_dir = tmp_path / "cand"
    ref_dir.mkdir()
    cand_dir.mkdir()
    ref_path = ref_dir / "view.png"
    cand_path = cand_dir / "view.png"
    ref = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
    ref.putpixel((0, 0), (255, 0, 0, 255))
    ref.save(ref_path)
    Image.new("RGBA", (2, 1), (255, 255, 255, 255)).save(cand_path)
    render_result = {
        "status": "ok",
        "screenshots": [str(cand_path)],
        "browser_score": {
            "enabled": True,
            "metric": "browser_fast_rgba_mae_v1",
            "fit_score": 0.99,
            "diff_score": 0.01,
            "views": [],
        },
    }

    payload = fit_material._browser_score_analysis_payload(
        render_result,
        config={
            "laya_capture": {
                "browser_score": {
                    "reference_images": [{"view_id": "v000", "path": str(ref_path)}],
                }
            },
            "browser_score_objective": {"mode": "reference_foreground_mae"},
        },
    )

    assert payload["fit_score"] == pytest.approx(1.0 / 3.0)
    assert payload["diff_score"] == pytest.approx(2.0 / 3.0)
    summary = payload["multiview_analysis"]["summary"]
    assert summary["optimization_fit_score_source"] == "browser_score_reference_foreground_mae"
    assert summary["foreground_pixel_count"] == 1


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


class _SlowTrackingDriver(_StubDriver):
    """Driver that proves candidate evaluation can overlap."""

    def __init__(self, output_dir: Path, *, delay_s: float = 0.05) -> None:
        super().__init__(output_dir)
        self.delay_s = delay_s
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def render_candidate(self, iteration: int, params: dict) -> dict:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay_s)
            return super().render_candidate(iteration, params)
        finally:
            with self.lock:
                self.active -= 1


class _WorkerPoolTrackingDriver(_StubDriver):
    """Driver that detects overlapping work on the same isolated worker."""

    parallel_safe = True

    def __init__(self, output_dir: Path, *, worker_count: int = 2) -> None:
        super().__init__(output_dir)
        self.worker_count = worker_count
        self.active = 0
        self.max_active = 0
        self.active_by_worker = {index: 0 for index in range(worker_count)}
        self.max_active_by_worker = {index: 0 for index in range(worker_count)}
        self.lock = threading.Lock()

    def render_candidate(self, iteration: int, params: dict) -> dict:
        worker_index = iteration % self.worker_count
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.active_by_worker[worker_index] += 1
            self.max_active_by_worker[worker_index] = max(
                self.max_active_by_worker[worker_index],
                self.active_by_worker[worker_index],
            )
        try:
            # Make worker 0 slower so a naive "max workers == worker_count"
            # executor can still overlap iteration 0 and 2 on the same worker.
            time.sleep(0.08 if worker_index == 0 else 0.01)
            self.calls.append((iteration, params))
            return {
                "screenshots": [],
                "iteration": iteration,
                "worker": {"index": worker_index, "name": f"worker-{worker_index}"},
            }
        finally:
            with self.lock:
                self.active_by_worker[worker_index] -= 1
                self.active -= 1


class _BrowserScoreSequenceDriver(_StubDriver):
    """Driver that returns browser_score payloads from a fixed score sequence."""

    def __init__(self, output_dir: Path, scores: list[float | None]) -> None:
        super().__init__(output_dir)
        self.scores = list(scores)
        self.reset_calls = 0

    def render_candidate(self, iteration: int, params: dict) -> dict:
        self.calls.append((iteration, params))
        score = self.scores.pop(0)
        if score is None:
            return {
                "status": "failed",
                "returncode": 4,
                "stderr": "simulated timeout waiting for persistent render result",
                "params_path": str(self.output_dir / f"params_{iteration:04d}.json"),
                "screenshots": [],
            }
        return _browser_score_render_result(iteration, score)

    def reset_persistent_queue(self) -> bool:
        self.reset_calls += 1
        return True


class _FreshOracleValidationDriver(_BrowserScoreSequenceDriver):
    """Browser-score driver that exposes fresh-oracle stability validation."""

    def __init__(
        self,
        output_dir: Path,
        scores: list[float | None],
        *,
        validation_score: float,
        validation_records: list[float] | None = None,
        validation_foreground_sums: list[int] | None = None,
    ) -> None:
        super().__init__(output_dir, scores)
        self.validation_score = validation_score
        self.validation_records = list(validation_records or [])
        self.validation_foreground_sums = list(validation_foreground_sums or [])
        self.fresh_validation_calls: list[dict] = []

    def validate_persistent_oracle_stability(
        self,
        *,
        iteration: int,
        params: dict,
        attempts: int,
        output_subdir: str = "fresh_oracle_validation",
    ) -> dict:
        self.fresh_validation_calls.append(
            {
                "iteration": iteration,
                "params": dict(params),
                "attempts": attempts,
                "output_subdir": output_subdir,
            }
        )
        records = []
        for index, score in enumerate(self.validation_records):
            fit_score = float(score)
            record = {"attempt_index": index, "fit_score": fit_score, "diff_score": 1.0 - fit_score}
            if index < len(self.validation_foreground_sums):
                foreground_sum = int(self.validation_foreground_sums[index])
                record["browser_score"] = {
                    "fit_score": fit_score,
                    "diff_score": 1.0 - fit_score,
                    "views": [
                        {
                            "view_id": "v000_yaw0_pitch0",
                            "fit_score": fit_score,
                            "diff_score": 1.0 - fit_score,
                            "foreground_weight_sum": foreground_sum,
                        }
                    ],
                }
            records.append(record)
        return {
            "status": "ok",
            "attempts_requested": attempts,
            "attempts_completed": attempts,
            "attempts_scored": attempts,
            "score_policy": "fresh_oracle_min",
            "conservative_fit_score": self.validation_score,
            "conservative_diff_score": 1.0 - self.validation_score,
            "fit_score_min": self.validation_score,
            "fit_score_median": 0.88,
            "fit_score_mean": 0.88,
            "fit_score_max": 0.95,
            "fit_score_spread": 0.95 - self.validation_score,
            "records": records,
        }


class _OracleFreshValidationDriver(_FreshOracleValidationDriver):
    """Fresh-oracle validation driver with a selected oracle foreground mode."""

    def __init__(
        self,
        output_dir: Path,
        scores: list[float | None],
        *,
        validation_score: float,
        validation_records: list[float] | None = None,
        validation_foreground_sums: list[int] | None = None,
        selected_foreground_sum: int = 61000,
    ) -> None:
        super().__init__(
            output_dir,
            scores,
            validation_score=validation_score,
            validation_records=validation_records,
            validation_foreground_sums=validation_foreground_sums,
        )
        self.selected_foreground_sum = selected_foreground_sum
        self.selection_calls: list[dict] = []

    def select_persistent_oracle(
        self,
        *,
        iteration: int,
        params: dict,
        attempts: int,
        min_fit_score: float | None = None,
        output_subdir: str = "oracle_stabilization",
        probe_candidates: list[dict] | None = None,
        selection_policy: str = "best",
    ) -> dict:
        self.selection_calls.append(
            {
                "iteration": iteration,
                "params": dict(params),
                "attempts": attempts,
                "min_fit_score": min_fit_score,
                "output_subdir": output_subdir,
                "selection_policy": selection_policy,
                "probe_candidates": json.loads(json.dumps(probe_candidates)) if probe_candidates else None,
            }
        )
        return {
            "status": "ok",
            "attempts_requested": attempts,
            "attempts_completed": attempts,
            "selected_attempt": 0,
            "selected_fit_score": 0.91,
            "records": [
                {
                    "attempt": 0,
                    "status": "ok",
                    "fit_score": 0.91,
                    "browser_score": {
                        "fit_score": 0.91,
                        "diff_score": 0.09,
                        "views": [
                            {
                                "view_id": "v000_yaw0_pitch0",
                                "fit_score": 0.91,
                                "diff_score": 0.09,
                                "foreground_weight_sum": self.selected_foreground_sum,
                            }
                        ],
                    },
                }
            ],
        }


class _FreshOraclePerParamValidationDriver(_BrowserScoreSequenceDriver):
    """Browser-score driver that returns fresh-oracle validation by candidate params."""

    def __init__(
        self,
        output_dir: Path,
        scores: list[float | None],
        *,
        validation_scores_by_gamma: dict[float, float],
    ) -> None:
        super().__init__(output_dir, scores)
        self.validation_scores_by_gamma = {
            round(float(gamma), 4): float(score) for gamma, score in validation_scores_by_gamma.items()
        }
        self.fresh_validation_calls: list[dict] = []

    def validate_persistent_oracle_stability(
        self,
        *,
        iteration: int,
        params: dict,
        attempts: int,
        output_subdir: str = "fresh_oracle_validation",
    ) -> dict:
        gamma = round(float(params["u_Gamma_Power"]), 4)
        score = self.validation_scores_by_gamma[gamma]
        self.fresh_validation_calls.append(
            {
                "iteration": iteration,
                "params": dict(params),
                "attempts": attempts,
                "output_subdir": output_subdir,
                "selected_fit_score": score,
            }
        )
        return {
            "status": "ok",
            "attempts_requested": attempts,
            "attempts_completed": attempts,
            "attempts_scored": attempts,
            "score_policy": "fresh_oracle_median",
            "conservative_fit_score": score,
            "conservative_diff_score": 1.0 - score,
            "fit_score_min": score,
            "fit_score_median": score,
            "fit_score_mean": score,
            "fit_score_max": score,
            "fit_score_spread": 0.0,
            "records": [],
        }


class _FreshOracleBatchValidationDriver(_BrowserScoreSequenceDriver):
    """Browser-score driver that batch-validates candidates by params."""

    def __init__(
        self,
        output_dir: Path,
        scores: list[float | None],
        *,
        validation_scores_by_gamma: dict[float, float],
    ) -> None:
        super().__init__(output_dir, scores)
        self.validation_scores_by_gamma = {
            round(float(gamma), 4): float(score) for gamma, score in validation_scores_by_gamma.items()
        }
        self.batch_validation_calls: list[dict] = []

    def validate_persistent_oracle_stability(self, **kwargs) -> dict:
        raise AssertionError("top-k stability feedback should use batch fresh-oracle validation")

    def validate_persistent_oracle_stability_many(
        self,
        *,
        iteration: int,
        candidates: list[dict],
        attempts: int,
        output_subdir: str = "fresh_oracle_batch_validation",
    ) -> dict:
        self.batch_validation_calls.append(
            {
                "iteration": iteration,
                "candidates": json.loads(json.dumps(candidates)),
                "attempts": attempts,
                "output_subdir": output_subdir,
            }
        )
        candidate_summaries = []
        for candidate_index, candidate in enumerate(candidates):
            params = candidate["params"]
            gamma = round(float(params["u_Gamma_Power"]), 4)
            score = self.validation_scores_by_gamma[gamma]
            candidate_summaries.append(
                {
                    "status": "ok",
                    "candidate_index": candidate_index,
                    "candidate_id": candidate.get("candidate_id", f"candidate_{candidate_index:02d}"),
                    "attempts_requested": attempts,
                    "attempts_completed": attempts,
                    "attempts_scored": attempts,
                    "score_policy": "fresh_oracle_median",
                    "conservative_fit_score": score,
                    "conservative_diff_score": 1.0 - score,
                    "fit_score_min": score,
                    "fit_score_median": score,
                    "fit_score_mean": score,
                    "fit_score_max": score,
                    "fit_score_spread": 0.0,
                    "records": [],
                }
            )
        return {
            "status": "ok",
            "attempts_requested": attempts,
            "attempts_completed": attempts,
            "candidate_count": len(candidate_summaries),
            "candidates_scored": len(candidate_summaries),
            "score_policy": "fresh_oracle_median",
            "candidates": candidate_summaries,
        }


class _OracleSelectionDriver(_StubDriver):
    """Driver that records oracle selection before normal candidate renders."""

    def __init__(self, output_dir: Path) -> None:
        super().__init__(output_dir)
        self.events: list[tuple[str, int | None]] = []
        self.selection_calls: list[dict] = []

    def select_persistent_oracle(
        self,
        *,
        iteration: int,
        params: dict,
        attempts: int,
        min_fit_score: float | None = None,
        output_subdir: str = "oracle_stabilization",
        probe_candidates: list[dict] | None = None,
        selection_policy: str = "best",
    ) -> dict:
        self.events.append(("select", iteration))
        self.selection_calls.append(
            {
                "iteration": iteration,
                "params": dict(params),
                "probe_candidates": json.loads(json.dumps(probe_candidates)) if probe_candidates is not None else None,
                "attempts": attempts,
                "min_fit_score": min_fit_score,
                "output_subdir": output_subdir,
                "selection_policy": selection_policy,
            }
        )
        return {
            "status": "ok",
            "attempts_requested": attempts,
            "attempts_completed": attempts,
            "selected_attempt": 1,
            "selected_fit_score": 0.91,
        }

    def render_candidate(self, iteration: int, params: dict) -> dict:
        self.events.append(("render", iteration))
        return super().render_candidate(iteration, params)


class _DuplicateBatchStrategy:
    """Batch strategy that deliberately emits duplicate parameters."""

    def __init__(self) -> None:
        self.tell_many_scores_calls: list[list[tuple[float, float]]] = []

    def propose_many(self, ctx, *, count: int):
        assert count == 3
        base = dict(ctx.current_params)
        first = {**base, "u_Gamma_Power": 2.5}
        duplicate = {**base, "u_Gamma_Power": 2.5}
        third = {**base, "u_Gamma_Power": 3.0}
        proposals = [first, duplicate, third]
        return [
            (
                params,
                {
                    "optimizer": "cma_es",
                    "cma_es": {
                        "evaluations": len(self.tell_many_scores_calls) * 3,
                        "batch": {"index": index, "size": count},
                    },
                },
            )
            for index, params in enumerate(proposals)
        ]

    def tell_many_scores(self, score_pairs):
        self.tell_many_scores_calls.append(list(score_pairs))

    def stop_reason(self):
        return None

    def research_summary(self):
        return {}


class _UniqueBatchStrategy:
    """Batch strategy with deterministic unique proposals."""

    def __init__(self) -> None:
        self.tell_many_scores_calls: list[list[tuple[float, float]]] = []

    def propose_many(self, ctx, *, count: int):
        base = dict(ctx.current_params)
        return [
            (
                {**base, "u_Gamma_Power": 2.0 + 0.1 * index},
                {
                    "optimizer": "cma_es",
                    "cma_es": {
                        "evaluations": len(self.tell_many_scores_calls) * count,
                        "batch": {"index": index, "size": count},
                    },
                },
            )
            for index in range(count)
        ]

    def tell_many_scores(self, score_pairs):
        self.tell_many_scores_calls.append(list(score_pairs))

    def stop_reason(self):
        return None

    def research_summary(self):
        return {}


class _TwoRoundUniqueBatchStrategy:
    """Batch strategy with deterministic unique proposals across two batches."""

    def __init__(self) -> None:
        self.tell_many_scores_calls: list[list[tuple[float, float]]] = []

    def propose_many(self, ctx, *, count: int):
        base = dict(ctx.current_params)
        batch_index = len(self.tell_many_scores_calls)
        gamma_base = 2.0 + batch_index
        return [
            (
                {**base, "u_Gamma_Power": gamma_base + 0.1 * index},
                {
                    "optimizer": "cma_es",
                    "cma_es": {
                        "evaluations": len(self.tell_many_scores_calls) * count,
                        "batch": {"index": index, "size": count},
                    },
                },
            )
            for index in range(count)
        ]

    def tell_many_scores(self, score_pairs):
        self.tell_many_scores_calls.append(list(score_pairs))

    def stop_reason(self):
        return None

    def research_summary(self):
        return {}


class _CurrentFirstBatchStrategy:
    """Batch strategy that emits the current params as the first proposal."""

    def __init__(self) -> None:
        self.tell_many_scores_calls: list[list[tuple[float, float]]] = []

    def propose_many(self, ctx, *, count: int):
        base = dict(ctx.current_params)
        proposals = [
            base,
            {**base, "u_Gamma_Power": 2.7},
        ][:count]
        return [
            (
                params,
                {
                    "optimizer": "cma_es",
                    "stage": {"name": "cma_initial_design"},
                    "cma_es": {
                        "evaluations": len(self.tell_many_scores_calls) * count,
                        "batch": {"index": index, "size": count},
                        "initial_design": {
                            "enabled": True,
                            "requested_samples": count,
                            "include_current": True,
                        },
                    },
                },
            )
            for index, params in enumerate(proposals)
        ]

    def tell_many_scores(self, score_pairs):
        self.tell_many_scores_calls.append(list(score_pairs))

    def stop_reason(self):
        return None

    def research_summary(self):
        return {}


class _ShortBatchStrategy:
    """Strategy that returns fewer candidates than requested."""

    def __init__(self) -> None:
        self.requested_counts: list[int] = []
        self.tell_many_scores_calls: list[list[tuple[float, float]]] = []

    def propose_many(self, ctx, *, count: int):
        self.requested_counts.append(count)
        base = dict(ctx.current_params)
        params = {**base, "u_Gamma_Power": 2.0 + 0.1 * len(self.tell_many_scores_calls)}
        return [
            (
                params,
                {
                    "optimizer": "cma_es",
                    "stage": {"name": "cma_initial_design"},
                    "cma_es": {
                        "evaluations": len(self.tell_many_scores_calls),
                        "batch": {"index": 0, "size": 1},
                        "initial_design": {
                            "enabled": True,
                            "requested_samples": 2,
                            "remaining_samples": max(0, 1 - len(self.tell_many_scores_calls)),
                        },
                    },
                },
            )
        ]

    def tell_many_scores(self, score_pairs):
        self.tell_many_scores_calls.append(list(score_pairs))

    def stop_reason(self):
        return None

    def research_summary(self):
        return {}


class _FailingTellBatchStrategy:
    """Batch strategy that fails after candidates have been evaluated."""

    def propose_many(self, ctx, *, count: int):
        base = dict(ctx.current_params)
        return [
            (
                {**base, "u_Gamma_Power": 2.5 + 0.1 * index},
                {
                    "optimizer": "cma_es",
                    "cma_es": {
                        "evaluations": 0,
                        "batch": {"index": index, "size": count},
                    },
                },
            )
            for index in range(count)
        ]

    def tell_many_scores(self, score_pairs):
        raise RuntimeError("simulated optimizer failure after evaluated batch")

    def stop_reason(self):
        return None

    def research_summary(self):
        return {}


@pytest.fixture
def patched_pipeline(monkeypatch, tmp_path):
    """Stub out image diff + driver and pre-build minimal disk state.

    Returns ``(output_dir, laya_material_path)`` so each test can call
    ``fit_material._run_auto_adjustment`` with the right paths.
    """

    fake_pair = {"reference": str(tmp_path / "ref.png"), "candidate": str(tmp_path / "cand.png")}
    from PIL import Image

    Image.new("RGB", (16, 16), (120, 120, 120)).save(tmp_path / "ref.png")
    Image.new("RGB", (16, 16), (130, 120, 120)).save(tmp_path / "cand.png")

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
    monkeypatch.setattr(
        fit_material,
        "analyze_multiview_pairs",
        lambda *args, **kwargs: _fake_multiview_result(),
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
    fit_score_mode: str = "perceptual",
    config: dict | None = None,
    cma_es_config: CmaesStrategyConfig | None = None,
) -> dict:
    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    return fit_material._run_auto_adjustment(
        config=config or {},
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
        fit_score_mode=fit_score_mode,
        optimizer=optimizer,
        cma_es_config=cma_es_config,
    )


def _load_iteration_decision(output_dir: Path, entry: dict) -> dict:
    payload = json.loads(
        (output_dir / "auto_adjust" / str(entry["iter_id"]) / "decision.json").read_text(
            encoding="utf-8",
        )
    )
    return payload["decision"]


def test_fit_material_prepares_oracle_before_first_optimizer_render(patched_pipeline):
    output_dir, lmat = patched_pipeline

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _OracleSelectionDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "laya_capture": {
                "oracle_stabilization": {
                    "enabled": True,
                    "attempts": 3,
                    "min_fit_score": 0.90,
                    "iteration": -700,
                    "output_subdir": "oracle_select",
                    "selection_policy": "median",
                }
            }
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=1,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert driver.events[:2] == [("select", -700), ("render", 0)]
    assert driver.selection_calls[0]["attempts"] == 3
    assert driver.selection_calls[0]["min_fit_score"] == pytest.approx(0.90)
    assert driver.selection_calls[0]["selection_policy"] == "median"
    assert driver.selection_calls[0]["params"] == _initial_params()
    assert result["oracle_stabilization"]["selected_fit_score"] == pytest.approx(0.91)
    summary_path = output_dir / "auto_adjust" / "oracle_stabilization.json"
    assert summary_path.exists()
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    assert persisted["selected_attempt"] == 1
    assert persisted["config"]["selection_policy"] == "median"


def test_fit_material_oracle_stabilization_can_use_probe_params(patched_pipeline):
    output_dir, lmat = patched_pipeline

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    probe_params = {**_initial_params(), "u_Gamma_Power": 4.4}
    driver = _OracleSelectionDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "oracle_stabilization": {
                "enabled": True,
                "attempts": 2,
                "probe_params": probe_params,
            }
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=1,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert driver.selection_calls[0]["params"] == probe_params
    assert result["oracle_stabilization"]["config"]["params_source"] == "probe_params"
    assert result["oracle_stabilization"]["config"]["probe_param_count"] == len(probe_params)


def test_fit_material_oracle_stabilization_can_use_probe_portfolio(patched_pipeline):
    output_dir, lmat = patched_pipeline

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    probe_portfolio = [
        {"label": "zero", "params": {"u_Metallic": 0.0, "u_Gamma_Power": 0.0}},
        {"label": "prior_best", "params": {**_initial_params(), "u_Gamma_Power": 4.4}},
    ]
    driver = _OracleSelectionDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "oracle_stabilization": {
                "enabled": True,
                "attempts": 2,
                "probe_portfolio": probe_portfolio,
            }
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=1,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert driver.selection_calls[0]["probe_candidates"] == probe_portfolio
    assert driver.selection_calls[0]["params"] == probe_portfolio[0]["params"]
    assert result["oracle_stabilization"]["config"]["params_source"] == "probe_portfolio"
    assert result["oracle_stabilization"]["config"]["probe_candidate_count"] == 2
    assert result["oracle_stabilization"]["config"]["probe_labels"] == ["zero", "prior_best"]


def test_cold_start_prior_anchors_from_config_returns_deep_copied_list():
    raw_anchor = {
        "label": "external_case_prior",
        "param_values": {"u_GammaPower": 2.25},
    }
    anchors = fit_material._cold_start_prior_anchors_from_config(
        {
            "cold_start_hybrid": {
                "prior_anchors": [raw_anchor, "ignored"],
            },
        }
    )

    assert anchors == [raw_anchor]
    anchors[0]["param_values"]["u_GammaPower"] = 9.0
    assert raw_anchor["param_values"]["u_GammaPower"] == pytest.approx(2.25)


def test_fit_material_passes_cold_start_prior_anchors_to_strategy(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    prior_anchors = [
        {
            "label": "external_case_prior",
            "param_values": {"u_GammaPower": 2.25},
        }
    ]
    captured: dict[str, Any] = {}
    strategy = _UniqueBatchStrategy()

    def fake_build_strategy(**kwargs):
        captured.update(kwargs)
        return strategy

    monkeypatch.setattr(fit_material, "build_strategy", fake_build_strategy)

    _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="cold_start_hybrid",
        iterations=1,
        config={
            "cold_start_hybrid": {"prior_anchors": prior_anchors},
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "evaluation_workers": 2,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
    )

    assert captured["cold_start_prior_anchors"] == prior_anchors
    captured["cold_start_prior_anchors"][0]["param_values"]["u_GammaPower"] = 9.0
    assert prior_anchors[0]["param_values"]["u_GammaPower"] == pytest.approx(2.25)


def test_fit_material_rejects_human_target_teacher_optimizer(patched_pipeline):
    output_dir, lmat = patched_pipeline
    target_params = {**_initial_params(), "u_Gamma_Power": 3.4}
    target_path = output_dir / "inputs/human_target_params.json"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(target_params), encoding="utf-8")

    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="human_target",
        iterations=1,
        config={"human_target": {"params_path": str(target_path)}},
    )

    assert result["status"] == "configuration_error"
    assert result["optimizer"] == "human_target"
    assert "unknown optimizer" in result["reason"]
    assert not (output_dir / "human_target_params.json").exists()


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
        assert entry["optimizer"] == "heuristic"


def test_fit_material_records_optimizer_preset_metadata(patched_pipeline):
    output_dir, lmat = patched_pipeline
    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="heuristic",
        iterations=1,
        config={"optimizer_preset": "cma_mature_default"},
    )

    assert result["optimizer_preset"] == "cma_mature_default"
    summary = result["optimizer_evidence_summary"]
    assert summary["optimizer_preset"] == "cma_mature_default"
    assert summary["optimizer"] == "heuristic"
    assert summary["status"] == "max_iterations_reached"
    assert summary["iterations"] == 1
    assert summary["batch_execution"]["enabled"] is False
    assert Path(result["optimizer_evidence_summary_path"]).name == "optimizer_evidence_summary.json"
    summary_path_payload = json.loads(Path(result["optimizer_evidence_summary_path"]).read_text(encoding="utf-8"))
    assert summary_path_payload == summary


def test_iteration_series_entry_records_research_validity_summary():
    entry = fit_material._iteration_series_entry(
        {
            "iteration": 7,
            "selected_stage": "cma",
            "diff_score_before": 0.2,
            "fit_score_before": 0.3,
            "target_score": 0.98,
            "decision": {"optimizer": "cma_es"},
            "perceptual_signals": {
                "research_metrics": {
                    "status": "ok_with_invalid_views",
                    "profile": "fast",
                    "score_is_proxy": True,
                    "score": 31.5,
                    "loss": 0.685,
                    "valid_view_count": 0,
                    "invalid_view_count": 8,
                    "scored_invalid_view_count": 8,
                    "score_uses_invalid_views": True,
                    "validity": {
                        "passed": False,
                        "passed_view_count": 0,
                        "failed_view_count": 8,
                        "mask_iou": 0.82,
                        "mask_iou_min": 0.71,
                        "bbox_center_error_px_max": 23.0,
                        "bbox_scale_error_max": 0.15,
                        "reasons": ["mask_iou below 0.990"],
                    },
                    "guidance": {
                        "validity_penalty_applied": True,
                        "validity_penalty": {
                            "mode": "soft_alignment_penalty",
                            "loss": 0.62,
                        },
                    },
                },
            },
        },
        is_snapshot=True,
        is_best=False,
    )

    assert entry["research_validity"] == {
        "status": "ok_with_invalid_views",
        "profile": "fast",
        "score_is_proxy": True,
        "valid_view_count": 0,
        "invalid_view_count": 8,
        "passed": False,
        "mask_iou_min": 0.71,
        "bbox_center_error_px_max": 23.0,
        "bbox_scale_error_max": 0.15,
        "reasons": ["mask_iou below 0.990"],
        "validity_penalty_applied": True,
        "validity_penalty_mode": "soft_alignment_penalty",
        "validity_penalty_loss": 0.62,
    }


def test_iteration_series_entry_keeps_scored_params_separate_from_next_candidate():
    scored_params = dict(_initial_params())
    candidate_params = {**scored_params, "u_Gamma_Power": 2.8}

    entry = fit_material._iteration_series_entry(
        {
            "iteration": 0,
            "fit_score_before": 0.42,
            "decision": {"optimizer": "cma_es"},
            "scored_params": scored_params,
            "score_params_role": "current_params",
            "candidate_params": candidate_params,
        },
        is_snapshot=True,
        is_best=True,
    )

    assert entry["scored_params"] == scored_params
    assert entry["score_params_role"] == "current_params"
    assert entry["candidate_params"] == candidate_params
    assert entry["scored_params"] != entry["candidate_params"]


def test_fit_material_nonbatch_records_scored_params_as_current_params(patched_pipeline):
    output_dir, lmat = patched_pipeline

    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="cma_cold",
        iterations=1,
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.10)
    assert result["iterations"][0]["scored_params"] == _initial_params()
    assert result["iterations"][0]["score_params_role"] == "current_params"

    decision_payload = json.loads(
        (output_dir / "auto_adjust" / "iter_0000" / "decision.json").read_text(encoding="utf-8")
    )
    assert decision_payload["scored_params"] == _initial_params()
    assert decision_payload["score_params_role"] == "current_params"


def test_warm_start_history_prefers_score_aligned_params_from_decision(patched_pipeline):
    output_dir, _lmat = patched_pipeline
    auto_dir = output_dir / "auto_adjust"
    iter_dir = auto_dir / "iter_0000"
    candidate_dir = iter_dir / "candidate"
    candidate_dir.mkdir(parents=True, exist_ok=True)

    proposed_params = {**_initial_params(), "u_Gamma_Power": 9.0}
    scored_params = {**_initial_params(), "u_Gamma_Power": 3.0}
    (candidate_dir / "params.json").write_text(json.dumps(proposed_params), encoding="utf-8")
    (iter_dir / "decision.json").write_text(
        json.dumps(
            {
                "fit_score_before": 0.77,
                "diff_score_before": 0.23,
                "scored_params": scored_params,
                "score_params_role": "current_params",
            }
        ),
        encoding="utf-8",
    )

    history, sources = fit_material._load_optimizer_warm_start_history(
        auto_dir,
        limit=1,
        source="iteration_history",
    )

    assert sources["iteration_history"] == 1
    assert history == [(scored_params, pytest.approx(0.77))]


def test_elite_archive_history_prefers_embedded_scored_params(patched_pipeline):
    output_dir, _lmat = patched_pipeline
    auto_dir = output_dir / "auto_adjust"
    candidate_dir = auto_dir / "iter_0000" / "candidate"
    candidate_dir.mkdir(parents=True, exist_ok=True)

    proposed_params = {**_initial_params(), "u_Gamma_Power": 9.0}
    scored_params = {**_initial_params(), "u_Gamma_Power": 3.0}
    params_path = candidate_dir / "params.json"
    params_path.write_text(json.dumps(proposed_params), encoding="utf-8")
    (auto_dir / "optimizer_candidate_archive.json").write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "iteration": 0,
                        "iter_id": "iter_0000",
                        "fit_score": 0.77,
                        "params_path": str(params_path),
                        "candidate_params": proposed_params,
                        "scored_params": scored_params,
                        "score_params_role": "current_params",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    history, sources = fit_material._load_optimizer_warm_start_history(
        auto_dir,
        limit=1,
        source="elite_archive_only",
    )

    assert sources["elite_archive"] == 1
    assert history == [(scored_params, pytest.approx(0.77))]


def test_fit_material_cli_optimizer_preset_applies_mature_defaults():
    config = {
        "optimizer": "heuristic",
        "optimizer_preset": "manual",
        "cma_es": {
            "seed": 99,
            "stagnation_patience": 0,
            "restart_population_schedule": "ipop",
            "initial_design_samples": 0,
        },
        "analysis_performance": {
            "evaluation_batch_size": 1,
            "evaluation_workers": 1,
        },
    }

    merged = fit_material._apply_optimizer_preset_override(config, "cma_mature_default")

    assert config["optimizer"] == "heuristic"
    assert config["cma_es"]["stagnation_patience"] == 0
    assert merged["optimizer"] == "cma_warm"
    assert merged["optimizer_preset"] == "cma_mature_default"
    assert merged["cma_es"]["seed"] == 99
    assert merged["cma_es"]["stagnation_patience"] == 64
    assert merged["cma_es"]["stagnation_max_restarts"] == 8
    assert merged["cma_es"]["stagnation_stop_after_restarts"] is False
    assert merged["cma_es"]["restart_center_mode"] == "alternate"
    assert merged["cma_es"]["restart_population_multiplier"] == pytest.approx(2.0)
    assert merged["cma_es"]["restart_population_schedule"] == "bipop"
    assert merged["cma_es"]["initial_design_samples"] == 33
    assert merged["cma_es"]["initial_design_method"] == "local_coordinate_probe"
    assert merged["cma_es"]["initial_design_local_step_ratio"] == pytest.approx(0.03)
    assert merged["analysis_performance"]["evaluation_batch_size"] == 8
    assert merged["analysis_performance"]["evaluation_workers"] == 4
    assert merged["analysis_performance"]["full_rerank_top_k"] == 1


def test_fit_material_writes_optimizer_candidate_archive(monkeypatch, patched_pipeline):
    output_dir, lmat = patched_pipeline

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        if "iter_0000" in analysis_dir_text:
            return _fake_multiview_result(0.20)
        if "iter_0001" in analysis_dir_text:
            return _fake_multiview_result(0.70)
        if "iter_0002" in analysis_dir_text:
            return _fake_multiview_result(0.40)
        raise AssertionError(f"unexpected analysis dir {analysis_dir_text!r}")

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)

    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="heuristic",
        iterations=3,
    )

    archive = result["optimizer_candidate_archive"]
    archive_path = Path(result["optimizer_candidate_archive_path"])
    assert archive_path.name == "optimizer_candidate_archive.json"
    assert json.loads(archive_path.read_text(encoding="utf-8")) == archive

    assert archive["top_k"] == 20
    assert archive["total_candidates"] == 3
    assert archive["best"]["iteration"] == 1
    assert archive["best"]["fit_score"] == pytest.approx(0.70)
    assert [item["iteration"] for item in archive["candidates"]] == [1, 2, 0]
    assert [item["fit_score"] for item in archive["candidates"]] == pytest.approx([0.70, 0.40, 0.20])
    assert all(Path(item["params_path"]).name == "params.json" for item in archive["candidates"])

    summary_archive = result["optimizer_evidence_summary"]["candidate_archive"]
    assert summary_archive["top_k"] == 20
    assert summary_archive["total_candidates"] == 3
    assert summary_archive["best_iteration"] == 1
    assert summary_archive["best_fit_score"] == pytest.approx(0.70)
    assert summary_archive["path"] == str(archive_path)


def test_fit_material_tiered_research_profile_uses_full_snapshots_and_fast_regular_iterations(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    seen_profiles: list[str | None] = []

    def fake_multiview(*args, **kwargs):
        seen_profiles.append(kwargs.get("research_metrics_profile"))
        return _fake_multiview_result()

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)

    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="heuristic",
        iterations=3,
        config={
            "analysis_performance": {
                "snapshot_interval": 2,
                "research_metrics_profile": "tiered",
            },
        },
    )

    assert result["status"] == "max_iterations_reached"
    assert seen_profiles == ["full", "fast", "full"]
    assert [entry["timing"]["research_metrics_profile"] for entry in result["iterations"]] == ["full", "fast", "full"]


def test_fit_material_cma_fast_score_only_is_limited_to_fast_research_iterations(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    seen: list[tuple[str | None, bool | None]] = []

    def fake_multiview(*args, **kwargs):
        seen.append((kwargs.get("research_metrics_profile"), kwargs.get("fast_score_only")))
        return _fake_multiview_result()

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)

    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="cma_cold",
        iterations=3,
        fit_score_mode="research",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
        config={
            "analysis_performance": {
                "snapshot_interval": 2,
                "research_metrics_profile": "tiered",
                "fast_score_only": True,
            },
        },
    )

    assert result["status"] == "max_iterations_reached"
    assert seen == [("full", False), ("fast", True), ("full", False)]
    assert [entry["timing"]["fast_score_only_enabled"] for entry in result["iterations"]] == [False, True, False]


def test_fit_material_records_evaluation_batch_size_config(patched_pipeline):
    output_dir, lmat = patched_pipeline
    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="cma_cold",
        iterations=2,
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
        config={
            "analysis_performance": {
                "evaluation_batch_size": 4,
            },
        },
    )

    assert result["analysis_performance"]["evaluation_batch_size"] == 4
    assert [entry["timing"]["evaluation_batch_size"] for entry in result["iterations"]] == [4, 4]


def test_score_ceiling_config_derives_reachable_effective_target() -> None:
    ceiling = fit_material._resolve_score_ceiling(
        {
            "score_ceiling": {
                "enabled": True,
                "target_self_score": 0.9647406955,
                "tolerance": 0.001,
                "source": "same_renderer_reachability",
            }
        },
        target_score=0.98,
    )

    assert ceiling == {
        "enabled": True,
        "target_self_score": pytest.approx(0.9647406955),
        "tolerance": pytest.approx(0.001),
        "effective_target_score": pytest.approx(0.9637406955),
        "raw_target_score": pytest.approx(0.98),
        "source": "same_renderer_reachability",
        "active": True,
    }
    assert fit_material._target_stop_reason(
        0.9641133424,
        target_score=0.98,
        score_ceiling=ceiling,
    ) == "score_ceiling_reached"


def test_score_ceiling_can_be_calibrated_from_selected_oracle_score() -> None:
    ceiling = fit_material._resolve_score_ceiling(
        {
            "score_ceiling": {
                "enabled": True,
                "target_self_score": 0.9647406955,
                "tolerance": 0.001,
                "source": "same_renderer_reachability",
                "calibrate_from_oracle_stabilization": True,
            }
        },
        target_score=0.98,
        oracle_stabilization={"status": "ok", "selected_fit_score": 0.9434302795},
    )

    assert ceiling is not None
    assert ceiling["target_self_score"] == pytest.approx(0.9434302795)
    assert ceiling["configured_target_self_score"] == pytest.approx(0.9647406955)
    assert ceiling["effective_target_score"] == pytest.approx(0.9424302795)
    assert ceiling["source"] == "same_renderer_reachability+oracle_stabilization"


def test_fit_material_stops_when_score_ceiling_is_reached(monkeypatch, patched_pipeline):
    output_dir, lmat = patched_pipeline
    monkeypatch.setattr(
        fit_material,
        "analyze_multiview_pairs",
        lambda *args, **kwargs: _fake_multiview_result(0.9641133424),
    )

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "score_ceiling": {
                "enabled": True,
                "target_self_score": 0.9647406955,
                "tolerance": 0.001,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=5,
        target_score=0.98,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "score_ceiling_reached"
    assert result["terminal_reason"] == "score_ceiling_reached"
    assert result["best_fit_score"] == pytest.approx(0.9641133424)
    assert result["effective_target_score"] == pytest.approx(0.9637406955)
    assert result["score_ceiling"]["active"] is True
    assert len(result["iterations"]) == 1
    assert result["iterations"][0]["selected_stage"] == "score_ceiling_reached"
    decision_payload = _load_iteration_decision(output_dir, result["iterations"][0])
    assert decision_payload["stop_reason"] == "score_ceiling_reached"
    assert result["iterations"][0]["effective_target_score"] == pytest.approx(0.9637406955)


def test_fit_material_cma_batch_mode_stops_when_score_ceiling_is_reached(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    scores = iter([0.10, 0.9641133424, 0.20])

    def fake_multiview(*args, **kwargs):
        return _fake_multiview_result(next(scores))

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "score_ceiling": {
                "enabled": True,
                "target_self_score": 0.9647406955,
                "tolerance": 0.001,
            },
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=8,
        target_score=0.98,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "score_ceiling_reached"
    assert result["terminal_reason"] == "score_ceiling_reached"
    assert result["best_fit_score"] == pytest.approx(0.9641133424)
    assert result["effective_target_score"] == pytest.approx(0.9637406955)
    assert result["batch_execution"]["real_evaluations"] == 2
    assert result["iterations"][0]["selected_stage"] == "score_ceiling_reached"
    decision_payload = _load_iteration_decision(output_dir, result["iterations"][0])
    assert decision_payload["stop_reason"] == "score_ceiling_reached"


def test_fit_material_renders_initial_context_browser_score_before_nonbatch_search(patched_pipeline):
    output_dir, lmat = patched_pipeline

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _BrowserScoreSequenceDriver(output_dir, [0.10, 0.9641133424])
    result = fit_material._run_auto_adjustment(
        config={
            "browser_score_context_render": {"enabled": True},
            "score_ceiling": {
                "enabled": True,
                "target_self_score": 0.9647406955,
                "tolerance": 0.001,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=5,
        target_score=0.98,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "score_ceiling_reached"
    assert result["terminal_reason"] == "score_ceiling_reached"
    assert result["best_fit_score"] == pytest.approx(0.9641133424)
    assert [call[0] for call in driver.calls] == [-1, 0]
    assert result["iterations"][0]["timing"]["initial_context_render_iteration"] == -1
    assert result["iterations"][0]["timing"]["initial_context_browser_score_used"] is True


def test_fit_material_cma_batch_mode_renders_initial_context_browser_score(patched_pipeline):
    output_dir, lmat = patched_pipeline

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _BrowserScoreSequenceDriver(output_dir, [0.10, 0.9641133424, 0.20])
    result = fit_material._run_auto_adjustment(
        config={
            "browser_score_context_render": {"enabled": True},
            "score_ceiling": {
                "enabled": True,
                "target_self_score": 0.9647406955,
                "tolerance": 0.001,
            },
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=8,
        target_score=0.98,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "score_ceiling_reached"
    assert result["terminal_reason"] == "score_ceiling_reached"
    assert result["best_fit_score"] == pytest.approx(0.9641133424)
    assert [call[0] for call in driver.calls] == [-1, 0, 1]
    assert result["batch_execution"]["context"]["fit_score"] == pytest.approx(0.10)
    assert result["batch_execution"]["context"]["timing"]["initial_context_render_iteration"] == -1
    assert result["batch_execution"]["context"]["timing"]["initial_context_browser_score_used"] is True


def test_fit_material_context_browser_score_uses_objective_config(patched_pipeline):
    output_dir, lmat = patched_pipeline

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    class WorstViewContextDriver(_StubDriver):
        def render_candidate(self, iteration: int, params: dict) -> dict:
            self.calls.append((iteration, params))
            if iteration < 0:
                return _browser_score_render_result(iteration, 0.90, worst_fit_score=0.80)
            return _browser_score_render_result(iteration, 0.20)

    driver = WorstViewContextDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "browser_score_context_render": {"enabled": True},
            "browser_score_objective": {
                "mode": "mean_worst_blend",
                "worst_view_weight": 0.5,
            },
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=5,
        target_score=0.84,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "target_reached"
    assert [call[0] for call in driver.calls] == [-1]
    assert result["best_fit_score"] == pytest.approx(0.85)
    assert result["batch_execution"]["context"]["fit_score"] == pytest.approx(0.85)
    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.85)
    detail = json.loads((output_dir / "auto_adjust" / "iter_0000" / "decision.json").read_text(encoding="utf-8"))
    summary = detail["multiview_analysis"]["summary"]
    assert summary["mean_fit_score"] == pytest.approx(0.90)
    assert summary["worst_diff_score"] == pytest.approx(0.20)
    assert summary["optimization_fit_score"] == pytest.approx(0.85)
    assert summary["optimization_fit_score_source"] == "browser_score_mean_worst_blend"


def test_fit_material_cma_cli_overrides_stagnation_config():
    base = CmaesStrategyConfig(
        mode="warm",
        warm_start_iters=12,
        population_size=None,
        sigma=None,
        seed=None,
        hint_bias_mix_ratio=0.30,
        stagnation_patience=0,
        stagnation_min_delta=0.001,
        stagnation_min_evaluations=0,
        stagnation_max_restarts=0,
        stagnation_stop_after_restarts=True,
        restart_center_mode="best",
        restart_population_multiplier=1.0,
        restart_population_schedule="ipop",
        restart_max_population_size=None,
        allow_scene_lighting=True,
    )
    args = argparse.Namespace(
        cma_warm_start_iters=None,
        cma_population_size=None,
        cma_sigma=None,
        cma_seed=None,
        cma_hint_bias_mix_ratio=None,
        cma_stagnation_patience=120,
        cma_stagnation_min_delta=0.002,
        cma_stagnation_min_evaluations=240,
        cma_stagnation_max_restarts=2,
        cma_continue_after_stagnation_restarts=True,
        cma_restart_center_mode="alternate",
        cma_restart_population_multiplier=2.0,
        cma_restart_population_schedule="bipop",
        cma_restart_max_population_size=32,
    )

    config = fit_material._override_cmaes_from_cli(args, base)

    assert config.stagnation_patience == 120
    assert config.stagnation_min_delta == pytest.approx(0.002)
    assert config.stagnation_min_evaluations == 240
    assert config.stagnation_max_restarts == 2
    assert config.stagnation_stop_after_restarts is False
    assert config.restart_center_mode == "alternate"
    assert config.restart_population_multiplier == pytest.approx(2.0)
    assert config.restart_population_schedule == "bipop"
    assert config.restart_max_population_size == 32
    assert config.allow_scene_lighting is True


def test_fit_material_cma_batch_mode_evaluates_candidates_in_batches(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    scores = iter([0.10, 0.20, 0.30, 0.40, 0.50, 0.60])

    def fake_multiview(*args, **kwargs):
        return _fake_multiview_result(next(scores))

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 3,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=5,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    decisions = [
        _load_iteration_decision(output_dir, entry)
        for entry in result["iterations"]
    ]
    batch_info = [decision["cma_es"]["batch"] for decision in decisions]

    assert result["status"] == "max_iterations_reached"
    assert len(result["iterations"]) == 5
    assert len(driver.calls) == 5
    assert [call[0] for call in driver.calls] == [0, 1, 2, 3, 4]
    assert [item["size"] for item in batch_info] == [3, 3, 3, 2, 2]
    assert [item["index"] for item in batch_info] == [0, 1, 2, 0, 1]
    assert [decision["cma_es"]["evaluations"] for decision in decisions] == [0, 0, 0, 3, 3]
    assert result["best_fit_score"] == pytest.approx(0.60)


def test_fit_material_cma_batch_mode_preserves_context_best_for_current_candidate(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _CurrentFirstBatchStrategy()

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        if "batch_context" in analysis_dir_text:
            return _fake_multiview_result(0.70)
        if "iter_0001" in analysis_dir_text:
            return _fake_multiview_result(0.20)
        raise AssertionError(f"unexpected analysis dir {analysis_dir_text!r}")

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "evaluation_workers": 4,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
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
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "max_iterations_reached"
    assert result["best_fit_score"] == pytest.approx(0.70)
    assert result["best_fit_params"] == _initial_params()
    assert [call[0] for call in driver.calls] == [1]
    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.70)
    first_payload = json.loads(
        (output_dir / "auto_adjust" / "iter_0000" / "decision.json").read_text(
            encoding="utf-8",
        )
    )
    assert first_payload["render_result"]["status"] == "cached_evaluation"
    assert strategy.tell_many_scores_calls == [
        [(pytest.approx(0.70), pytest.approx(0.30)), (pytest.approx(0.20), pytest.approx(0.80))]
    ]


def test_fit_material_cma_batch_mode_reuses_context_candidate_when_general_cache_disabled(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _CurrentFirstBatchStrategy()

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        if "batch_context" in analysis_dir_text:
            return _fake_multiview_result(0.70)
        if "iter_0001" in analysis_dir_text:
            return _fake_multiview_result(0.20)
        raise AssertionError(f"unexpected analysis dir {analysis_dir_text!r}")

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "evaluation_workers": 4,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
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
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
        focus_callback=lambda _label: {"focused": True},
    )

    assert result["best_fit_score"] == pytest.approx(0.70)
    assert [call[0] for call in driver.calls] == [1]
    assert result["batch_execution"]["disabled_reasons"] == {"focus_callback_controls_shared_window": 2}
    assert result["batch_execution"]["cached_evaluations"] == 1
    assert strategy.tell_many_scores_calls == [
        [(pytest.approx(0.70), pytest.approx(0.30)), (pytest.approx(0.20), pytest.approx(0.80))]
    ]


def test_fit_material_cma_batch_mode_accepts_underfilled_strategy_batches(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _ShortBatchStrategy()
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 3,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
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
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "max_iterations_reached"
    assert [entry["iteration"] for entry in result["iterations"]] == [0, 1]
    assert [call[0] for call in driver.calls] == [0, 1]
    assert strategy.requested_counts == [2, 1]
    assert strategy.tell_many_scores_calls == [[(0.10, 0.90)], [(0.10, 0.90)]]
    assert result["batch_execution"]["evaluation_batch_size"] == 3
    assert result["batch_execution"]["evaluations"] == 2
    assert result["batch_execution"]["batches"] == 2


def test_fit_material_evidence_summary_records_cma_initial_design(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        if "batch_context" in analysis_dir_text:
            return _fake_multiview_result(0.10)
        if "iter_0000" in analysis_dir_text:
            return _fake_multiview_result(0.20)
        if "iter_0001" in analysis_dir_text:
            return _fake_multiview_result(0.70)
        if "iter_0002" in analysis_dir_text:
            return _fake_multiview_result(0.40)
        raise AssertionError(f"unexpected analysis dir {analysis_dir_text!r}")

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=3,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_warm",
        cma_es_config=CmaesStrategyConfig(
            mode="warm",
            seed=11,
            population_size=4,
            warm_start_iters=4,
            initial_design_samples=2,
            initial_design_method="latin_hypercube",
            initial_design_include_current=True,
        ),
    )

    summary = result["optimizer_evidence_summary"]
    assert summary["initial_design"] == {
        "enabled": True,
        "method": "latin_hypercube",
        "requested_samples": 2,
        "include_current": True,
        "evaluated_samples": 2,
        "completed": True,
        "best_fit_score": pytest.approx(0.70),
        "best_iteration": 1,
    }
    assert result["iterations"][0]["cma_initial_design"]["enabled"] is True
    assert result["iterations"][1]["cma_initial_design"]["completed"] is False
    assert result["iterations"][2]["cma_initial_design"]["completed"] is True
    assert result["iterations"][0]["candidate_params"] == _initial_params()
    assert result["optimizer_candidate_archive"]["best"]["candidate_params"] == result["iterations"][1]["candidate_params"]


def test_fit_material_cma_batch_mode_full_reranks_top_fast_candidates(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()
    calls: list[tuple[str, str]] = []

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        profile = str(kwargs.get("research_metrics_profile"))
        calls.append((analysis_dir_text, profile))
        if "batch_context" in analysis_dir_text:
            return _fake_multiview_result(0.10)
        if "full_rerank" in analysis_dir_text:
            assert "iter_0001" in analysis_dir_text
            assert profile == "full"
            return _fake_multiview_result(0.30)
        if "iter_0000" in analysis_dir_text:
            assert profile == "fast"
            return _fake_multiview_result(0.20)
        if "iter_0001" in analysis_dir_text:
            assert profile == "fast"
            return _fake_multiview_result(0.60)
        if "iter_0002" in analysis_dir_text:
            assert profile == "fast"
            return _fake_multiview_result(0.40)
        raise AssertionError(f"unexpected analysis dir {analysis_dir_text!r}")

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 3,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "full_rerank_top_k": 1,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=3,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    full_calls = [item for item in calls if item[1] == "full"]
    assert result["status"] == "max_iterations_reached"
    assert full_calls == [(str(output_dir / "auto_adjust" / "iter_0001" / "full_rerank"), "full")]
    assert result["analysis_performance"]["full_rerank_top_k"] == 1
    assert result["iterations"][1]["timing"]["full_rerank_selected"] is True
    assert result["iterations"][1]["timing"]["full_rerank_source_fit_score"] == pytest.approx(0.60)
    assert result["iterations"][1]["fit_score_before"] == pytest.approx(0.30)
    assert strategy.tell_many_scores_calls == [[(0.20, 0.80), (0.30, 0.70), (0.40, 0.60)]]


def test_fit_material_cma_batch_mode_requires_full_validation_before_target_stop(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()
    calls: list[tuple[str, str]] = []

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        profile = str(kwargs.get("research_metrics_profile"))
        calls.append((analysis_dir_text, profile))
        if "batch_context" in analysis_dir_text:
            return _fake_multiview_result(0.10)
        if "target_full_validation" in analysis_dir_text:
            assert "iter_0000" in analysis_dir_text
            assert profile == "full"
            return _fake_multiview_result(0.50)
        if "iter_0000" in analysis_dir_text:
            assert profile == "fast"
            return _fake_multiview_result(0.95)
        if "iter_0001" in analysis_dir_text:
            assert profile == "fast"
            return _fake_multiview_result(0.20)
        raise AssertionError(f"unexpected analysis dir {analysis_dir_text!r}")

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "target_full_validation": True,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=2,
        target_score=0.90,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    full_calls = [item for item in calls if item[1] == "full"]
    assert result["status"] == "max_iterations_reached"
    assert full_calls == [(str(output_dir / "auto_adjust" / "iter_0000" / "target_full_validation"), "full")]
    assert result["analysis_performance"]["target_full_validation"] is True
    assert result["iterations"][0]["timing"]["target_full_validation_selected"] is True
    assert result["iterations"][0]["timing"]["target_full_validation_source_fit_score"] == pytest.approx(0.95)
    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.50)
    assert strategy.tell_many_scores_calls == [[(0.50, 0.50), (0.20, 0.80)]]


def test_fit_material_cma_batch_mode_stability_validation_rerenders_target_candidate(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()
    full_validation_calls: list[str] = []

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        if "target_full_validation" in analysis_dir_text:
            full_validation_calls.append(analysis_dir_text)
            return _fake_multiview_result(0.95)
        return _fake_multiview_result(0.10)

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _BrowserScoreSequenceDriver(output_dir, [0.95, 0.20, 0.82])
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "target_full_validation": True,
                "stability_validation_repeats": 2,
                "stability_validation_restart_renderer": True,
                "stability_score_drift_threshold": 0.005,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=2,
        target_score=0.90,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert full_validation_calls == [str(output_dir / "auto_adjust" / "iter_0000" / "target_full_validation")]
    assert [call[0] for call in driver.calls] == [0, 1, 1_000_000]
    assert driver.reset_calls == 1
    assert result["status"] == "max_iterations_reached"
    assert result["best_fit_score"] == pytest.approx(0.82)
    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.82)
    assert result["iterations"][0]["timing"]["stability_validation_selected"] is True
    assert result["iterations"][0]["timing"]["stability_validation_restart_renderer"] is True
    assert result["iterations"][0]["timing"]["stability_validation_stable"] is False
    assert result["iterations"][0]["stability_validation"]["fit_score_spread"] == pytest.approx(0.13)
    assert result["iterations"][0]["stability_validation"]["conservative_fit_score"] == pytest.approx(0.82)
    assert strategy.tell_many_scores_calls == [[(0.82, 0.18), (0.20, 0.80)]]


def test_fit_material_cma_batch_mode_stability_validation_can_run_without_full_validation(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        if "full_validation" in analysis_dir_text:
            raise AssertionError("browser_score stability validation should not require full image analysis")
        return _fake_multiview_result(0.10)

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _BrowserScoreSequenceDriver(output_dir, [0.95, 0.20, 0.82])
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "stability_validation_repeats": 2,
                "stability_validation_restart_renderer": True,
                "stability_score_drift_threshold": 0.005,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
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
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert [call[0] for call in driver.calls] == [0, 1, 1_000_000]
    assert driver.reset_calls == 1
    assert result["best_fit_score"] == pytest.approx(0.82)
    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.82)
    assert result["iterations"][0]["timing"]["stability_validation_selected"] is True
    assert result["iterations"][0]["stability_validation"]["conservative_fit_score"] == pytest.approx(0.82)
    assert strategy.tell_many_scores_calls == [[(0.82, 0.18), (0.20, 0.80)]]


def test_fit_material_cma_batch_mode_can_use_fresh_oracle_stability_validation(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        if "fresh_oracle" in analysis_dir_text or "full_validation" in analysis_dir_text:
            raise AssertionError("fresh oracle validation should use browser_score renders directly")
        return _fake_multiview_result(0.10)

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _FreshOracleValidationDriver(output_dir, [0.95, 0.20], validation_score=0.81)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "stability_validation_repeats": 3,
                "stability_validation_mode": "fresh_oracle",
                "stability_score_drift_threshold": 0.005,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
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
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert [call[0] for call in driver.calls] == [0, 1]
    assert driver.reset_calls == 0
    assert len(driver.fresh_validation_calls) == 1
    assert driver.fresh_validation_calls[0]["attempts"] == 3
    assert "best_stability_validation_fresh_oracle" in driver.fresh_validation_calls[0]["output_subdir"]
    assert result["best_fit_score"] == pytest.approx(0.81)
    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.81)
    assert result["iterations"][0]["timing"]["stability_validation_mode"] == "fresh_oracle"
    assert result["iterations"][0]["stability_validation"]["score_policy"] == "fresh_oracle_min"
    assert result["iterations"][0]["stability_validation"]["stable"] is False
    assert strategy.tell_many_scores_calls[0][0] == pytest.approx((0.81, 0.19))
    assert strategy.tell_many_scores_calls[0][1] == pytest.approx((0.20, 0.80))


def test_fit_material_fresh_oracle_stability_can_score_by_median(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", lambda *args, **kwargs: _fake_multiview_result(0.10))
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _FreshOracleValidationDriver(output_dir, [0.95, 0.20], validation_score=0.81)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "stability_validation_repeats": 3,
                "stability_validation_mode": "fresh_oracle",
                "stability_validation_score_policy": "median",
                "stability_score_drift_threshold": 0.005,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
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
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["analysis_performance"]["stability_validation_score_policy"] == "median"
    assert result["best_fit_score"] == pytest.approx(0.88)
    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.88)
    assert result["iterations"][0]["stability_validation"]["score_policy"] == "fresh_oracle_median"
    assert strategy.tell_many_scores_calls[0][0] == pytest.approx((0.88, 0.12))
    assert strategy.tell_many_scores_calls[0][1] == pytest.approx((0.20, 0.80))


def test_fit_material_fresh_oracle_stability_can_score_by_lower_quartile(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", lambda *args, **kwargs: _fake_multiview_result(0.10))
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _FreshOracleValidationDriver(
        output_dir,
        [0.95, 0.20],
        validation_score=0.81,
        validation_records=[0.81, 0.92, 0.93],
    )
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "stability_validation_repeats": 3,
                "stability_validation_mode": "fresh_oracle",
                "stability_validation_score_policy": "p25",
                "stability_score_drift_threshold": 0.005,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
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
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["analysis_performance"]["stability_validation_score_policy"] == "lower_quartile"
    assert result["best_fit_score"] == pytest.approx(0.81)
    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.81)
    assert result["iterations"][0]["stability_validation"]["score_policy"] == "fresh_oracle_lower_quartile"
    assert strategy.tell_many_scores_calls[0][0] == pytest.approx((0.81, 0.19))
    assert strategy.tell_many_scores_calls[0][1] == pytest.approx((0.20, 0.80))


def test_fit_material_fresh_oracle_foreground_instability_forces_conservative_score(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", lambda *args, **kwargs: _fake_multiview_result(0.10))
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _FreshOracleValidationDriver(
        output_dir,
        [0.95, 0.20],
        validation_score=0.88,
        validation_records=[0.88, 0.89, 0.90, 0.91, 0.92, 0.93],
        validation_foreground_sums=[61000, 62000, 61020, 61980, 61010, 62010],
    )
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "stability_validation_repeats": 6,
                "stability_validation_mode": "fresh_oracle",
                "stability_validation_score_policy": "lower_quartile",
                "stability_score_drift_threshold": 0.10,
                "stability_foreground_abs_threshold": 128.0,
                "stability_foreground_ratio_threshold": 0.005,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
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
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    validation = result["iterations"][0]["stability_validation"]
    assert validation["score_stable"] is True
    assert validation["foreground_stable"] is False
    assert validation["stable"] is False
    assert validation["worst_foreground_weight_sum_spread"] == pytest.approx(1010.0)
    assert result["best_fit_score"] == pytest.approx(0.88)
    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.88)
    assert strategy.tell_many_scores_calls[0][0] == pytest.approx((0.88, 0.12))


def test_fit_material_fresh_oracle_can_score_by_canonical_oracle_mode(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", lambda *args, **kwargs: _fake_multiview_result(0.10))
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _OracleFreshValidationDriver(
        output_dir,
        [0.95, 0.20],
        validation_score=0.80,
        validation_records=[0.91, 0.92, 0.80, 0.81, 0.82, 0.83],
        validation_foreground_sums=[61000, 61012, 62500, 62508, 62516, 62524],
        selected_foreground_sum=61000,
    )
    result = fit_material._run_auto_adjustment(
        config={
            "oracle_stabilization": {
                "enabled": True,
                "attempts": 2,
            },
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "stability_validation_repeats": 6,
                "stability_validation_mode": "fresh_oracle",
                "stability_validation_score_policy": "canonical_mode_p25",
                "stability_validation_top_k": 0,
                "stability_score_drift_threshold": 0.20,
                "stability_foreground_abs_threshold": 128.0,
                "stability_foreground_ratio_threshold": 0.005,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
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
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    validation = result["iterations"][0]["stability_validation"]
    assert result["analysis_performance"]["stability_validation_score_policy"] == "canonical_mode_lower_quartile"
    assert validation["score_policy"] == "fresh_oracle_canonical_mode_lower_quartile"
    assert validation["dominant_foreground_mode"]["sample_count"] == 4
    assert validation["canonical_foreground_mode"]["sample_count"] == 2
    assert result["best_fit_score"] == pytest.approx(0.91)
    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.91)
    assert strategy.tell_many_scores_calls[0][0] == pytest.approx((0.91, 0.09))


def test_fit_material_batch_stability_top_k_can_promote_raw_under_best_candidate(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _TwoRoundUniqueBatchStrategy()

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", lambda *args, **kwargs: _fake_multiview_result(0.10))
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _FreshOraclePerParamValidationDriver(
        output_dir,
        [0.93, 0.10, 0.95, 0.89],
        validation_scores_by_gamma={
            2.0: 0.90,
            2.1: 0.10,
            3.0: 0.87,
            3.1: 0.91,
        },
    )
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "stability_validation_repeats": 3,
                "stability_validation_mode": "fresh_oracle",
                "stability_validation_score_policy": "median",
                "stability_validation_top_k": 2,
                "stability_score_drift_threshold": 0.005,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=4,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    validated_gammas = [
        round(float(call["params"]["u_Gamma_Power"]), 4) for call in driver.fresh_validation_calls
    ]
    assert result["analysis_performance"]["stability_validation_top_k"] == 2
    assert validated_gammas == pytest.approx([2.0, 2.1, 3.0, 3.1])
    assert result["best_fit_score"] == pytest.approx(0.91)
    assert result["iterations"][3]["fit_score_before"] == pytest.approx(0.91)
    assert result["iterations"][3]["stability_validation"]["score_policy"] == "fresh_oracle_median"
    assert len(strategy.tell_many_scores_calls) == 2
    batch0_scores = [value for pair in strategy.tell_many_scores_calls[0] for value in pair]
    batch1_scores = [value for pair in strategy.tell_many_scores_calls[1] for value in pair]
    assert batch0_scores == pytest.approx([0.90, 0.10, 0.10, 0.90])
    assert batch1_scores == pytest.approx([0.87, 0.13, 0.91, 0.09])


def test_fit_material_batch_stability_top_k_uses_batch_fresh_oracle_validation(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _TwoRoundUniqueBatchStrategy()

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", lambda *args, **kwargs: _fake_multiview_result(0.10))
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _FreshOracleBatchValidationDriver(
        output_dir,
        [0.93, 0.10, 0.95, 0.89],
        validation_scores_by_gamma={
            2.0: 0.90,
            2.1: 0.10,
            3.0: 0.87,
            3.1: 0.91,
        },
    )
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "stability_validation_repeats": 3,
                "stability_validation_mode": "fresh_oracle",
                "stability_validation_score_policy": "median",
                "stability_validation_top_k": 2,
                "stability_score_drift_threshold": 0.005,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=4,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert len(driver.batch_validation_calls) == 2
    assert [len(call["candidates"]) for call in driver.batch_validation_calls] == [2, 2]
    assert result["best_fit_score"] == pytest.approx(0.91)
    assert result["iterations"][3]["stability_validation"]["score_policy"] == "fresh_oracle_median"
    assert len(strategy.tell_many_scores_calls) == 2
    batch1_scores = [value for pair in strategy.tell_many_scores_calls[1] for value in pair]
    assert batch1_scores == pytest.approx([0.87, 0.13, 0.91, 0.09])


def test_fit_material_batch_stability_top_k_honors_batch_chunk_size(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", lambda *args, **kwargs: _fake_multiview_result(0.10))
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _FreshOracleBatchValidationDriver(
        output_dir,
        [0.93, 0.92, 0.91, 0.90],
        validation_scores_by_gamma={
            2.0: 0.90,
            2.1: 0.89,
            2.2: 0.88,
            2.3: 0.87,
        },
    )
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 4,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "stability_validation_repeats": 2,
                "stability_validation_mode": "fresh_oracle",
                "stability_validation_score_policy": "median",
                "stability_validation_top_k": 4,
                "stability_validation_batch_chunk_size": 2,
                "stability_score_drift_threshold": 0.005,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=4,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["analysis_performance"]["stability_validation_batch_chunk_size"] == 2
    assert [len(call["candidates"]) for call in driver.batch_validation_calls] == [2, 2]
    chunk_gammas = [
        [round(float(candidate["params"]["u_Gamma_Power"]), 4) for candidate in call["candidates"]]
        for call in driver.batch_validation_calls
    ]
    assert chunk_gammas == [[2.0, 2.1], [2.2, 2.3]]
    assert result["best_fit_score"] == pytest.approx(0.90)
    assert len(strategy.tell_many_scores_calls) == 1


def test_fit_material_cma_batch_mode_stability_render_failure_becomes_conservative_low_score(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        if "full_validation" in analysis_dir_text or "stability_validation" in analysis_dir_text:
            raise AssertionError("failed stability render must not fall back to static image_pairs")
        return _fake_multiview_result(0.10)

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _BrowserScoreSequenceDriver(output_dir, [0.95, 0.20, None, 0.20])
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "stability_validation_repeats": 2,
                "stability_validation_restart_renderer": True,
                "stability_score_drift_threshold": 0.005,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
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
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert [call[0] for call in driver.calls] == [0, 1, 1_000_000, 1_000_001]
    assert driver.reset_calls == 3
    assert result["best_fit_score"] == pytest.approx(0.20)
    assert result["iterations"][0]["fit_score_before"] == pytest.approx(0.0)
    assert result["iterations"][0]["timing"]["stability_validation_stable"] is False
    assert result["iterations"][0]["stability_validation"]["conservative_fit_score"] == pytest.approx(0.0)
    assert strategy.tell_many_scores_calls == [[(0.0, 1.0), (0.20, 0.80)]]


def test_fit_material_cma_batch_mode_full_validates_best_improvements(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()
    calls: list[tuple[str, str]] = []

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        profile = str(kwargs.get("research_metrics_profile"))
        calls.append((analysis_dir_text, profile))
        if "batch_context" in analysis_dir_text:
            return _fake_multiview_result(0.10)
        if "best_full_validation" in analysis_dir_text:
            assert profile == "full"
            if "iter_0001" in analysis_dir_text:
                return _fake_multiview_result(0.25)
            if "iter_0002" in analysis_dir_text:
                return _fake_multiview_result(0.35)
            raise AssertionError(f"unexpected best validation dir {analysis_dir_text!r}")
        if "iter_0000" in analysis_dir_text:
            assert profile == "fast"
            return _fake_multiview_result(0.20)
        if "iter_0001" in analysis_dir_text:
            assert profile == "fast"
            return _fake_multiview_result(0.60)
        if "iter_0002" in analysis_dir_text:
            assert profile == "fast"
            return _fake_multiview_result(0.40)
        raise AssertionError(f"unexpected analysis dir {analysis_dir_text!r}")

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "optimizer_preset": "cma_mature_default",
            "analysis_performance": {
                "evaluation_batch_size": 3,
                "snapshot_interval": 0,
                "research_metrics_profile": "fast",
                "best_full_validation": True,
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=3,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    full_calls = [item for item in calls if item[1] == "full"]
    assert result["status"] == "max_iterations_reached"
    assert result["optimizer_preset"] == "cma_mature_default"
    summary = result["optimizer_evidence_summary"]
    assert summary["optimizer_preset"] == "cma_mature_default"
    assert summary["optimizer"] == "cma_cold"
    assert summary["multi_fidelity"] == {
        "research_metrics_profile": "fast",
        "full_rerank_top_k": 0,
        "best_full_validation": True,
        "target_full_validation": False,
    }
    assert summary["batch_execution"]["enabled"] is True
    assert summary["batch_execution"]["evaluation_batch_size"] == 3
    assert summary["cma_es"]["population_size"] == 4
    assert full_calls == [
        (str(output_dir / "auto_adjust" / "iter_0001" / "best_full_validation"), "full"),
        (str(output_dir / "auto_adjust" / "iter_0002" / "best_full_validation"), "full"),
    ]
    assert result["analysis_performance"]["best_full_validation"] is True
    assert result["best_fit_score"] == pytest.approx(0.35)
    assert result["iterations"][0]["timing"]["best_full_validation_selected"] is False
    assert result["iterations"][1]["timing"]["best_full_validation_selected"] is True
    assert result["iterations"][1]["timing"]["best_full_validation_source_fit_score"] == pytest.approx(0.60)
    assert result["iterations"][1]["fit_score_before"] == pytest.approx(0.25)
    assert result["iterations"][2]["timing"]["best_full_validation_selected"] is True
    assert result["iterations"][2]["timing"]["best_full_validation_source_fit_score"] == pytest.approx(0.40)
    assert result["iterations"][2]["fit_score_before"] == pytest.approx(0.35)
    assert strategy.tell_many_scores_calls == [[(0.20, 0.80), (0.25, 0.75), (0.35, 0.65)]]


def test_fit_material_cma_batch_mode_stops_on_cma_stagnation(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    monkeypatch.setattr(
        fit_material,
        "analyze_multiview_pairs",
        lambda *args, **kwargs: _fake_multiview_result(0.10),
    )

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 4,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=8,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(
            mode="cold",
            seed=11,
            population_size=4,
            stagnation_patience=3,
            stagnation_min_delta=0.02,
            stagnation_min_evaluations=4,
        ),
    )

    assert result["status"] == "cmaes_stagnation"
    assert result["terminal_reason"] == "cmaes_stagnation"
    assert len(result["iterations"]) == 4
    assert [call[0] for call in driver.calls] == [0, 1, 2, 3]


def test_fit_material_cma_batch_mode_restarts_before_stagnation_stop(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    monkeypatch.setattr(
        fit_material,
        "analyze_multiview_pairs",
        lambda *args, **kwargs: _fake_multiview_result(0.10),
    )

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 4,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=8,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(
            mode="cold",
            seed=11,
            population_size=4,
            stagnation_patience=3,
            stagnation_min_delta=0.02,
            stagnation_min_evaluations=4,
            stagnation_max_restarts=1,
        ),
    )

    assert result["status"] == "cmaes_stagnation"
    assert result["terminal_reason"] == "cmaes_stagnation"
    assert len(result["iterations"]) == 8
    assert [call[0] for call in driver.calls] == list(range(8))
    decision_after_restart = _load_iteration_decision(output_dir, result["iterations"][4])
    assert decision_after_restart["cma_es"]["restarts"]["count"] == 1


def test_fit_material_cma_batch_mode_parallelizes_safe_candidate_evaluation(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    monkeypatch.setattr(
        fit_material,
        "analyze_multiview_pairs",
        lambda *args, **kwargs: _fake_multiview_result(0.10),
    )

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _SlowTrackingDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 3,
                "evaluation_workers": 3,
                "evaluation_parallel_safe": True,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=3,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "max_iterations_reached"
    assert driver.max_active > 1
    batch_execution = dict(result["batch_execution"])
    context = batch_execution.pop("context")
    assert context["fit_score"] == pytest.approx(0.10)
    assert context["score_params_role"] == "batch_context"
    assert batch_execution == {
        "enabled": True,
        "evaluation_batch_size": 3,
        "evaluation_workers_requested": 3,
        "evaluation_workers_effective": 3,
        "evaluation_parallel_safe": True,
        "renderer_parallel_safe": False,
        "renderer_worker_count": 1,
        "evaluations": 3,
        "real_evaluations": 3,
        "cached_evaluations": 0,
        "cache_hit_rate": 0.0,
        "cache_sources": {},
        "batches": 1,
        "mode_counts": {"cma_batch_parallel": 3},
        "disabled_reasons": {},
    }
    assert [entry["timing"]["evaluation_mode"] for entry in result["iterations"]] == [
        "cma_batch_parallel",
        "cma_batch_parallel",
        "cma_batch_parallel",
    ]


def test_fit_material_cma_batch_mode_does_not_parallelize_unmarked_renderer(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    monkeypatch.setattr(
        fit_material,
        "analyze_multiview_pairs",
        lambda *args, **kwargs: _fake_multiview_result(0.10),
    )

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _SlowTrackingDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 3,
                "evaluation_workers": 3,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=3,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "max_iterations_reached"
    assert driver.max_active == 1
    batch_execution = dict(result["batch_execution"])
    context = batch_execution.pop("context")
    assert context["fit_score"] == pytest.approx(0.10)
    assert context["score_params_role"] == "batch_context"
    assert batch_execution == {
        "enabled": True,
        "evaluation_batch_size": 3,
        "evaluation_workers_requested": 3,
        "evaluation_workers_effective": 1,
        "evaluation_parallel_safe": False,
        "renderer_parallel_safe": False,
        "renderer_worker_count": 1,
        "evaluations": 3,
        "real_evaluations": 3,
        "cached_evaluations": 0,
        "cache_hit_rate": 0.0,
        "cache_sources": {},
        "batches": 1,
        "mode_counts": {"cma_batch_sequential": 3},
        "disabled_reasons": {"renderer_not_marked_parallel_safe": 3},
    }
    assert [entry["timing"]["evaluation_mode"] for entry in result["iterations"]] == [
        "cma_batch_sequential",
        "cma_batch_sequential",
        "cma_batch_sequential",
    ]
    assert [entry["timing"]["evaluation_parallel_disabled_reason"] for entry in result["iterations"]] == [
        "renderer_not_marked_parallel_safe",
        "renderer_not_marked_parallel_safe",
        "renderer_not_marked_parallel_safe",
    ]


def test_fit_material_cma_batch_mode_pipelines_analysis_after_serial_render(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _UniqueBatchStrategy()
    events: list[tuple[float, str, int]] = []
    event_lock = threading.Lock()

    def record_event(label: str, iteration: int) -> None:
        with event_lock:
            events.append((time.perf_counter(), label, iteration))

    class ScreenshotSlowDriver(_SlowTrackingDriver):
        def render_candidate(self, iteration: int, params: dict) -> dict:
            record_event("render_start", iteration)
            try:
                result = super().render_candidate(iteration, params)
                screenshot = output_dir / f"candidate_{iteration:04d}.png"
                screenshot.write_bytes(b"png")
                return {**result, "screenshots": [str(screenshot)]}
            finally:
                record_event("render_end", iteration)

    def fake_multiview(*args, **kwargs):
        analysis_dir = Path(args[1])
        if "batch_context" in analysis_dir.parts:
            return _fake_multiview_result(0.10)
        iteration_dir = next(part for part in analysis_dir.parts if part.startswith("iter_"))
        iteration = int(iteration_dir.split("_", 1)[1])
        record_event("analysis_start", iteration)
        time.sleep(0.05)
        record_event("analysis_end", iteration)
        return _fake_multiview_result(0.20 + iteration * 0.01)

    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)
    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = ScreenshotSlowDriver(output_dir, delay_s=0.05)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 3,
                "evaluation_workers": 3,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=3,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
        focus_callback=lambda _label: {"focused": True},
    )

    assert result["status"] == "max_iterations_reached"
    assert driver.max_active == 1
    assert result["batch_execution"]["mode_counts"] == {
        "cma_batch_render_analysis_pipeline": 2,
        "cma_batch_sequential": 1,
    }
    assert result["batch_execution"]["cached_evaluations"] == 1
    by_label_iteration = {(label, iteration): ts for ts, label, iteration in events}
    assert by_label_iteration[("analysis_start", 0)] < by_label_iteration[("render_end", 1)]
    assert by_label_iteration[("render_start", 1)] < by_label_iteration[("analysis_end", 0)]


def test_fit_material_cma_batch_mode_uses_driver_parallel_safe_capability(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    monkeypatch.setattr(
        fit_material,
        "analyze_multiview_pairs",
        lambda *args, **kwargs: _fake_multiview_result(0.10),
    )

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _SlowTrackingDriver(output_dir)
    driver.parallel_safe = True
    driver.worker_count = 2
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 3,
                "evaluation_workers": 3,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=3,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "max_iterations_reached"
    assert driver.max_active > 1
    assert driver.max_active == 2
    assert result["batch_execution"]["evaluation_workers_effective"] == 2
    assert result["batch_execution"]["renderer_parallel_safe"] is True
    assert result["batch_execution"]["renderer_worker_count"] == 2
    assert result["batch_execution"]["evaluation_parallel_safe"] is False


def test_fit_material_cma_batch_worker_pool_never_reenters_the_same_worker(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    monkeypatch.setattr(
        fit_material,
        "analyze_multiview_pairs",
        lambda *args, **kwargs: _fake_multiview_result(0.10),
    )

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _WorkerPoolTrackingDriver(output_dir, worker_count=2)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 3,
                "evaluation_workers": 3,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=3,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "max_iterations_reached"
    assert driver.max_active == 2
    assert max(driver.max_active_by_worker.values()) == 1
    assert result["batch_execution"]["evaluation_workers_effective"] == 2
    assert result["batch_execution"]["renderer_worker_count"] == 2
    assert [entry["timing"]["evaluation_mode"] for entry in result["iterations"]] == [
        "cma_batch_parallel",
        "cma_batch_parallel",
        "cma_batch_parallel",
    ]


def test_fit_material_cma_batch_reuses_duplicate_candidate_evaluations(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    seen_analysis_dirs: list[Path] = []

    def fake_multiview(*args, **kwargs):
        analysis_dir = Path(args[1])
        seen_analysis_dirs.append(analysis_dir)
        analysis_dir_text = str(analysis_dir)
        if "batch_context" in analysis_dir_text:
            score = 0.10
        elif "iter_0000" in analysis_dir_text:
            score = 0.20
        elif "iter_0001" in analysis_dir_text:
            score = 0.30
        elif "iter_0002" in analysis_dir_text:
            score = 0.40
        else:
            raise AssertionError(f"Unexpected analysis path: {analysis_dir}")
        return _fake_multiview_result(score)

    strategy = _DuplicateBatchStrategy()
    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 3,
                "evaluation_workers": 3,
                "evaluation_parallel_safe": True,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=driver,  # type: ignore[arg-type]
        iterations=3,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "max_iterations_reached"
    assert sorted(call[0] for call in driver.calls) == [0, 2]
    assert len(seen_analysis_dirs) == 3  # batch context + two unique candidates
    assert result["iterations"][1]["timing"]["candidate_evaluation_cache_hit"] is True
    assert result["iterations"][1]["timing"]["candidate_evaluation_cache_source_iteration"] == 0
    assert result["iterations"][1]["fit_score_before"] == pytest.approx(0.20)
    assert result["iterations"][2]["fit_score_before"] == pytest.approx(0.40)
    assert result["batch_execution"]["real_evaluations"] == 2
    assert result["batch_execution"]["cached_evaluations"] == 1
    assert result["batch_execution"]["cache_hit_rate"] == pytest.approx(1 / 3)
    assert result["batch_execution"]["cache_sources"] == {"0": 1}
    assert strategy.tell_many_scores_calls == [[(0.20, 0.80), (0.20, 0.80), (0.40, 0.60)]]


def test_fit_material_cma_batch_checkpoints_state_before_batch_tell_failure(
    monkeypatch,
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline
    strategy = _FailingTellBatchStrategy()

    def fake_multiview(*args, **kwargs):
        analysis_dir_text = str(Path(args[1]))
        if "iter_0000" in analysis_dir_text:
            return _fake_multiview_result(0.20)
        if "iter_0001" in analysis_dir_text:
            return _fake_multiview_result(0.30)
        return _fake_multiview_result(0.10)

    monkeypatch.setattr(fit_material, "analyze_multiview_pairs", fake_multiview)
    monkeypatch.setattr(fit_material, "build_strategy", lambda **kwargs: strategy)

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    driver = _StubDriver(output_dir)
    with pytest.raises(RuntimeError, match="simulated optimizer failure"):
        fit_material._run_auto_adjustment(
            config={
                "analysis_performance": {
                    "evaluation_batch_size": 2,
                    "snapshot_interval": 1,
                    "research_metrics_profile": "fast",
                },
            },
            project_root=output_dir,
            output_dir=output_dir,
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
            optimizer="cma_cold",
            cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
        )

    state_path = output_dir / "auto_adjust" / "state.json"
    assert state_path.exists()
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["iteration"] == 2
    assert len(state_payload["history"]) == 2
    assert state_payload["best_fit_score"] == pytest.approx(0.30)


def test_fit_material_cma_batch_resume_continues_from_checkpoint(
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    first_driver = _StubDriver(output_dir)
    first_result = fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=first_driver,  # type: ignore[arg-type]
        iterations=2,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )
    assert [entry["iteration"] for entry in first_result["iterations"]] == [0, 1]
    assert (output_dir / "auto_adjust" / "optimizer_checkpoint.pkl").exists()

    second_driver = _StubDriver(output_dir)
    resumed_result = fit_material._run_auto_adjustment(
        config={
            "auto_adjust_resume": True,
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=second_driver,  # type: ignore[arg-type]
        iterations=4,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert [entry["iteration"] for entry in resumed_result["iterations"]] == [0, 1, 2, 3]
    assert [call[0] for call in second_driver.calls] == [2, 3]
    resumed_decision = _load_iteration_decision(output_dir, resumed_result["iterations"][2])
    assert resumed_decision["cma_es"]["evaluations"] == 2
    state_payload = json.loads((output_dir / "auto_adjust" / "state.json").read_text(encoding="utf-8"))
    assert state_payload["iteration"] == 4
    assert len(state_payload["history"]) == 4
    series_payload = json.loads((output_dir / "auto_adjust" / "iteration_series.json").read_text(encoding="utf-8"))
    assert [entry["iteration"] for entry in series_payload] == [0, 1, 2, 3]


def test_fit_material_cma_batch_resume_rejects_incompatible_checkpoint(
    patched_pipeline,
):
    output_dir, lmat = patched_pipeline

    from tools.material_fit.optimizer.adjustment_algorithm import (
        build_adjustment_policies,
    )

    first_driver = _StubDriver(output_dir)
    fit_material._run_auto_adjustment(
        config={
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=_shader_params(),
        initial_params=_initial_params(),
        policies=build_adjustment_policies(_shader_params()),
        unity_material_params={},
        driver=first_driver,  # type: ignore[arg-type]
        iterations=2,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    incompatible_shader_params = [
        (
            ShaderParam("u_Gamma_Power", "Range", default=1.0, range_min=0.05, range_max=20.0)
            if param.name == "u_Gamma_Power"
            else param
        )
        for param in _shader_params()
    ]
    second_driver = _StubDriver(output_dir)
    result = fit_material._run_auto_adjustment(
        config={
            "auto_adjust_resume": True,
            "analysis_performance": {
                "evaluation_batch_size": 2,
                "snapshot_interval": 1,
                "research_metrics_profile": "fast",
            },
        },
        project_root=output_dir,
        output_dir=output_dir,
        laya_material_path=lmat,
        laya_shader_params=incompatible_shader_params,
        initial_params=_initial_params(),
        policies=build_adjustment_policies(incompatible_shader_params),
        unity_material_params={},
        driver=second_driver,  # type: ignore[arg-type]
        iterations=4,
        target_score=0.99,
        use_capture=False,
        write_candidate_lmat=False,
        apply_lmat=False,
        capture_screen_after_apply=False,
        rerender_wait_ms=0,
        screen_capture_region="",
        fit_score_mode="perceptual",
        optimizer="cma_cold",
        cma_es_config=CmaesStrategyConfig(mode="cold", seed=11, population_size=4),
    )

    assert result["status"] == "configuration_error"
    assert "incompatible CMA-ES checkpoint" in result["reason"]
    assert second_driver.calls == []


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
    last_decision = _load_iteration_decision(output_dir, result["iterations"][-1])
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
    last_decision = _load_iteration_decision(fresh_output, result["iterations"][-1])
    assert last_decision["optimizer"] == "cma_es"
    assert last_decision["cma_es"]["warm_started"] is True


def test_fit_material_cma_warm_loads_elite_archive_history(patched_pipeline):
    output_dir, lmat = patched_pipeline
    auto_dir = output_dir / "auto_adjust"
    auto_dir.mkdir(parents=True, exist_ok=True)
    archive_candidates = []
    for iteration, fit_score, gamma in ((7, 0.91, 2.9), (4, 0.83, 2.6)):
        params = dict(_initial_params())
        params["u_Gamma_Power"] = gamma
        candidate_dir = auto_dir / f"iter_{iteration:04d}" / "candidate"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        params_path = candidate_dir / "params.json"
        params_path.write_text(json.dumps(params), encoding="utf-8")
        archive_candidates.append(
            {
                "iteration": iteration,
                "iter_id": f"iter_{iteration:04d}",
                "fit_score": fit_score,
                "diff_score": 1.0 - fit_score,
                "params_path": str(params_path),
            }
        )
    (auto_dir / "optimizer_candidate_archive.json").write_text(
        json.dumps(
            {
                "top_k": 20,
                "selection_metric": "fit_score",
                "candidates": archive_candidates,
                "best": archive_candidates[0],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="cma_warm",
        iterations=2,
        cma_es_config=CmaesStrategyConfig(mode="warm", seed=11, population_size=4, warm_start_iters=2),
    )

    assert result["optimizer"] == "cma_warm"
    assert result["warm_start_history_size"] == 2
    assert result["warm_start_sources"] == {
        "limit": 2,
        "source": "elite_archive_first",
        "elite_archive": 2,
        "iteration_history": 0,
        "total": 2,
    }
    assert result["optimizer_evidence_summary"]["warm_start_sources"] == result["warm_start_sources"]
    last_decision = _load_iteration_decision(output_dir, result["iterations"][-1])
    assert last_decision["cma_es"]["warm_started"] is True
    assert last_decision["cma_es"]["warm_start_iters_used"] == 2


def test_fit_material_cma_warm_can_use_iteration_history_only(patched_pipeline):
    output_dir, lmat = patched_pipeline
    auto_dir = output_dir / "auto_adjust"
    auto_dir.mkdir(parents=True, exist_ok=True)

    archive_candidates = []
    for iteration, fit_score, gamma in ((7, 0.91, 2.9), (8, 0.88, 2.8)):
        params = dict(_initial_params())
        params["u_Gamma_Power"] = gamma
        candidate_dir = auto_dir / f"iter_{iteration:04d}" / "candidate"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        params_path = candidate_dir / "params.json"
        params_path.write_text(json.dumps(params), encoding="utf-8")
        archive_candidates.append(
            {
                "iteration": iteration,
                "iter_id": f"iter_{iteration:04d}",
                "fit_score": fit_score,
                "params_path": str(params_path),
            }
        )
    (auto_dir / "optimizer_candidate_archive.json").write_text(
        json.dumps({"candidates": archive_candidates, "best": archive_candidates[0]}, ensure_ascii=False),
        encoding="utf-8",
    )

    for iteration, fit_score, gamma in ((0, 0.42, 2.3), (1, 0.46, 2.4)):
        params = dict(_initial_params())
        params["u_Gamma_Power"] = gamma
        iter_dir = auto_dir / f"iter_{iteration:04d}"
        candidate_dir = iter_dir / "candidate"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        (candidate_dir / "params.json").write_text(json.dumps(params), encoding="utf-8")
        (iter_dir / "decision.json").write_text(
            json.dumps({"fit_score_before": fit_score, "diff_score_before": 1.0 - fit_score}),
            encoding="utf-8",
        )

    result = _run(
        output_dir=output_dir,
        laya_material_path=lmat,
        optimizer="cma_warm",
        iterations=2,
        cma_es_config=CmaesStrategyConfig(
            mode="warm",
            seed=11,
            population_size=4,
            warm_start_iters=2,
            warm_start_source="iteration_history",
        ),
    )

    assert result["warm_start_history_size"] == 2
    assert result["warm_start_sources"] == {
        "limit": 2,
        "source": "iteration_history",
        "elite_archive": 0,
        "iteration_history": 2,
        "total": 2,
    }
    last_decision = _load_iteration_decision(output_dir, result["iterations"][-1])
    assert last_decision["cma_es"]["warm_started"] is True
    assert last_decision["cma_es"]["warm_start_iters_used"] == 2


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
    last_decision = _load_iteration_decision(output_dir, result["iterations"][-1])
    assert last_decision["cma_es"]["warm_started"] is False, (
        "WS-CMA-ES with empty history must fall back to cold rather than crash"
    )
