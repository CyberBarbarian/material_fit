from __future__ import annotations

import atexit
import json
import math
import os
import re
import shutil
import subprocess
import time
import copy
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..laya_capture.asset_profile import capture_command_from_profile, load_asset_profile
from ..laya_capture.capture_quality import default_visual_quality_guard
from ..laya_capture.managed_runtime import ManagedRuntimeRenderer
from ..laya_capture.runtime_bridge import RuntimeCaptureBridge
from ..optimizer.material_discrete_space import (
    BROWSER_SCORE_OVERRIDE_PARAM,
    merge_candidate_into_material_patch,
    split_discrete_candidate,
)


_VIEW_ID_RE = re.compile(r"(v\d{3}_yaw-?\d+(?:\.\d+)?_pitch-?\d+(?:\.\d+)?)")


def _capture_config_with_asset_profile(config: dict[str, Any]) -> dict[str, Any]:
    capture_config = copy.deepcopy(config)
    runtime_cfg = capture_config.get("runtime_bridge")
    if not isinstance(runtime_cfg, dict) or not runtime_cfg.get("asset_profile"):
        return capture_config
    profile = load_asset_profile(str(runtime_cfg["asset_profile"]))
    defaults = capture_command_from_profile(profile)
    defaults.setdefault("width", int(profile.get("width") or 320))
    defaults.setdefault("height", int(profile.get("height") or 240))
    defaults.update(capture_config)
    normalized_runtime = copy.deepcopy(runtime_cfg)
    normalized_runtime["asset_profile"] = str(profile["_profile_path"])
    defaults["runtime_bridge"] = normalized_runtime
    queue_cfg = defaults.get("persistent_queue")
    if isinstance(queue_cfg, dict) and queue_cfg.get("enabled"):
        raise ValueError("asset-profile runtime_bridge and persistent_queue cannot both be enabled")
    return defaults


