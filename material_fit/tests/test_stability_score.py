from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.auto_adjust.stability import (  # noqa: E402
    browser_score_stability_sample,
    normalize_stability_score_policy,
    select_stability_policy_value,
    summarize_fresh_oracle_records,
    summarize_stability_samples,
)


def test_summarize_stability_samples_uses_conservative_min_score() -> None:
    samples = [
        _sample(0, 0.95, foreground_sum=61558),
        _sample(1, 0.82, foreground_sum=61580),
    ]

    summary = summarize_stability_samples(samples, score_drift_threshold=0.005)

    assert summary["stable"] is False
    assert summary["score_stable"] is False
    assert summary["foreground_stable"] is True
    assert summary["fit_score_spread"] == 0.13
    assert summary["conservative_fit_score"] == 0.82
    assert summary["conservative_diff_score"] == 0.18


def test_summarize_stability_samples_flags_foreground_drift() -> None:
    samples = [
        _sample(0, 0.90, foreground_sum=47126),
        _sample(1, 0.902, foreground_sum=47715),
    ]

    summary = summarize_stability_samples(
        samples,
        score_drift_threshold=0.005,
        foreground_abs_threshold=128.0,
        foreground_ratio_threshold=0.005,
    )

    assert summary["score_stable"] is True
    assert summary["foreground_stable"] is False
    assert summary["stable"] is False
    assert summary["worst_foreground_view_id"] == "v000_yaw0_pitch0"
    assert summary["worst_foreground_weight_sum_spread"] == 589.0


def test_browser_score_stability_sample_extracts_view_payload() -> None:
    sample = browser_score_stability_sample(
        {
            "fit_score": 0.91,
            "diff_score": 0.09,
            "views": [
                {
                    "view_id": "v000_yaw0_pitch0",
                    "fit_score": 0.91,
                    "diff_score": 0.09,
                    "foreground_weight_sum": 61558,
                }
            ],
        },
        repeat_index=2,
        label="repeat_02",
    )

    assert sample["repeat_index"] == 2
    assert sample["label"] == "repeat_02"
    assert sample["fit_score"] == 0.91
    assert sample["views"][0]["foreground_weight_sum"] == 61558.0


def test_select_stability_policy_value_lower_quartile_ignores_high_oracle_mode() -> None:
    summary = {
        "records": [
            {"fit_score": 0.87, "diff_score": 0.13},
            {"fit_score": 0.88, "diff_score": 0.12},
            {"fit_score": 0.89, "diff_score": 0.11},
            {"fit_score": 0.90, "diff_score": 0.10},
            {"fit_score": 0.91, "diff_score": 0.09},
            {"fit_score": 0.92, "diff_score": 0.08},
        ],
        "fit_score_median": 0.895,
        "diff_score_median": 0.105,
        "conservative_fit_score": 0.87,
        "conservative_diff_score": 0.13,
    }

    assert select_stability_policy_value(summary, "fit_score", "lower_quartile") == 0.88
    assert select_stability_policy_value(summary, "diff_score", "lower_quartile") == 0.12


def test_select_stability_policy_value_lower_quartile_falls_back_to_min_for_three_samples() -> None:
    summary = {
        "records": [
            {"fit_score": 0.87, "diff_score": 0.13},
            {"fit_score": 0.90, "diff_score": 0.10},
            {"fit_score": 0.91, "diff_score": 0.09},
        ],
        "conservative_fit_score": 0.87,
        "conservative_diff_score": 0.13,
    }

    assert select_stability_policy_value(summary, "fit_score", "q25") == 0.87
    assert select_stability_policy_value(summary, "diff_score", "q25") == 0.13


def test_normalize_stability_score_policy_accepts_lower_quartile_aliases() -> None:
    assert normalize_stability_score_policy("p25") == "lower_quartile"
    assert normalize_stability_score_policy("lower") == "lower_quartile"
    assert normalize_stability_score_policy("unknown", default="median") == "median"


def test_summarize_fresh_oracle_records_flags_foreground_drift() -> None:
    fresh_summary = {
        "status": "ok",
        "records": [
            _fresh_record(0, 0.910, foreground_sum=61000),
            _fresh_record(1, 0.912, foreground_sum=62000),
        ],
    }

    summary = summarize_fresh_oracle_records(
        fresh_summary,
        score_drift_threshold=0.005,
        foreground_abs_threshold=128.0,
        foreground_ratio_threshold=0.005,
    )

    assert summary is not None
    assert summary["score_stable"] is True
    assert summary["foreground_stable"] is False
    assert summary["stable"] is False
    assert summary["worst_foreground_view_id"] == "v000_yaw0_pitch0"
    assert summary["worst_foreground_weight_sum_spread"] == 1000.0


