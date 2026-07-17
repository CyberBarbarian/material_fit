from __future__ import annotations

import json
from pathlib import Path

from material_fit.fit_artifacts import _prune_iteration_artifacts, _record_iteration_outputs
from material_fit.fit_material import _load_iteration_series


def test_iteration_series_uses_incremental_jsonl_until_finalization(tmp_path: Path) -> None:
    series: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    snapshots: set[int] = set()
    payloads: dict[int, dict[str, object]] = {}

    for iteration in range(2):
        _record_iteration_outputs(
            auto_dir=tmp_path,
            iteration_payload={
                "iteration": iteration,
                "fit_score_before": 0.8 + 0.01 * iteration,
                "decision": {"optimizer": "material_stage1_hybrid"},
                "timing": {"iteration_total_ms": 400.0},
            },
            result_iterations=results,
            iteration_series=series,
            snapshot_iterations=snapshots,
            full_payloads=payloads,
            is_snapshot=iteration == 1,
            is_best=True,
        )

    jsonl_path = tmp_path / "iteration_series.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["iteration"] for line in lines] == [0, 1]
    assert not (tmp_path / "iteration_series.json").exists()
    assert (tmp_path / "snapshot_index.json").is_file()
    assert _load_iteration_series(tmp_path) == series


def test_iteration_artifact_pruning_runs_on_snapshot_cadence(tmp_path: Path) -> None:
    stale = tmp_path / "iter_0001" / "candidate"
    stale.mkdir(parents=True)
    (stale / "params.json").write_text("{}", encoding="utf-8")

    _prune_iteration_artifacts(
        tmp_path,
        [{"iteration": 1, "fit_score_before": 0.5}],
        current_iteration=2,
        snapshot_interval=25,
        keep_last_n=0,
        always_keep_best=False,
        always_keep_first=False,
    )
    assert (stale / "params.json").exists()

    _prune_iteration_artifacts(
        tmp_path,
        [{"iteration": 1, "fit_score_before": 0.5}],
        current_iteration=25,
        snapshot_interval=25,
        keep_last_n=0,
        always_keep_best=False,
        always_keep_first=False,
    )
    assert not (stale / "params.json").exists()