class RenderDriver:
    """Bridge between Python fitting code and the real Laya render scene.

    The first framework version supports two modes:
    - ``dry_run``: only writes candidate parameter files.
    - external command: invokes a user-provided renderer command later wired to
      the Laya benchmark scene and screenshot process.
    """

    def __init__(
        self,
        output_dir: str | Path,
        command: list[str] | None = None,
        dry_run: bool = True,
        capture_config: dict[str, Any] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.command = command or []
        self.dry_run = dry_run
        self.capture_config = _capture_config_with_asset_profile(capture_config or {})
        self._worker_name: str | None = None
        self._worker_index: int | None = None
        self._runtime_bridge: RuntimeCaptureBridge | None = None
        self._runtime_renderer: ManagedRuntimeRenderer | None = None
        self._persistent_queue: _PersistentQueueClient | None = None
        self._atexit_registered = False
        self._workers = self._build_workers()
        self.worker_count = len(self._workers) if self._workers else 1
        self.parallel_safe = bool(
            self._workers
            and len(self._workers) > 1
            and all(bool(worker_cfg.get("parallel_safe")) for worker_cfg, _ in self._workers)
        )
        if not self._workers and not self.dry_run:
            try:
                self._runtime_bridge = self._build_runtime_bridge()
                self._runtime_renderer = self._build_profile_runtime_renderer()
                self._persistent_queue = self._build_persistent_queue()
            except Exception:
                self.close()
                raise
        self.output_dir.mkdir(parents=True, exist_ok=True)
        atexit.register(self.close)
        self._atexit_registered = True

    @property
    def runtime_capture_base_url(self) -> str:
        if self._runtime_bridge is None:
            raise RuntimeError("runtime_bridge is not enabled for this RenderDriver")
        return self._runtime_bridge.base_url

    def close(self) -> None:
        if self._atexit_registered:
            atexit.unregister(self.close)
            self._atexit_registered = False
        for _worker_cfg, worker_driver in self._workers:
            worker_driver.close()
        if self._runtime_renderer is not None:
            self._runtime_renderer.stop()
            self._runtime_renderer = None
        if self._runtime_bridge is not None:
            self._runtime_bridge.stop()
            self._runtime_bridge = None
        if self._persistent_queue is not None:
            self._persistent_queue.reset()
        self._persistent_queue = None

    def reset_persistent_queue(self) -> bool:
        """Restart or invalidate the persistent queue before a validation render."""

        if self._workers:
            return any(worker_driver.reset_persistent_queue() for _worker_cfg, worker_driver in self._workers)
        if self._persistent_queue is None:
            return False
        return self._persistent_queue.reset()

    def select_persistent_oracle(
        self,
        *,
        iteration: int,
        params: dict[str, Any],
        attempts: int,
        min_fit_score: float | None = None,
        output_subdir: str = "oracle_stabilization",
        probe_candidates: list[dict[str, Any]] | None = None,
        selection_policy: str = "best",
    ) -> dict[str, Any]:
        """Start several isolated persistent queues and keep the best scorer.

        Fresh Laya/WebGL daemon starts can land in different deterministic
        render states. The optimizer needs one stable oracle, so this method
        scores probe parameters across isolated daemon attempts and adopts the
        best attempt for subsequent renders.
        """

        attempt_count = max(1, int(attempts))
        if attempt_count <= 1:
            return {"status": "skipped", "reason": "attempts_le_1", "attempts_requested": attempt_count}
        if self.dry_run:
            return {"status": "skipped", "reason": "dry_run", "attempts_requested": attempt_count}
        if self._workers:
            return {"status": "skipped", "reason": "worker_pool_enabled", "attempts_requested": attempt_count}
        queue_cfg = self.capture_config.get("persistent_queue")
        if not isinstance(queue_cfg, dict) or not queue_cfg.get("enabled"):
            return {"status": "skipped", "reason": "persistent_queue_disabled", "attempts_requested": attempt_count}
        if not _browser_score_config_enabled(self.capture_config):
            return {"status": "skipped", "reason": "browser_score_disabled", "attempts_requested": attempt_count}
        if _persistent_queue_base_port(queue_cfg) is None:
            return {
                "status": "skipped",
                "reason": "cap_port_required_for_attempt_isolation",
                "attempts_requested": attempt_count,
            }

        records: list[dict[str, Any]] = []
        selected_driver: RenderDriver | None = None
        selected_record: dict[str, Any] | None = None
        selected_score = -math.inf
        retained_attempts: list[tuple[dict[str, Any], RenderDriver, float]] = []
        selection_policy = _normalize_oracle_selection_policy(selection_policy)
        selection_output_root = self.output_dir / output_subdir
        selection_output_root.mkdir(parents=True, exist_ok=True)
        probes = _persistent_oracle_probe_candidates(params, probe_candidates)
        probe_count = len(probes)

        for attempt_index in range(attempt_count):
            attempt_capture_config = _capture_config_for_persistent_oracle_attempt(
                self.capture_config,
                attempt_index=attempt_index,
            )
            attempt_output_dir = selection_output_root / f"attempt_{attempt_index:02d}"
            attempt_driver = RenderDriver(
                output_dir=attempt_output_dir,
                command=self.command,
                dry_run=False,
                capture_config=attempt_capture_config,
            )
            keep_attempt = False
            record = _persistent_attempt_record(
                attempt_index=attempt_index,
                capture_config=attempt_capture_config,
            )
            probe_records: list[dict[str, Any]] = []
            probe_scores: dict[str, float] = {}
            try:
                weighted_score_sum = 0.0
                weight_sum = 0.0
                first_render_result: dict[str, Any] | None = None
                first_browser_score: dict[str, Any] | None = None
                for probe_index, probe in enumerate(probes):
                    probe_iteration = iteration + attempt_index * probe_count + probe_index
                    render_result = attempt_driver.render_candidate(probe_iteration, probe["params"])
                    if first_render_result is None:
                        first_render_result = render_result
                    browser_score = _browser_score_from_render_result(render_result)
                    if first_browser_score is None:
                        first_browser_score = browser_score
                    fit_score = _fit_score_from_browser_score(browser_score)
                    probe_record = {
                        "label": probe["label"],
                        "iteration": probe_iteration,
                        "weight": probe["weight"],
                        "status": str(render_result.get("status") or ""),
                        "returncode": render_result.get("returncode"),
                        "fit_score": fit_score if math.isfinite(fit_score) else None,
                        "browser_score": browser_score,
                    }
                    probe_records.append(probe_record)
                    if not math.isfinite(fit_score):
                        raise RuntimeError(f"probe {probe['label']} did not produce a finite browser_score")
                    probe_scores[str(probe["label"])] = fit_score
                    weighted_score_sum += fit_score * float(probe["weight"])
                    weight_sum += float(probe["weight"])

                if weight_sum <= 0.0:
                    raise RuntimeError("oracle probe portfolio has no positive total weight")
                fit_score = weighted_score_sum / weight_sum
                record.update(
                    {
                        "status": str(first_render_result.get("status") or "") if first_render_result else "ok",
                        "returncode": first_render_result.get("returncode") if first_render_result else None,
                        "fit_score": fit_score if math.isfinite(fit_score) else None,
                        "selection_score": fit_score if math.isfinite(fit_score) else None,
                        "browser_score": first_browser_score,
                        "probe_scores": probe_scores,
                        "probe_records": probe_records,
                        "output_dir": str(attempt_output_dir),
                    }
                )
                if selection_policy == "best" and math.isfinite(fit_score) and fit_score > selected_score:
                    if selected_driver is not None:
                        selected_driver.close()
                    selected_driver = attempt_driver
                    selected_record = record
                    selected_score = fit_score
                    keep_attempt = True
                elif selection_policy != "best" and math.isfinite(fit_score):
                    retained_attempts.append((record, attempt_driver, fit_score))
                    keep_attempt = True
            except Exception as exc:  # noqa: BLE001
                record.update(
                    {
                        "status": "failed",
                        "error": str(exc),
                        "probe_scores": probe_scores,
                        "probe_records": probe_records,
                        "output_dir": str(attempt_output_dir),
                    }
                )
            finally:
                records.append(record)
                if not keep_attempt:
                    attempt_driver.close()

            if (
                selection_policy == "best"
                and min_fit_score is not None
                and math.isfinite(selected_score)
                and selected_score >= float(min_fit_score)
            ):
                break

        if selection_policy != "best" and retained_attempts:
            selected_record, selected_driver, selected_score = _select_retained_oracle_attempt(
                retained_attempts,
                selection_policy=selection_policy,
            )
            for record, attempt_driver, _score in retained_attempts:
                if attempt_driver is not selected_driver:
                    attempt_driver.close()

        if selected_driver is None or selected_record is None:
            return {
                "status": "failed",
                "reason": "no_scored_attempt",
                "attempts_requested": attempt_count,
                "attempts_completed": len(records),
                "records": records,
            }

        if (
            self._persistent_queue is not None
            and self._persistent_queue is not selected_driver._persistent_queue
            and bool(getattr(self._persistent_queue, "_ensured", False))
        ):
            self._persistent_queue.reset()
        self.capture_config = copy.deepcopy(selected_driver.capture_config)
        self._persistent_queue = selected_driver._persistent_queue
        selected_driver._persistent_queue = None
        selected_driver.close()

        return {
            "status": "ok",
            "attempts_requested": attempt_count,
            "attempts_completed": len(records),
            "selection_policy": selection_policy,
            "selected_attempt": selected_record["attempt"],
            "selected_fit_score": selected_score,
            "selected_state_dir": selected_record.get("state_dir"),
            "selected_cap_port": selected_record.get("cap_port"),
            "selected_http_port": selected_record.get("http_port"),
            "selected_probe_scores": selected_record.get("probe_scores"),
            "probe_count": probe_count,
            "records": records,
        }

    def validate_persistent_oracle_stability(
        self,
        *,
        iteration: int,
        params: dict[str, Any],
        attempts: int,
        output_subdir: str = "fresh_oracle_validation",
    ) -> dict[str, Any]:
        """Score one candidate across isolated fresh persistent queue starts.

        Unlike ``select_persistent_oracle``, this method never adopts an
        attempt. It is intended for final-candidate validation where the
        conservative score should be the minimum observed score across fresh
        daemon starts, not the best selected daemon score.
        """

        attempt_count = max(1, int(attempts))
        if self.dry_run:
            return {"status": "skipped", "reason": "dry_run", "attempts_requested": attempt_count}
        if self._workers:
            return {"status": "skipped", "reason": "worker_pool_enabled", "attempts_requested": attempt_count}
        queue_cfg = self.capture_config.get("persistent_queue")
        if not isinstance(queue_cfg, dict) or not queue_cfg.get("enabled"):
            return {"status": "skipped", "reason": "persistent_queue_disabled", "attempts_requested": attempt_count}
        if not _browser_score_config_enabled(self.capture_config):
            return {"status": "skipped", "reason": "browser_score_disabled", "attempts_requested": attempt_count}
        if _persistent_queue_base_port(queue_cfg) is None:
            return {
                "status": "skipped",
                "reason": "cap_port_required_for_attempt_isolation",
                "attempts_requested": attempt_count,
            }

        records: list[dict[str, Any]] = []
        fit_scores: list[float] = []
        diff_scores: list[float] = []
        validation_output_root = self.output_dir / output_subdir
        validation_output_root.mkdir(parents=True, exist_ok=True)
        validation_port_offset = _persistent_queue_validation_port_offset(queue_cfg)
        validation_timeout = _persistent_queue_validation_timeout(queue_cfg)
        for attempt_index in range(attempt_count):
            attempt_capture_config = _capture_config_for_persistent_oracle_attempt(
                self.capture_config,
                attempt_index=attempt_index,
                port_offset=validation_port_offset,
                timeout_s=validation_timeout,
            )
            attempt_output_dir = validation_output_root / f"attempt_{attempt_index:02d}"
            attempt_driver = RenderDriver(
                output_dir=attempt_output_dir,
                command=self.command,
                dry_run=False,
                capture_config=attempt_capture_config,
            )
            record = _persistent_attempt_record(
                attempt_index=attempt_index,
                capture_config=attempt_capture_config,
            )
            try:
                render_result = attempt_driver.render_candidate(iteration + attempt_index, params)
                browser_score = _browser_score_from_render_result(render_result)
                fit_score = _fit_score_from_browser_score(browser_score)
                diff_score = _diff_score_from_browser_score(browser_score, fit_score=fit_score)
                record.update(
                    {
                        "status": str(render_result.get("status") or ""),
                        "returncode": render_result.get("returncode"),
                        "fit_score": fit_score if math.isfinite(fit_score) else None,
                        "diff_score": diff_score if math.isfinite(diff_score) else None,
                        "browser_score": browser_score,
                        "output_dir": str(attempt_output_dir),
                    }
                )
                if math.isfinite(fit_score):
                    fit_scores.append(fit_score)
                if math.isfinite(diff_score):
                    diff_scores.append(diff_score)
            except Exception as exc:  # noqa: BLE001
                record.update({"status": "failed", "error": str(exc), "output_dir": str(attempt_output_dir)})
            finally:
                records.append(record)
                attempt_driver.close()

        score_summary = _fit_score_distribution(fit_scores)
        diff_summary = _fit_score_distribution(diff_scores)
        if not fit_scores:
            return {
                "status": "failed",
                "reason": "no_scored_attempt",
                "attempts_requested": attempt_count,
                "attempts_completed": len(records),
                "attempts_scored": 0,
                "score_policy": "fresh_oracle_min",
                "records": records,
            }
        return {
            "status": "ok",
            "attempts_requested": attempt_count,
            "attempts_completed": len(records),
            "attempts_scored": len(fit_scores),
            "score_policy": "fresh_oracle_min",
            "conservative_fit_score": score_summary["min"],
            "conservative_diff_score": diff_summary["max"],
            "fit_score_min": score_summary["min"],
            "fit_score_median": score_summary["median"],
            "fit_score_mean": score_summary["mean"],
            "fit_score_max": score_summary["max"],
            "fit_score_spread": score_summary["spread"],
            "diff_score_min": diff_summary["min"],
            "diff_score_median": diff_summary["median"],
            "diff_score_mean": diff_summary["mean"],
            "diff_score_max": diff_summary["max"],
            "diff_score_spread": diff_summary["spread"],
            "records": records,
        }

    def validate_persistent_oracle_stability_many(
        self,
        *,
        iteration: int,
        candidates: list[dict[str, Any]],
        attempts: int,
        output_subdir: str = "fresh_oracle_batch_validation",
    ) -> dict[str, Any]:
        """Score several candidates across the same fresh persistent starts.

        This preserves the fresh-oracle isolation used by
        :meth:`validate_persistent_oracle_stability`, but amortizes daemon
        startup cost across a batch of candidates.
        """

        attempt_count = max(1, int(attempts))
        candidate_specs: list[dict[str, Any]] = []
        for candidate_index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                continue
            params = candidate.get("params")
            if not isinstance(params, dict):
                continue
            candidate_specs.append(
                {
                    "candidate_index": candidate_index,
                    "candidate_id": str(candidate.get("candidate_id", f"candidate_{candidate_index:02d}")),
                    "params": copy.deepcopy(params),
                }
            )
        if not candidate_specs:
            return {
                "status": "skipped",
                "reason": "no_candidates",
                "attempts_requested": attempt_count,
                "candidate_count": 0,
                "candidates": [],
            }
        if self.dry_run:
            return {"status": "skipped", "reason": "dry_run", "attempts_requested": attempt_count}
        if self._workers:
            return {"status": "skipped", "reason": "worker_pool_enabled", "attempts_requested": attempt_count}
        queue_cfg = self.capture_config.get("persistent_queue")
        if not isinstance(queue_cfg, dict) or not queue_cfg.get("enabled"):
            return {"status": "skipped", "reason": "persistent_queue_disabled", "attempts_requested": attempt_count}
        if not _browser_score_config_enabled(self.capture_config):
            return {"status": "skipped", "reason": "browser_score_disabled", "attempts_requested": attempt_count}
        if _persistent_queue_base_port(queue_cfg) is None:
            return {
                "status": "skipped",
                "reason": "cap_port_required_for_attempt_isolation",
                "attempts_requested": attempt_count,
            }

        candidate_records: list[dict[str, Any]] = [
            {
                "candidate_index": int(spec["candidate_index"]),
                "candidate_id": str(spec["candidate_id"]),
                "records": [],
            }
            for spec in candidate_specs
        ]
        fit_scores_by_candidate: list[list[float]] = [[] for _spec in candidate_specs]
        diff_scores_by_candidate: list[list[float]] = [[] for _spec in candidate_specs]
        validation_output_root = self.output_dir / output_subdir
        validation_output_root.mkdir(parents=True, exist_ok=True)
        validation_port_offset = _persistent_queue_validation_port_offset(queue_cfg)
        validation_timeout = _persistent_queue_validation_timeout(queue_cfg)
        for attempt_index in range(attempt_count):
            attempt_capture_config = _capture_config_for_persistent_oracle_attempt(
                self.capture_config,
                attempt_index=attempt_index,
                port_offset=validation_port_offset,
                timeout_s=validation_timeout,
            )
            attempt_output_dir = validation_output_root / f"attempt_{attempt_index:02d}"
            attempt_driver = RenderDriver(
                output_dir=attempt_output_dir,
                command=self.command,
                dry_run=False,
                capture_config=attempt_capture_config,
            )
            try:
                for local_candidate_index, spec in enumerate(candidate_specs):
                    render_iteration = iteration + attempt_index * 1000 + local_candidate_index
                    record = _persistent_attempt_record(
                        attempt_index=attempt_index,
                        capture_config=attempt_capture_config,
                    )
                    record.update(
                        {
                            "candidate_index": int(spec["candidate_index"]),
                            "candidate_id": str(spec["candidate_id"]),
                            "render_iteration": render_iteration,
                        }
                    )
                    try:
                        render_result = attempt_driver.render_candidate(render_iteration, spec["params"])
                        browser_score = _browser_score_from_render_result(render_result)
                        fit_score = _fit_score_from_browser_score(browser_score)
                        diff_score = _diff_score_from_browser_score(browser_score, fit_score=fit_score)
                        record.update(
                            {
                                "status": str(render_result.get("status") or ""),
                                "returncode": render_result.get("returncode"),
                                "fit_score": fit_score if math.isfinite(fit_score) else None,
                                "diff_score": diff_score if math.isfinite(diff_score) else None,
                                "browser_score": browser_score,
                                "output_dir": str(attempt_output_dir),
                            }
                        )
                        if math.isfinite(fit_score):
                            fit_scores_by_candidate[local_candidate_index].append(fit_score)
                        if math.isfinite(diff_score):
                            diff_scores_by_candidate[local_candidate_index].append(diff_score)
                    except Exception as exc:  # noqa: BLE001
                        record.update({"status": "failed", "error": str(exc), "output_dir": str(attempt_output_dir)})
                    finally:
                        candidate_records[local_candidate_index]["records"].append(record)
            finally:
                attempt_driver.close()

        candidate_summaries: list[dict[str, Any]] = []
        ok_count = 0
        for local_candidate_index, candidate_payload in enumerate(candidate_records):
            fit_scores = fit_scores_by_candidate[local_candidate_index]
            diff_scores = diff_scores_by_candidate[local_candidate_index]
            if not fit_scores:
                candidate_summaries.append(
                    {
                        **candidate_payload,
                        "status": "failed",
                        "reason": "no_scored_attempt",
                        "attempts_requested": attempt_count,
                        "attempts_completed": len(candidate_payload["records"]),
                        "attempts_scored": 0,
                        "score_policy": "fresh_oracle_min",
                    }
                )
                continue
            score_summary = _fit_score_distribution(fit_scores)
            diff_summary = _fit_score_distribution(diff_scores)
            ok_count += 1
            candidate_summaries.append(
                {
                    **candidate_payload,
                    "status": "ok",
                    "attempts_requested": attempt_count,
                    "attempts_completed": len(candidate_payload["records"]),
                    "attempts_scored": len(fit_scores),
                    "score_policy": "fresh_oracle_min",
                    "conservative_fit_score": score_summary["min"],
                    "conservative_diff_score": diff_summary["max"],
                    "fit_score_min": score_summary["min"],
                    "fit_score_median": score_summary["median"],
                    "fit_score_mean": score_summary["mean"],
                    "fit_score_max": score_summary["max"],
                    "fit_score_spread": score_summary["spread"],
                    "diff_score_min": diff_summary["min"],
                    "diff_score_median": diff_summary["median"],
                    "diff_score_mean": diff_summary["mean"],
                    "diff_score_max": diff_summary["max"],
                    "diff_score_spread": diff_summary["spread"],
                }
            )

        return {
            "status": "ok" if ok_count == len(candidate_summaries) else "partial" if ok_count else "failed",
            "attempts_requested": attempt_count,
            "attempts_completed": attempt_count,
            "candidate_count": len(candidate_summaries),
            "candidates_scored": ok_count,
            "score_policy": "fresh_oracle_min",
            "candidates": candidate_summaries,
        }

    def render_candidate(self, iteration: int, params: dict[str, Any]) -> dict[str, Any]:
        worker = self._select_worker(iteration)
        if worker is not None:
            worker_cfg, worker_driver = worker
            result = worker_driver.render_candidate(iteration, params)
            result["worker"] = {
                "index": int(worker_cfg["index"]),
                "name": str(worker_cfg["name"]),
            }
            return result

        iteration_dir = self.output_dir / "iterations" / f"iter_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        params_path = iteration_dir / "params.json"
        params_path.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")

        if self._runtime_bridge is not None:
            return self._render_with_runtime_bridge(
                iteration=iteration,
                params=params,
                iteration_dir=iteration_dir,
                params_path=params_path,
            )

        if self.dry_run or (self._persistent_queue is None and not self.command):
            return {"status": "dry_run", "params_path": str(params_path), "screenshots": []}

        if self._persistent_queue is not None:
            return self._persistent_queue.render(
                capture_config=self.capture_config,
                iteration=iteration,
                params_path=params_path,
                iteration_dir=iteration_dir,
                params=params,
            )

        completed = subprocess.run(
            [*self.command, str(params_path), str(iteration_dir)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        screenshots = _capture_files(iteration_dir)
        result = {
            "status": "ok" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "params_path": str(params_path),
            "screenshots": screenshots,
            "candidate_overrides": _build_candidate_overrides(screenshots),
        }
        persistent_result = _read_optional_persistent_result(iteration_dir)
        if persistent_result is not None:
            result["persistent_result"] = persistent_result
            browser_score = _browser_score_payload(persistent_result)
            if browser_score is not None:
                result["browser_score"] = browser_score
        return result

    def capture_candidate(self, iteration: int, params: dict[str, Any]) -> dict[str, Any]:
        """Write candidate params and invoke the configured screenshot command.

        The default command shape is intentionally simple and product-friendly:
        ``command <capture_request.json> <output.png>``. The provided
        ``vision/capture_laya.js`` helper implements this contract using
        Puppeteer, but teams may replace it with any renderer/capture program.
        """

        worker = self._select_worker(iteration)
        if worker is not None:
            worker_cfg, worker_driver = worker
            result = worker_driver.capture_candidate(iteration, params)
            result["worker"] = {
                "index": int(worker_cfg["index"]),
                "name": str(worker_cfg["name"]),
            }
            return result

        iteration_dir = self.output_dir / "iterations" / f"iter_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        params_path = iteration_dir / "params.json"
        params_path.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
        screenshot_path = iteration_dir / "laya_capture.png"
        request_path = iteration_dir / "capture_request.json"
        request = _build_capture_request(self.capture_config, params_path, params)
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

        capture_command = self.capture_config.get("command") or self.command
        if self.dry_run or (self._runtime_bridge is None and not capture_command):
            return {
                "status": "dry_run",
                "params_path": str(params_path),
                "capture_request_path": str(request_path),
                "screenshots": [],
            }

        if self._runtime_bridge is not None:
            return self._render_with_runtime_bridge(
                iteration=iteration,
                params=params,
                iteration_dir=iteration_dir,
                params_path=params_path,
                request=request,
                request_path=request_path,
            )

        completed = subprocess.run(
            [*capture_command, str(request_path), str(screenshot_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        screenshots = [str(screenshot_path)] if screenshot_path.exists() else []
        return {
            "status": "ok" if completed.returncode == 0 and screenshot_path.exists() else "failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "params_path": str(params_path),
            "capture_request_path": str(request_path),
            "screenshots": screenshots,
            "candidate_overrides": _build_candidate_overrides(screenshots),
        }

    def _render_with_runtime_bridge(
        self,
        *,
        iteration: int,
        params: dict[str, Any],
        iteration_dir: Path,
        params_path: Path,
        request: dict[str, Any] | None = None,
        request_path: Path | None = None,
    ) -> dict[str, Any]:
        if self._runtime_bridge is None:
            raise RuntimeError("runtime_bridge is not enabled")
        request_path = request_path or iteration_dir / "capture_request.json"
        request = request or _build_capture_request(self.capture_config, params_path, params)
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        runtime_cfg = self.capture_config.get("runtime_bridge")
        runtime_cfg = runtime_cfg if isinstance(runtime_cfg, dict) else {}
        runtime_output_dir = iteration_dir / str(runtime_cfg.get("output_subdir") or "laya_multiview")
        runtime_request = dict(request)
        runtime_request["nonce"] = str(runtime_request.get("nonce") or f"capture-{iteration:04d}")
        result = self._runtime_bridge.capture(
            runtime_request,
            output_dir=runtime_output_dir,
            timeout_s=float(runtime_cfg.get("timeout_s", self.capture_config.get("timeout_s", 90)) or 90),
        )
        return {
            **result,
            "params_path": str(params_path),
            "capture_request_path": str(request_path),
        }

    def _build_runtime_bridge(self) -> RuntimeCaptureBridge | None:
        runtime_cfg = self.capture_config.get("runtime_bridge")
        if not isinstance(runtime_cfg, dict) or not runtime_cfg.get("enabled"):
            return None
        raw_port = runtime_cfg.get("port", 8787)
        port = 8787 if raw_port is None or raw_port == "" else int(raw_port)
        bridge = RuntimeCaptureBridge(
            host=str(runtime_cfg.get("host") or "127.0.0.1"),
            port=port,
        )
        if bool(runtime_cfg.get("auto_start", True)):
            bridge.start()
        return bridge

    def _build_profile_runtime_renderer(self) -> ManagedRuntimeRenderer | None:
        runtime_cfg = self.capture_config.get("runtime_bridge")
        if not isinstance(runtime_cfg, dict) or self._runtime_bridge is None:
            return None
        profile_path = runtime_cfg.get("asset_profile")
        if not profile_path or not bool(runtime_cfg.get("auto_start_renderer", True)):
            return None
        state_value = runtime_cfg.get("state_dir")
        state_dir = Path(str(state_value)).expanduser() if state_value else self.output_dir / "runtime_renderer"
        node_modules = runtime_cfg.get("node_modules")
        renderer = ManagedRuntimeRenderer(
            profile_path=str(profile_path),
            server_url=self._runtime_bridge.base_url,
            state_dir=state_dir,
            timeout_s=float(runtime_cfg.get("startup_timeout_s", runtime_cfg.get("timeout_s", 30)) or 30),
            node_modules=str(node_modules) if node_modules else None,
        )
        renderer.start()
        return renderer

    def _build_persistent_queue(self) -> "_PersistentQueueClient | None":
        queue_cfg = self.capture_config.get("persistent_queue")
        if not isinstance(queue_cfg, dict) or not queue_cfg.get("enabled"):
            return None
        return _PersistentQueueClient(queue_cfg)

    def _build_workers(self) -> list[tuple[dict[str, Any], "RenderDriver"]]:
        raw_workers = self.capture_config.get("workers")
        if not isinstance(raw_workers, list) or not raw_workers:
            return []
        parent_capture_config = {
            key: copy.deepcopy(value)
            for key, value in self.capture_config.items()
            if key != "workers"
        }
        workers: list[tuple[dict[str, Any], RenderDriver]] = []
        for index, raw in enumerate(raw_workers):
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or f"worker_{index}")
            output_dir_value = raw.get("output_dir") or raw.get("outputDir")
            output_dir = Path(str(output_dir_value)) if output_dir_value else self.output_dir / "workers" / name
            worker_capture_config = copy.deepcopy(parent_capture_config)
            overrides = raw.get("capture_config") if isinstance(raw.get("capture_config"), dict) else {}
            worker_capture_config.update(copy.deepcopy(overrides))
            worker_command = raw.get("command") if isinstance(raw.get("command"), list) else self.command
            worker_driver = RenderDriver(
                output_dir=output_dir,
                command=[str(item) for item in worker_command],
                dry_run=bool(raw.get("dry_run", self.dry_run)),
                capture_config=worker_capture_config,
            )
            worker_driver._worker_name = name
            worker_driver._worker_index = index
            workers.append(
                (
                    {
                        "index": index,
                        "name": name,
                        "parallel_safe": bool(raw.get("parallel_safe", False)),
                    },
                    worker_driver,
                )
            )
        return workers

    def _select_worker(self, iteration: int) -> tuple[dict[str, Any], "RenderDriver"] | None:
        if not self._workers:
            return None
        return self._workers[int(iteration) % len(self._workers)]


def _browser_score_config_enabled(capture_config: dict[str, Any]) -> bool:
    browser_score = capture_config.get("browser_score")
    return isinstance(browser_score, dict) and bool(browser_score.get("enabled"))


def _capture_config_for_persistent_oracle_attempt(
    capture_config: dict[str, Any],
    *,
    attempt_index: int,
    port_offset: int = 0,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(capture_config)
    updated.pop("workers", None)
    queue_cfg = updated.get("persistent_queue") if isinstance(updated.get("persistent_queue"), dict) else {}
    queue_cfg = copy.deepcopy(queue_cfg)
    attempt_timeout = _positive_float_or_none(timeout_s)
    if attempt_timeout is None:
        attempt_timeout = _positive_float_or_none(
            queue_cfg.get(
                "oracle_selection_timeout_s",
                queue_cfg.get("oracle_selection_timeout_sec", queue_cfg.get("oracle_attempt_timeout_s")),
            )
        )
    if attempt_timeout is not None:
        queue_cfg["timeout_s"] = attempt_timeout
        queue_cfg["timeout_sec"] = attempt_timeout
    base_state_dir = Path(str(queue_cfg.get("state_dir") or queue_cfg.get("stateDir") or "persistent_state")).expanduser()
    selection_root = Path(
        str(
            queue_cfg.get("oracle_selection_state_root_dir")
            or queue_cfg.get("selection_state_root_dir")
            or (base_state_dir.parent / f"{base_state_dir.name}_oracle_selection")
        )
    ).expanduser()
    attempt_state_dir = selection_root / f"attempt_{attempt_index:02d}"
    attempt_queue_dir = attempt_state_dir / "queue"
    attempt_result_dir = attempt_state_dir / "results"
    attempt_ready_file = attempt_state_dir / "ready.json"

    replacements = {
        "state_dir": str(attempt_state_dir),
        "queue_dir": str(attempt_queue_dir),
        "result_dir": str(attempt_result_dir),
        "ready_file": str(attempt_ready_file),
        "attempt_index": str(attempt_index),
    }

    queue_cfg["state_dir"] = str(attempt_state_dir)
    if "stateDir" in queue_cfg:
        queue_cfg["stateDir"] = str(attempt_state_dir)
    queue_cfg["queue_dir"] = str(attempt_queue_dir)
    queue_cfg["result_dir"] = str(attempt_result_dir)
    queue_cfg["ready_file"] = str(attempt_ready_file)

    environment = {
        str(key): str(value)
        for key, value in (queue_cfg.get("environment") or {}).items()
    } if isinstance(queue_cfg.get("environment"), dict) else {}
    environment.update(
        {
            "STATE_DIR": str(attempt_state_dir),
            "QUEUE_DIR": str(attempt_queue_dir),
            "RESULT_DIR": str(attempt_result_dir),
            "READY_FILE": str(attempt_ready_file),
            "MATERIAL_FIT_PERSISTENT_STATE_DIR": str(attempt_state_dir),
            "MATERIAL_FIT_PERSISTENT_LOG_DIR": str(attempt_state_dir / "logs"),
        }
    )

    base_port = _persistent_queue_base_port(queue_cfg)
    if base_port is not None:
        port_stride = _positive_int_or_default(queue_cfg.get("oracle_selection_port_stride"), 10)
        attempt_port = base_port + max(0, int(port_offset)) + attempt_index * port_stride
        queue_cfg["cap_port"] = attempt_port
        if "capPort" in queue_cfg:
            queue_cfg["capPort"] = attempt_port
        queue_cfg["server_base_url"] = f"http://127.0.0.1:{attempt_port}"
        environment["CAP_PORT"] = str(attempt_port)
        replacements["cap_port"] = str(attempt_port)
        base_http_port = _persistent_queue_base_http_port(queue_cfg)
        if base_http_port is not None:
            attempt_http_port = base_http_port + max(0, int(port_offset)) + attempt_index * port_stride
            queue_cfg["http_port"] = attempt_http_port
            if "httpPort" in queue_cfg:
                queue_cfg["httpPort"] = attempt_http_port
            environment["HTTP_PORT"] = str(attempt_http_port)
            replacements["http_port"] = str(attempt_http_port)

    queue_cfg["environment"] = environment
    for key in ("ensure_command", "stop_command"):
        command = queue_cfg.get(key)
        if isinstance(command, list):
            queue_cfg[key] = [_format_command_token(str(item), replacements) for item in command]
    updated["persistent_queue"] = queue_cfg
    return updated


def _persistent_attempt_record(*, attempt_index: int, capture_config: dict[str, Any]) -> dict[str, Any]:
    queue_cfg = capture_config.get("persistent_queue") if isinstance(capture_config.get("persistent_queue"), dict) else {}
    return {
        "attempt": attempt_index,
        "state_dir": str(queue_cfg.get("state_dir") or queue_cfg.get("stateDir") or ""),
        "cap_port": _persistent_queue_base_port(queue_cfg),
        "http_port": _persistent_queue_base_http_port(queue_cfg),
    }


def _persistent_oracle_probe_candidates(
    params: dict[str, Any],
    probe_candidates: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not probe_candidates:
        return [{"label": "probe_00", "params": copy.deepcopy(params), "weight": 1.0}]

    probes: list[dict[str, Any]] = []
    for index, raw_probe in enumerate(probe_candidates):
        if not isinstance(raw_probe, dict):
            continue
        label = str(raw_probe.get("label") or raw_probe.get("name") or f"probe_{index:02d}")
        if isinstance(raw_probe.get("params"), dict):
            probe_params = copy.deepcopy(raw_probe["params"])
        elif isinstance(raw_probe.get("param_values"), dict):
            probe_params = copy.deepcopy(raw_probe["param_values"])
        else:
            probe_params = {
                str(key): copy.deepcopy(value)
                for key, value in raw_probe.items()
                if key not in {"label", "name", "weight"}
            }
        if not probe_params:
            continue
        weight = _positive_float_or_default(raw_probe.get("weight"), 1.0)
        probes.append({"label": label, "params": probe_params, "weight": weight})

    if not probes:
        return [{"label": "probe_00", "params": copy.deepcopy(params), "weight": 1.0}]
    return probes


def _normalize_oracle_selection_policy(value: Any) -> str:
    policy = str(value or "best").strip().lower()
    aliases = {
        "max": "best",
        "highest": "best",
        "p100": "best",
        "middle": "median",
        "p50": "median",
        "min": "worst",
        "lowest": "worst",
        "p0": "worst",
    }
    policy = aliases.get(policy, policy)
    return policy if policy in {"best", "median", "worst"} else "best"


def _select_retained_oracle_attempt(
    retained_attempts: list[tuple[dict[str, Any], "RenderDriver", float]],
    *,
    selection_policy: str,
) -> tuple[dict[str, Any], "RenderDriver", float]:
    ordered = sorted(retained_attempts, key=lambda item: item[2])
    if selection_policy == "worst":
        return ordered[0]
    if selection_policy == "median":
        return ordered[len(ordered) // 2]
    return ordered[-1]


def _format_command_token(token: str, replacements: dict[str, str]) -> str:
    try:
        return token.format(**replacements)
    except (KeyError, ValueError):
        return token


def _persistent_queue_base_port(queue_cfg: dict[str, Any]) -> int | None:
    environment = queue_cfg.get("environment") if isinstance(queue_cfg.get("environment"), dict) else {}
    return _int_or_none(queue_cfg.get("cap_port") or queue_cfg.get("capPort") or environment.get("CAP_PORT"))


def _persistent_queue_base_http_port(queue_cfg: dict[str, Any]) -> int | None:
    environment = queue_cfg.get("environment") if isinstance(queue_cfg.get("environment"), dict) else {}
    return _int_or_none(queue_cfg.get("http_port") or queue_cfg.get("httpPort") or environment.get("HTTP_PORT"))


def _persistent_queue_validation_port_offset(queue_cfg: dict[str, Any]) -> int:
    return _nonnegative_int_or_default(
        queue_cfg.get("oracle_validation_port_offset", queue_cfg.get("fresh_oracle_validation_port_offset")),
        1000,
    )


def _persistent_queue_validation_timeout(queue_cfg: dict[str, Any]) -> float | None:
    return _positive_float_or_none(
        queue_cfg.get(
            "fresh_oracle_validation_timeout_s",
            queue_cfg.get(
                "fresh_oracle_validation_timeout_sec",
                queue_cfg.get("oracle_validation_timeout_s", queue_cfg.get("oracle_validation_timeout_sec")),
            ),
        )
    )


def _nonnegative_int_or_default(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(0, parsed)


def _positive_int_or_default(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(1, parsed)


def _positive_float_or_default(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    if not math.isfinite(parsed) or parsed <= 0.0:
        return float(default)
    return parsed


def _positive_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0.0:
        return None
    return parsed


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _browser_score_from_render_result(render_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(render_result, dict):
        return None
    persistent_result = render_result.get("persistent_result")
    if isinstance(persistent_result, dict):
        payload = _browser_score_payload(persistent_result)
        if payload is not None:
            return copy.deepcopy(payload)
    payload = _browser_score_payload(render_result)
    return copy.deepcopy(payload) if payload is not None else None


def _fit_score_from_browser_score(browser_score: dict[str, Any] | None) -> float:
    if not isinstance(browser_score, dict):
        return -math.inf
    for key in ("fit_score", "score"):
        value = browser_score.get(key)
        try:
            score = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score):
            continue
        if key == "score" and score > 1.0:
            score /= 100.0
        return score
    return -math.inf


def _diff_score_from_browser_score(browser_score: dict[str, Any] | None, *, fit_score: float) -> float:
    if isinstance(browser_score, dict):
        try:
            diff_score = float(browser_score.get("diff_score"))
        except (TypeError, ValueError):
            diff_score = math.nan
        if math.isfinite(diff_score):
            return diff_score
    if math.isfinite(fit_score):
        return max(0.0, 1.0 - fit_score)
    return math.inf


def _fit_score_distribution(scores: list[float]) -> dict[str, float | None]:
    finite_scores = [float(score) for score in scores if math.isfinite(float(score))]
    if not finite_scores:
        return {"min": None, "median": None, "mean": None, "max": None, "spread": None}
    ordered = sorted(finite_scores)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        median = ordered[middle]
    else:
        median = (ordered[middle - 1] + ordered[middle]) / 2.0
    return {
        "min": ordered[0],
        "median": median,
        "mean": sum(ordered) / count,
        "max": ordered[-1],
        "spread": ordered[-1] - ordered[0],
    }


def _capture_files(directory: Path) -> list[str]:
    return [
        str(path)
        for path in sorted(
            item
            for pattern in ("*.png", "*.rgba")
            for item in directory.glob(pattern)
        )
    ]


def _build_candidate_overrides(files: list[str | Path]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for file_path in files:
        path = Path(file_path)
        value = str(path)
        overrides[path.name] = value
        overrides[path.stem] = value
        match = _VIEW_ID_RE.search(path.stem)
        if match:
            overrides[match.group(1)] = value
    return overrides


def _path_replacements_from_config(config: dict[str, Any]) -> list[tuple[str, str]]:
    raw = config.get("path_replacements", config.get("path_mappings", []))
    if not isinstance(raw, list):
        return []
    replacements: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        source = entry.get("from") or entry.get("source") or entry.get("remote")
        target = entry.get("to") or entry.get("target") or entry.get("local")
        if source is None or target is None:
            continue
        source_text = str(source)
        target_text = str(target)
        if source_text:
            replacements.append((source_text, target_text))
    return replacements


def _rewrite_string_paths(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, str):
        for source, target in replacements:
            if not value.startswith(source):
                continue
            suffix = value[len(source):]
            if "\\" in target:
                suffix = suffix.replace("/", "\\")
            return f"{target}{suffix}"
        return value
    if isinstance(value, list):
        return [_rewrite_string_paths(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_string_paths(item, replacements) for key, item in value.items()}
    return value


class _PersistentQueueClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = copy.deepcopy(config)
        self.state_dir = Path(str(config.get("state_dir") or config.get("stateDir") or "")).expanduser()
        if not self.state_dir:
            raise ValueError("persistent_queue requires state_dir")
        self.queue_dir = Path(str(config.get("queue_dir") or self.state_dir / "queue")).expanduser()
        self.result_dir = Path(str(config.get("result_dir") or self.state_dir / "results")).expanduser()
        self.ready_file = Path(str(config.get("ready_file") or self.state_dir / "ready.json")).expanduser()
        self.timeout_s = float(config.get("timeout_s", config.get("timeout_sec", 240)) or 240)
        self.poll_s = float(config.get("poll_s", config.get("poll_interval_s", 0.02)) or 0.02)
        self.ensure_command = [str(item) for item in config.get("ensure_command", [])] if isinstance(config.get("ensure_command"), list) else []
        self.stop_command = [str(item) for item in config.get("stop_command", [])] if isinstance(config.get("stop_command"), list) else []
        self.startup_settle_s = float(config.get("startup_settle_s", config.get("startup_settle_sec", 0.0)) or 0.0)
        self.warmup_requests = config.get("warmup_requests", [])
        if not isinstance(self.warmup_requests, list):
            self.warmup_requests = []
        self.warmup_timeout_s = float(config.get("warmup_timeout_s", config.get("warmup_timeout_sec", self.timeout_s)) or self.timeout_s)
        self.path_replacements = _path_replacements_from_config(config)
        self.warmup_record_file = Path(
            str(config.get("warmup_record_file") or self.state_dir / "warmup_records.json")
        ).expanduser()
        self.environment = {
            str(key): str(value)
            for key, value in (config.get("environment") or {}).items()
        } if isinstance(config.get("environment"), dict) else {}
        self._ensured = False

    def render(
        self,
        *,
        capture_config: dict[str, Any],
        iteration: int,
        params_path: Path,
        iteration_dir: Path,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        self._ensure_ready()
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.result_dir.mkdir(parents=True, exist_ok=True)
        request_id = f"req_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns()}_{os.getpid()}_{iteration:04d}"
        request_path = self.queue_dir / f"{request_id}.request.json"
        result_path = self.result_dir / f"{request_id}.result.json"
        command_path = iteration_dir / "persistent_request_command.json"
        command = _build_capture_request(capture_config, params_path, params)
        queue_cfg = capture_config.get("persistent_queue") if isinstance(capture_config.get("persistent_queue"), dict) else {}
        cap_port = int(queue_cfg.get("cap_port", queue_cfg.get("capPort", self.environment.get("CAP_PORT", 8787))) or 8787)
        server_base_url = str(queue_cfg.get("server_base_url") or f"http://127.0.0.1:{cap_port}")
        command.setdefault("views", _default_views())
        command.setdefault("camera_name", "Capture Camera")
        command.setdefault("target_name", str(capture_config.get("target_name") or "model"))
        command.setdefault("width", int(queue_cfg.get("width", self.environment.get("CAP_WIDTH", 320)) or 320))
        command.setdefault("height", int(queue_cfg.get("height", self.environment.get("CAP_HEIGHT", 240)) or 240))
        command.setdefault("use_orthographic", True)
        command.setdefault("orthographic_vertical_size", 8.0)
        command.setdefault("capture_mode", "rotate_target")
        command.setdefault("distance_scale", 2.2)
        command.setdefault("min_distance", 1.0)
        command.setdefault("yaw_offset", 0.0)
        command.setdefault("pitch_offset", 0.0)
        command.setdefault("target_yaw_sign", -1.0)
        command.setdefault("target_pitch_sign", -1.0)
        command.setdefault("transparent_background", True)
        command.setdefault("zero_transparent_rgb", True)
        command.setdefault("alpha_from_rgb", True)
        command.setdefault("alpha_from_rgb_threshold", 1.0)
        command.setdefault("alpha_source", str(queue_cfg.get("alpha_source") or self.environment.get("CAP_ALPHA_SOURCE", "render_alpha")))
        command.setdefault("mask_alpha_mode", "binary")
        command.setdefault("mask_alpha_threshold", 1.0)
        command.setdefault("flip_y", False)
        command.setdefault("render_texture_srgb", True)
        command.setdefault("freeze_animators", _bool_config(queue_cfg.get("freeze_animators"), True))
        command.setdefault(
            "restore_animators_after_capture",
            _bool_config(queue_cfg.get("restore_animators_after_capture"), False),
        )
        command.setdefault("freeze_scene_scripts", _bool_config(queue_cfg.get("freeze_scene_scripts"), True))
        command.setdefault(
            "restore_scene_scripts_after_capture",
            _bool_config(queue_cfg.get("restore_scene_scripts_after_capture"), False),
        )
        command.setdefault("preserve_target_base_rotation", _bool_config(queue_cfg.get("preserve_target_base_rotation"), False))
        command.setdefault("target_base_roll", float(queue_cfg.get("target_base_roll", 0.0) or 0.0))
        if "fixed_animation_state" not in command:
            fixed_state = queue_cfg.get("fixed_animation_state")
            if fixed_state:
                command["fixed_animation_state"] = str(fixed_state)
        command.setdefault("fixed_animation_layer", int(queue_cfg.get("fixed_animation_layer", 0) or 0))
        command.setdefault("fixed_animation_time", float(queue_cfg.get("fixed_animation_time", 0.0) or 0.0))
        if "settle_frames" in queue_cfg:
            command.setdefault("settle_frames", max(0, int(queue_cfg["settle_frames"])))
        animation_settle_frames = queue_cfg.get("animation_freeze_settle_frames")
        command.setdefault(
            "animation_freeze_settle_frames",
            3 if animation_settle_frames is None else max(0, int(animation_settle_frames)),
        )
        command.setdefault("render_backend", "draw_scene")
        if "visual_quality_guard" not in command:
            guard_cfg = queue_cfg.get("visual_quality_guard")
            command["visual_quality_guard"] = copy.deepcopy(guard_cfg) if isinstance(guard_cfg, dict) else default_visual_quality_guard()
        command["nonce"] = f"persistent_{request_id}_{int(time.time() * 1000) % 1000000:06d}"
        command["server_base_url"] = server_base_url
        command["post_url"] = f"{server_base_url}/material-fit/capture-result"
        command["output_dir"] = str(iteration_dir)
        command["material_patch"] = _candidate_material_patch(
            command.get("material_patch"),
            target_name=str(command.get("target_name") or "model"),
            params=params,
        )
        command = _with_reference_image_urls(command, server_base_url)
        request = {"request_id": request_id, "params_path": str(params_path), "command": command}
        command_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path = request_path.with_suffix(request_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(request_path)

        deadline = time.monotonic() + self.timeout_s
        while not result_path.exists() or result_path.stat().st_size == 0:
            if time.monotonic() >= deadline:
                return {
                    "status": "failed",
                    "returncode": 4,
                    "stderr": f"timeout waiting for persistent render result {result_path}",
                    "params_path": str(params_path),
                    "screenshots": _capture_files(iteration_dir),
                    "candidate_overrides": _build_candidate_overrides(_capture_files(iteration_dir)),
                }
            time.sleep(self.poll_s)
        shutil.copy2(result_path, iteration_dir / "persistent_render_result.json")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        screenshots = _capture_files(iteration_dir)
        expected_capture_count = len(command.get("views", []))
        browser_score = _browser_score_payload(result)
        browser_score_ok = _browser_score_enabled(command) and browser_score is not None
        status = "ok" if result.get("ok") and (browser_score_ok or len(screenshots) == expected_capture_count) else "failed"
        return {
            "status": status,
            "returncode": 0 if status == "ok" else 1,
            "stdout": json.dumps(
                {
                    "ok": result.get("ok"),
                    "total_ms": result.get("total_ms"),
                    "browser_capture_ms": result.get("browser_capture_ms"),
                    "png_count": len(screenshots),
                    "browser_score": browser_score,
                    "output_dir": str(iteration_dir),
                },
                ensure_ascii=False,
            ),
            "stderr": "" if status == "ok" else str(result.get("error") or ""),
            "params_path": str(params_path),
            "screenshots": screenshots,
            "candidate_overrides": _build_candidate_overrides(screenshots),
            "persistent_result": result,
        }

    def _ensure_ready(self) -> None:
        if self._ensured:
            return
        if self.ensure_command:
            env = os.environ.copy()
            env.update(self.environment)
            capture_ensure_output = _bool_config(self.config.get("capture_ensure_output"), False)
            run_kwargs: dict[str, Any] = {
                "check": False,
                "text": True,
                "encoding": "utf-8",
                "env": env,
            }
            if capture_ensure_output:
                run_kwargs["capture_output"] = True
            else:
                run_kwargs["stdout"] = subprocess.DEVNULL
                run_kwargs["stderr"] = subprocess.DEVNULL
            completed = subprocess.run(
                self.ensure_command,
                **run_kwargs,
            )
            if completed.returncode != 0:
                stdout = completed.stdout if capture_ensure_output else "<not captured>"
                stderr = completed.stderr if capture_ensure_output else "<not captured>"
                raise RuntimeError(
                    "persistent queue ensure_command failed "
                    f"returncode={completed.returncode}\nstdout={stdout}\nstderr={stderr}"
                )
        if not self.ready_file.exists() or self.ready_file.stat().st_size == 0:
            raise RuntimeError(f"persistent queue is not ready: {self.ready_file}")
        if self.startup_settle_s > 0:
            time.sleep(self.startup_settle_s)
        self._run_warmup_requests()
        self._ensured = True

    def reset(self) -> bool:
        stop_command = self.stop_command or self._sibling_stop_command()
        if stop_command:
            env = os.environ.copy()
            env.update(self.environment)
            env.setdefault("MATERIAL_FIT_PERSISTENT_STATE_DIR", str(self.state_dir))
            env.setdefault("MATERIAL_FIT_PERSISTENT_LOG_DIR", str(self.state_dir / "logs"))
            completed = subprocess.run(
                stop_command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    "persistent queue stop_command failed "
                    f"returncode={completed.returncode}\nstdout={completed.stdout}\nstderr={completed.stderr}"
                )
            self._ensured = False
            return True
        self._ensured = False
        return False

    def _sibling_stop_command(self) -> list[str]:
        if not self.ensure_command:
            return []
        ensure_path = Path(self.ensure_command[0])
        if ensure_path.name != "ensure_persistent_multiview_daemon.sh":
            return []
        stop_path = ensure_path.with_name("stop_persistent_multiview_daemon.sh")
        if not stop_path.exists():
            return []
        return [str(stop_path)]

    def _server_base_url(self) -> str:
        cap_port = int(self.config.get("cap_port", self.environment.get("CAP_PORT", 8787)) or 8787)
        return str(self.config.get("server_base_url") or f"http://127.0.0.1:{cap_port}")

    def _run_warmup_requests(self) -> None:
        if not self.warmup_requests:
            return

        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.result_dir.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, Any]] = []
        for index, raw in enumerate(self.warmup_requests):
            request_id, request = self._build_warmup_request(raw, index)
            result = self._enqueue_request(request_id=request_id, request=request, timeout_s=self.warmup_timeout_s)
            if not result.get("ok"):
                raise RuntimeError(
                    "persistent queue warmup request failed "
                    f"request_id={request_id} error={result.get('error') or result}"
                )
            records.append(
                {
                    "request_id": request_id,
                    "source_path": request.get("_warmup_source_path"),
                    "output_dir": request.get("command", {}).get("output_dir"),
                    "result": result,
                }
            )

        self.warmup_record_file.parent.mkdir(parents=True, exist_ok=True)
        self.warmup_record_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_warmup_request(self, raw: Any, index: int) -> tuple[str, dict[str, Any]]:
        if isinstance(raw, (str, Path)):
            entry: dict[str, Any] = {"source_path": str(raw)}
        elif isinstance(raw, dict):
            entry = copy.deepcopy(raw)
        else:
            raise ValueError(f"persistent_queue warmup_requests[{index}] must be a path or object")

        source_text = entry.get("source_path") or entry.get("request_path") or entry.get("path")
        if not source_text:
            raise ValueError(f"persistent_queue warmup_requests[{index}] requires source_path")
        source_path = Path(str(source_text)).expanduser()
        if not source_path.exists():
            raise FileNotFoundError(f"persistent queue warmup source does not exist: {source_path}")
        request = json.loads(source_path.read_text(encoding="utf-8"))
        request = _rewrite_string_paths(request, [*self.path_replacements, *_path_replacements_from_config(entry)])
        if not isinstance(request, dict) or not isinstance(request.get("command"), dict):
            raise ValueError(f"persistent queue warmup source is not a queue request: {source_path}")

        label = str(entry.get("label") or source_path.parent.name or f"warmup_{index:02d}")
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") or f"warmup_{index:02d}"
        request_id = str(entry.get("request_id") or f"warmup_{index:02d}_{safe_label}_{time.time_ns()}_{os.getpid()}")
        request["request_id"] = request_id
        request["_warmup_source_path"] = str(source_path)

        if entry.get("params_path"):
            request["params_path"] = str(entry["params_path"])
        elif request.get("params_path"):
            request["params_path"] = str(request["params_path"])

        command = request["command"]
        if entry.get("params_path"):
            command["paramsPath"] = str(entry["params_path"])
        elif command.get("paramsPath"):
            command["paramsPath"] = str(command["paramsPath"])

        output_dir = Path(str(entry.get("output_dir") or self.state_dir / "warmup" / safe_label)).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        server_base_url = self._server_base_url()
        command["output_dir"] = str(output_dir)
        command["server_base_url"] = server_base_url
        command["post_url"] = f"{server_base_url}/material-fit/capture-result"
        command["nonce"] = str(entry.get("nonce") or f"persistent_{request_id}_{int(time.time() * 1000) % 1000000:06d}")
        request["command"] = command
        return request_id, request

    def _enqueue_request(self, *, request_id: str, request: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        if self.config.get("stop_file"):
            stop_file = Path(str(self.config["stop_file"])).expanduser()
        else:
            stop_file = self.state_dir / "stop"
        if stop_file.exists():
            raise RuntimeError(f"persistent queue stop file exists before enqueue: {stop_file}")
        request_path = self.queue_dir / f"{request_id}.request.json"
        result_path = self.result_dir / f"{request_id}.result.json"
        result_path.unlink(missing_ok=True)
        tmp_path = request_path.with_suffix(request_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(request_path)

        deadline = time.monotonic() + timeout_s
        while not result_path.exists() or result_path.stat().st_size == 0:
            if stop_file.exists():
                raise RuntimeError(f"persistent queue stopped while waiting for result {result_path}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timeout waiting for persistent warmup result {result_path}")
            time.sleep(self.poll_s)
        return json.loads(result_path.read_text(encoding="utf-8"))


def _default_views() -> list[dict[str, Any]]:
    return [
        {
            "view_id": f"v{index:03d}_yaw{yaw}_pitch0",
            "yaw": float(yaw),
            "pitch": 0.0,
            "file_name": f"laya_v{index:03d}_yaw{yaw}_pitch0.png",
        }
        for index, yaw in enumerate(range(0, 360, 45))
    ]


def _build_capture_request(capture_config: dict[str, Any], params_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    internal_keys = {"command", "runtime_bridge", "workers", "persistent_queue", "oracle_stabilization"}
    request = {
        key: copy.deepcopy(value)
        for key, value in capture_config.items()
        if key not in internal_keys
    }
    request["paramsPath"] = str(params_path)
    raw_score_override = params.get(BROWSER_SCORE_OVERRIDE_PARAM)
    if isinstance(raw_score_override, dict):
        browser_score = request.get("browser_score")
        if isinstance(browser_score, dict):
            score_override = {
                key: copy.deepcopy(raw_score_override[key])
                for key in (
                    "metric",
                    "readback_width",
                    "readback_height",
                    "render_width",
                    "render_height",
                )
                if key in raw_score_override
            }
            browser_score.update(score_override)
    request["material_patch"] = _candidate_material_patch(
        request.get("material_patch"),
        target_name=str(capture_config.get("target_name") or ""),
        params=params,
    )
    return request


def _candidate_material_patch(
    template: Any,
    *,
    target_name: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    patch = copy.deepcopy(template) if isinstance(template, dict) else {}
    continuous_params, discrete_candidate = split_discrete_candidate(params)
    patch = merge_candidate_into_material_patch(patch, discrete_candidate)
    patch["target_name"] = str(patch.get("target_name") or target_name)
    patch["values"] = continuous_params
    return patch


def _bool_config(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
        return default
    return bool(value)


def _browser_score_enabled(command: dict[str, Any]) -> bool:
    browser_score = command.get("browser_score")
    return isinstance(browser_score, dict) and bool(browser_score.get("enabled"))


def _browser_score_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    browser_score = result.get("browser_score") if isinstance(result, dict) else None
    if not isinstance(browser_score, dict):
        return None
    if browser_score.get("fit_score") is None and browser_score.get("score") is None:
        return None
    return browser_score


def _read_optional_persistent_result(iteration_dir: Path) -> dict[str, Any] | None:
    result_path = iteration_dir / "persistent_render_result.json"
    if not result_path.exists() or result_path.stat().st_size == 0:
        return None
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"failed to read persistent_render_result.json: {exc}"}
    return result if isinstance(result, dict) else {"ok": False, "error": "persistent_render_result.json is not an object"}


def _with_reference_image_urls(command: dict[str, Any], base_url: str) -> dict[str, Any]:
    browser_score = command.get("browser_score")
    if not isinstance(browser_score, dict):
        return command
    references = browser_score.get("reference_images")
    if not isinstance(references, list):
        return command
    command = dict(command)
    score_cfg = dict(browser_score)
    rewritten: list[Any] = []
    for raw in references:
        if not isinstance(raw, dict):
            rewritten.append(raw)
            continue
        entry = copy.deepcopy(raw)
        if not entry.get("url") and entry.get("path"):
            entry["url"] = f"{base_url}/material-fit/reference-image?path={quote(str(entry['path']), safe='')}"
        if not entry.get("confidence_mask_url") and entry.get("confidence_mask_path"):
            entry["confidence_mask_url"] = (
                f"{base_url}/material-fit/reference-image?"
                f"path={quote(str(entry['confidence_mask_path']), safe='')}"
            )
        rewritten.append(entry)
    score_cfg["reference_images"] = rewritten
    command["browser_score"] = score_cfg
    return command