def test_select_stability_policy_value_uses_min_when_foreground_is_unstable() -> None:
    summary = {
        "foreground_stable": False,
        "records": [
            {"fit_score": 0.88, "diff_score": 0.12},
            {"fit_score": 0.89, "diff_score": 0.11},
            {"fit_score": 0.90, "diff_score": 0.10},
            {"fit_score": 0.91, "diff_score": 0.09},
            {"fit_score": 0.92, "diff_score": 0.08},
            {"fit_score": 0.93, "diff_score": 0.07},
        ],
        "fit_score_min": 0.88,
        "diff_score_max": 0.12,
        "conservative_fit_score": 0.88,
        "conservative_diff_score": 0.12,
    }

    assert select_stability_policy_value(summary, "fit_score", "lower_quartile") == 0.88
    assert select_stability_policy_value(summary, "diff_score", "lower_quartile") == 0.12


def test_dominant_foreground_mode_policy_scores_within_repeated_mode() -> None:
    fresh_summary = {
        "status": "ok",
        "records": [
            _fresh_record(0, 0.90, foreground_sum=61000),
            _fresh_record(1, 0.91, foreground_sum=61012),
            _fresh_record(2, 0.92, foreground_sum=61024),
            _fresh_record(3, 0.93, foreground_sum=61036),
            _fresh_record(4, 0.82, foreground_sum=62500),
            _fresh_record(5, 0.83, foreground_sum=62512),
        ],
    }

    summary = summarize_fresh_oracle_records(
        fresh_summary,
        score_drift_threshold=0.20,
        foreground_abs_threshold=128.0,
        foreground_ratio_threshold=0.005,
    )

    assert summary is not None
    assert summary["foreground_stable"] is False
    assert summary["dominant_foreground_mode"]["sample_count"] == 4
    assert summary["dominant_foreground_mode"]["fit_score_min"] == 0.90
    assert select_stability_policy_value(summary, "fit_score", "lower_quartile") == 0.82
    assert select_stability_policy_value(summary, "fit_score", "dominant_mode_lower_quartile") == 0.90
    diff_score = select_stability_policy_value(summary, "diff_score", "dominant_mode_lower_quartile")
    assert round(float(diff_score), 10) == 0.10


def test_canonical_foreground_mode_policy_uses_run_signature_over_larger_random_mode() -> None:
    fresh_summary = {
        "status": "ok",
        "records": [
            _fresh_record(0, 0.91, foreground_sum=61000),
            _fresh_record(1, 0.92, foreground_sum=61012),
            _fresh_record(2, 0.80, foreground_sum=62500),
            _fresh_record(3, 0.81, foreground_sum=62508),
            _fresh_record(4, 0.82, foreground_sum=62516),
            _fresh_record(5, 0.83, foreground_sum=62524),
        ],
    }
    canonical_signature = [
        {
            "view_id": "v000_yaw0_pitch0",
            "foreground_weight_sum_bucket": int(round(61000 / 128.0) * 128),
        }
    ]

    summary = summarize_fresh_oracle_records(
        fresh_summary,
        score_drift_threshold=0.20,
        foreground_abs_threshold=128.0,
        foreground_ratio_threshold=0.005,
        canonical_foreground_signature=canonical_signature,
    )

    assert summary is not None
    assert summary["dominant_foreground_mode"]["sample_count"] == 4
    assert summary["canonical_foreground_mode"]["sample_count"] == 2
    assert normalize_stability_score_policy("canonical_mode_p25") == "canonical_mode_lower_quartile"
    assert select_stability_policy_value(summary, "fit_score", "dominant_mode_lower_quartile") == 0.80
    assert select_stability_policy_value(summary, "fit_score", "canonical_mode_lower_quartile") == 0.91
    diff_score = select_stability_policy_value(summary, "diff_score", "canonical_mode_lower_quartile")
    assert round(float(diff_score), 10) == 0.09


def _sample(repeat_index: int, fit_score: float, *, foreground_sum: int) -> dict:
    return {
        "repeat_index": repeat_index,
        "label": f"repeat_{repeat_index}",
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


def _fresh_record(attempt_index: int, fit_score: float, *, foreground_sum: int) -> dict:
    return {
        "attempt_index": attempt_index,
        "fit_score": fit_score,
        "diff_score": 1.0 - fit_score,
        "browser_score": {
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
        },
    }
