"""Run the shared Phase 0.5 recovery matrix across multiple Laya assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from material_fit.assets.material_phase05 import resolve_material_asset
from material_fit.experiments.material_phase05_recovery import OPTIMIZER_ID
from material_fit.laya import lmat_io
from material_fit.optimizer.material_recovery import PERTURBATION_PRESETS, perturb_material_params


DEFAULT_ASSETS = ("fish", "turtle")
DEFAULT_PRESETS = ("mild", "medium", "strong")
DEFAULT_SEEDS = (20260713, 20260714)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    assets = _split(args.assets)
    presets = _split(args.presets)
    seeds = _integers(args.seeds, "seeds")
    gpus = _integers(args.gpus, "gpus")
    unsupported = sorted(set(presets) - set(PERTURBATION_PRESETS))
    if unsupported:
        raise ValueError(f"unsupported perturbation presets: {unsupported}")
    if not assets or not presets or not seeds or not gpus:
        raise ValueError("assets, presets, seeds, and gpus must be non-empty")

    batch_name = args.batch_name or f"shared_phase05_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else repo_root / "artifacts"
    batch_dir = output_root / batch_name
    runs_dir = batch_dir / "runs"
    logs_dir = batch_dir / "logs"
    pids_dir = batch_dir / "owned_pids"
    for directory in (runs_dir, logs_dir, pids_dir):
        directory.mkdir(parents=True, exist_ok=True)

    matrix = _matrix(assets, presets, seeds)
    plan = _build_plan(repo_root, matrix)
    plan.update(
        {
            "batch_name": batch_name,
            "iterations": args.iterations,
            "target_score": args.target_score,
            "success_score": args.success_score,
            "speed_gate_ms": args.speed_gate_ms,
            "gpus": gpus,
            "max_parallel": min(args.max_parallel, len(gpus), len(matrix)),
            "resume_existing": bool(args.resume),
            "max_attempts": max(1, args.max_attempts),
            "batch_dir": str(batch_dir),
        }
    )
    _write_json(batch_dir / "multistart_plan.json", plan)
    if not plan["all_start_hashes_unique_per_asset"]:
        raise RuntimeError("planned starts are not unique within each asset")
    if args.plan_only:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    started = time.perf_counter()
    launch_rows = _run_matrix(
        repo_root=repo_root,
        runs_dir=runs_dir,
        logs_dir=logs_dir,
        pids_dir=pids_dir,
        matrix=matrix,
        gpus=gpus,
        max_parallel=min(args.max_parallel, len(gpus), len(matrix)),
        iterations=args.iterations,
        target_score=args.target_score,
        success_score=args.success_score,
        speed_gate_ms=args.speed_gate_ms,
        max_runtime_sec=args.max_runtime_sec,
        node_modules=args.node_modules,
        engine_libs=args.engine_libs,
        resume_existing=args.resume,
        max_attempts=max(1, args.max_attempts),
    )
    _write_json(batch_dir / "launcher_results.json", launch_rows)
    report = _build_report(
        batch_dir=batch_dir,
        matrix=matrix,
        plan=plan,
        launch_rows=launch_rows,
        wall_elapsed_s=time.perf_counter() - started,
    )
    _write_json(batch_dir / "shared_phase05_multistart_report.json", report)
    _write_markdown(batch_dir / "shared_phase05_multistart_report.md", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["accepted"] else 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", default=",".join(DEFAULT_ASSETS))
    parser.add_argument("--presets", default=",".join(DEFAULT_PRESETS))
    parser.add_argument("--seeds", default=",".join(str(value) for value in DEFAULT_SEEDS))
    parser.add_argument("--iterations", type=int, default=600)
    parser.add_argument("--target-score", type=float, default=0.995)
    parser.add_argument("--success-score", type=float, default=0.98)
    parser.add_argument("--speed-gate-ms", type=float, default=500.0)
    parser.add_argument("--max-runtime-sec", type=float, default=900.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-parallel", type=int, default=3)
    parser.add_argument("--gpus", default="0,1,2")
    parser.add_argument("--node-modules", default="")
    parser.add_argument("--engine-libs", default="")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--batch-name", default="")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse complete accepted run reports in an existing batch directory.",
    )
    return parser.parse_args(argv)


def _matrix(assets: list[str], presets: list[str], seeds: list[int]) -> list[dict[str, Any]]:
    return [
        {
            "asset": asset,
            "preset": preset,
            "seed": seed,
            "run_name": f"{asset}_{preset}_seed{seed}",
        }
        for asset in assets
        for preset in presets
        for seed in seeds
    ]


def _build_plan(repo_root: Path, matrix: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    target_cache: dict[str, tuple[str, dict[str, Any]]] = {}
    for spec in matrix:
        asset_name = str(spec["asset"])
        if asset_name not in target_cache:
            asset = resolve_material_asset(repo_root, asset_name)
            target = lmat_io.extract_params(lmat_io.load_lmat(asset.target_material_path))
            target_cache[asset_name] = (_sha256(asset.target_material_path), target)
        target_hash, target_params = target_cache[asset_name]
        start_params, perturbation = perturb_material_params(
            target_params,
            preset=str(spec["preset"]),
            seed=int(spec["seed"]),
        )
        rows.append(
            {
                **spec,
                "target_material_sha256": target_hash,
                "planned_start_params_sha256": _payload_sha256(start_params),
                "changed_coordinate_count": perturbation["changed_coordinate_count"],
                "scene_alignment_perturbed": perturbation["scene_alignment_perturbed"],
            }
        )
    unique_by_asset = {
        asset: len(values) == len(set(values))
        for asset in sorted({str(row["asset"]) for row in rows})
        for values in [[
            str(row["planned_start_params_sha256"])
            for row in rows
            if row["asset"] == asset
        ]]
    }
    return {
        "contract": "shared_material_phase05_multistart_plan_v1",
        "matrix_size": len(rows),
        "asset_count": len(unique_by_asset),
        "unique_start_hashes_by_asset": unique_by_asset,
        "all_start_hashes_unique_per_asset": all(unique_by_asset.values()),
        "runs": rows,
    }


def _run_matrix(
    *,
    repo_root: Path,
    runs_dir: Path,
    logs_dir: Path,
    pids_dir: Path,
    matrix: list[dict[str, Any]],
    gpus: list[int],
    max_parallel: int,
    iterations: int,
    target_score: float,
    success_score: float,
    speed_gate_ms: float,
    max_runtime_sec: float,
    node_modules: str,
    engine_libs: str,
    resume_existing: bool = False,
    max_attempts: int = 3,
) -> list[dict[str, Any]]:
    active: dict[str, subprocess.Popen[str]] = {}
    lock = threading.Lock()
    stop_event = threading.Event()
    gpu_pool: queue.Queue[int] = queue.Queue()
    for gpu in gpus:
        gpu_pool.put(gpu)

    def terminate_all() -> None:
        with lock:
            processes = list(active.values())
        for process in processes:
            _terminate(process)

    previous: dict[signal.Signals, Any] = {}

    def handle(signum: int, _frame: Any) -> None:
        stop_event.set()
        terminate_all()
        raise KeyboardInterrupt(f"received signal {signum}")

    if threading.current_thread() is threading.main_thread():
        for item in (signal.SIGINT, signal.SIGTERM):
            previous[item] = signal.getsignal(item)
            signal.signal(item, handle)

    def launch(spec: dict[str, Any]) -> dict[str, Any]:
        run_name = str(spec["run_name"])
        if stop_event.is_set():
            return {**spec, "returncode": 143, "run_dir": str(runs_dir / run_name)}
        gpu = gpu_pool.get()
        try:
            if stop_event.is_set():
                return {
                    **spec,
                    "gpu": gpu,
                    "returncode": 143,
                    "run_dir": str(runs_dir / run_name),
                }
            base_log_path = logs_dir / f"{run_name}.log"
            pid_path = pids_dir / f"{run_name}.pid"
            command = [
                sys.executable,
                "-m",
                "material_fit.experiments.material_phase05_recovery",
                "--asset",
                str(spec["asset"]),
                "--output-root",
                str(runs_dir),
                "--run-name",
                run_name,
                "--perturbation-preset",
                str(spec["preset"]),
                "--seed",
                str(spec["seed"]),
                "--iterations",
                str(iterations),
                "--target-score",
                str(target_score),
                "--success-score",
                str(success_score),
                "--speed-gate-ms",
                str(speed_gate_ms),
                "--max-runtime-sec",
                str(max_runtime_sec),
            ]
            if node_modules:
                command.extend(("--node-modules", node_modules))
            if engine_libs:
                command.extend(("--engine-libs", engine_libs))
            env = os.environ.copy()
            env.update(
                {
                    "CUDA_VISIBLE_DEVICES": str(gpu),
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                }
            )
            kwargs: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
            }
            started = time.perf_counter()
            returncode = 143
            log_path = base_log_path
            attempts_used = 0
            for attempt in range(1, max(1, max_attempts) + 1):
                attempts_used = attempt
                if stop_event.is_set():
                    returncode = 143
                    break
                if attempt > 1:
                    shutil.rmtree(runs_dir / run_name, ignore_errors=True)
                    time.sleep(min(5.0, float(attempt)))
                log_path = (
                    base_log_path
                    if attempt == 1
                    else logs_dir / f"{run_name}.attempt{attempt}.log"
                )
                with log_path.open("w", encoding="utf-8") as log:
                    process = subprocess.Popen(
                        command,
                        cwd=repo_root,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        text=True,
                        **kwargs,
                    )
                    pid_path.write_text(f"{process.pid}\n", encoding="ascii")
                    with lock:
                        active[run_name] = process
                    try:
                        returncode = process.wait()
                    finally:
                        if process.poll() is None:
                            _terminate(process)
                        pid_path.unlink(missing_ok=True)
                        with lock:
                            active.pop(run_name, None)
                if returncode == 0 or stop_event.is_set():
                    break
                if not _is_transient_renderer_failure(log_path):
                    break
            return {
                **spec,
                "gpu": gpu,
                "returncode": int(returncode),
                "attempts": attempts_used,
                "elapsed_s": time.perf_counter() - started,
                "run_dir": str(runs_dir / run_name),
                "log_path": str(log_path),
            }
        finally:
            gpu_pool.put(gpu)

    pending: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for spec in matrix:
        run_name = str(spec["run_name"])
        run_dir = runs_dir / run_name
        if resume_existing and _is_resumable_run(run_dir):
            results.append(
                {
                    **spec,
                    "gpu": None,
                    "returncode": 0,
                    "elapsed_s": 0.0,
                    "run_dir": str(run_dir),
                    "log_path": str(logs_dir / f"{run_name}.log"),
                    "resumed": True,
                }
            )
        else:
            if resume_existing and run_dir.exists():
                shutil.rmtree(run_dir)
            pending.append(spec)

    executor = ThreadPoolExecutor(max_workers=max(1, max_parallel))
    futures: list[Future[dict[str, Any]]] = []
    try:
        for spec in pending:
            futures.append(executor.submit(launch, spec))
        for future in as_completed(futures):
            results.append(future.result())
    except BaseException:
        stop_event.set()
        terminate_all()
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    finally:
        for item, handler in previous.items():
            signal.signal(item, handler)
    order = {str(row["run_name"]): index for index, row in enumerate(matrix)}
    return sorted(results, key=lambda row: order[str(row["run_name"])])


def _is_resumable_run(run_dir: Path) -> bool:
    report_path = run_dir / "phase05_report.json"
    start_params_path = run_dir / "inputs" / "start_params.json"
    if not report_path.is_file() or not start_params_path.is_file():
        return False
    try:
        report = _read_json(report_path)
    except (OSError, ValueError, TypeError):
        return False
    return bool(
        report.get("contract") == "shared_material_phase05_recovery_v1"
        and report.get("accepted") is True
        and report.get("process_cleanup", {}).get("remaining_owned_pid_count") == 0
        and report.get("view_counts") == {"target": 8, "start": 8, "best": 8}
    )


def _is_transient_renderer_failure(log_path: Path) -> bool:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")[-131_072:]
    except OSError:
        return False
    markers = (
        "CONTEXT_LOST_WEBGL",
        "statefirst",
        "runtime renderer exited with",
        "Target page, context or browser has been closed",
    )
    return any(marker in text for marker in markers)


def _build_report(
    *,
    batch_dir: Path,
    matrix: list[dict[str, Any]],
    plan: dict[str, Any],
    launch_rows: list[dict[str, Any]],
    wall_elapsed_s: float,
) -> dict[str, Any]:
    launch_by_name = {str(row["run_name"]): row for row in launch_rows}
    plan_by_name = {str(row["run_name"]): row for row in plan["runs"]}
    rows: list[dict[str, Any]] = []
    for spec in matrix:
        name = str(spec["run_name"])
        launch = launch_by_name.get(name, {})
        report_path = Path(str(launch.get("run_dir") or "")) / "phase05_report.json"
        report = _read_json(report_path) if report_path.is_file() else {}
        actual_start = Path(str(launch.get("run_dir") or "")) / "inputs/start_params.json"
        actual_hash = _semantic_json_sha256(actual_start) if actual_start.is_file() else None
        row = {
            **spec,
            "returncode": launch.get("returncode"),
            "gpu": launch.get("gpu"),
            "resumed": launch.get("resumed") is True,
            "attempts": launch.get("attempts", 0 if launch.get("resumed") else 1),
            "run_dir": launch.get("run_dir"),
            "accepted": report.get("accepted") is True,
            "start_score": report.get("start_score"),
            "best_score": report.get("best_score"),
            "score_gain": report.get("score_gain"),
            "parameter_error_start": report.get("parameter_recovery", {}).get("start", {}).get("mean_normalized_abs_error"),
            "parameter_error_best": report.get("parameter_recovery", {}).get("best", {}).get("mean_normalized_abs_error"),
            "iteration_mean_ms": report.get("timing", {}).get("mean_ms"),
            "iteration_p95_ms": report.get("timing", {}).get("p95_ms"),
            "scorer_sanity_passed": report.get("scorer_sanity", {}).get("passed") is True,
            "parameter_recovery_improved": report.get("parameter_recovery", {}).get("improved") is True,
            "timing_gate_passed": report.get("timing", {}).get("gate_passed") is True,
            "process_cleanup_passed": (
                report.get("process_cleanup", {}).get("remaining_owned_pid_count") == 0
            ),
            "asset_contract_passed": report.get("asset_contract_passed") is True,
            "discrete_state_audit_passed": (
                report.get("discrete_state_audit_passed") is True
            ),
            "optimizer_input_boundary_passed": (
                report.get("optimizer_input_boundary_passed") is True
            ),
            "view_counts": report.get("view_counts", {}),
            "optimizer_contract": report.get("optimizer"),
            "optimizer_runtime_id": report.get("optimizer_runtime_id"),
            "planned_start_params_sha256": plan_by_name[name]["planned_start_params_sha256"],
            "actual_start_params_sha256": actual_hash,
            "start_hash_matches_plan": actual_hash == plan_by_name[name]["planned_start_params_sha256"],
            "contact_sheet": report.get("contact_sheet"),
        }
        row["passed"] = bool(
            row["returncode"] == 0
            and row["accepted"]
            and row["start_hash_matches_plan"]
            and row["scorer_sanity_passed"]
            and row["parameter_recovery_improved"]
            and row["timing_gate_passed"]
            and row["process_cleanup_passed"]
            and row["asset_contract_passed"]
            and row["discrete_state_audit_passed"]
            and row["optimizer_input_boundary_passed"]
            and row["view_counts"] == {"target": 8, "start": 8, "best": 8}
            and row["optimizer_contract"] == "structured_material_v1"
            and row["optimizer_runtime_id"] == OPTIMIZER_ID
        )
        rows.append(row)
    groups: dict[str, Any] = {}
    for asset in sorted({str(row["asset"]) for row in rows}):
        group = [row for row in rows if row["asset"] == asset]
        scores = [float(row["best_score"]) for row in group if isinstance(row["best_score"], (int, float))]
        groups[asset] = {
            "run_count": len(group),
            "passed_count": sum(bool(row["passed"]) for row in group),
            "accepted": all(bool(row["passed"]) for row in group),
            "best_score_min": min(scores) if scores else None,
            "best_score_mean": statistics.fmean(scores) if scores else None,
            "best_score_max": max(scores) if scores else None,
        }
    return {
        "contract": "shared_material_phase05_multistart_report_v1",
        "batch_dir": str(batch_dir),
        "accepted": bool(rows) and all(bool(row["passed"]) for row in rows),
        "run_count": len(rows),
        "passed_count": sum(bool(row["passed"]) for row in rows),
        "resumed_count": sum(bool(row["resumed"]) for row in rows),
        "wall_elapsed_s": wall_elapsed_s,
        "assets": groups,
        "runs": rows,
    }


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Shared Phase 0.5 Fish/Turtle Recovery",
        "",
        f"- Accepted: `{report['accepted']}`",
        f"- Passed: `{report['passed_count']}/{report['run_count']}`",
        f"- Wall seconds: `{report['wall_elapsed_s']:.3f}`",
        "",
        "| asset | preset | seed | start | best | param error start | param error best | mean ms | passed |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report["runs"]:
        values = [
            row["asset"],
            row["preset"],
            str(row["seed"]),
            _format(row["start_score"]),
            _format(row["best_score"]),
            _format(row["parameter_error_start"]),
            _format(row["parameter_error_best"]),
            _format(row["iteration_mean_ms"]),
            str(row["passed"]),
        ]
        lines.append("| " + " | ".join(values) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _terminate(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=8)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _integers(value: str, label: str) -> list[int]:
    try:
        return [int(item) for item in _split(value)]
    except ValueError as exc:
        raise ValueError(f"{label} must be comma-separated integers") from exc


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")).hexdigest()


def _semantic_json_sha256(path: Path) -> str:
    return _payload_sha256(_read_json(path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _format(value: Any) -> str:
    return f"{float(value):.6f}" if isinstance(value, (int, float)) else ""


if __name__ == "__main__":
    raise SystemExit(main())
