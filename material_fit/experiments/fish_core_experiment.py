"""Cross-platform runner for the repository fish material-fit experiments."""

from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from material_fit.assets.fish_scene import (
    FINETUNE_ASSET_SET_NAME,
    ZERO_ASSET_SET_NAME,
    FishSceneAssets,
    resolve_fish_scene_assets,
)


FISH_VIEWS = [
    {"view_id": "v000_yaw0_pitch0", "yaw": 0.0, "pitch": 0.0, "file_name": "laya_v000_yaw0_pitch0.png"},
    {"view_id": "v001_yaw45_pitch0", "yaw": 45.0, "pitch": 0.0, "file_name": "laya_v001_yaw45_pitch0.png"},
    {"view_id": "v002_yaw90_pitch0", "yaw": 90.0, "pitch": 0.0, "file_name": "laya_v002_yaw90_pitch0.png"},
    {"view_id": "v003_yaw135_pitch0", "yaw": 135.0, "pitch": 0.0, "file_name": "laya_v003_yaw135_pitch0.png"},
    {"view_id": "v004_yaw180_pitch0", "yaw": 180.0, "pitch": 0.0, "file_name": "laya_v004_yaw180_pitch0.png"},
    {"view_id": "v005_yaw225_pitch0", "yaw": 225.0, "pitch": 0.0, "file_name": "laya_v005_yaw225_pitch0.png"},
    {"view_id": "v006_yaw270_pitch0", "yaw": 270.0, "pitch": 0.0, "file_name": "laya_v006_yaw270_pitch0.png"},
    {"view_id": "v007_yaw315_pitch0", "yaw": 315.0, "pitch": 0.0, "file_name": "laya_v007_yaw315_pitch0.png"},
]

REQUIRED_LAYA_ENGINE_FILES = (
    "laya.core.js",
    "laya.webgl_2D.js",
    "laya.d3.js",
    "laya.webgl_3D.js",
)

CHROMIUM_UNSAFE_PORTS = {
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69,
    77, 79, 87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119,
    123, 135, 137, 139, 143, 161, 179, 389, 427, 465, 512, 513, 514, 515,
    526, 530, 531, 532, 540, 548, 554, 556, 563, 587, 601, 636, 989, 990,
    993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 5060, 5061, 6000, 6566,
    6665, 6666, 6667, 6668, 6669, 6697, 10080,
}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    mode = _normalize_mode(args.mode)
    run_tag = args.run_name or _default_run_name(mode)
    run_dir = (Path(args.output_root) if args.output_root else repo_root / "artifacts") / run_tag
    run_dir = run_dir.resolve()

    assets = resolve_fish_scene_assets(repo_root)
    oracle_base = _resolve_oracle_base(args.oracle_base)
    render_backend = _resolve_render_backend(str(args.render_backend), oracle_base=oracle_base)
    engine_root: Path | None = None
    if render_backend == "runtime":
        engine_root = _resolve_engine_root(args.engine_root)
        _require_laya_engine(engine_root)
        _ensure_playwright_chromium(repo_root)
    elif render_backend == "external" and not args.external_render_command:
        raise ValueError("--external-render-command is required when --render-backend external")

    cap_port = int(args.cap_port) if int(args.cap_port) > 0 else _find_free_port()
    http_port = int(args.http_port) if int(args.http_port) > 0 else _find_free_port(exclude={cap_port})
    run_dir.mkdir(parents=True, exist_ok=True)

    selected = _select_assets_for_mode(assets, mode, str(args.baseline))
    material_stem = str(selected["baseline_material_name"]).removesuffix(".lmat")
    material_suffix = "finetune" if mode == "material" else "zero_searchable"
    material_name = f"{material_stem}_{material_suffix}_working.lmat"
    working_material = run_dir / material_name
    shutil.copy2(selected["baseline_material_path"], working_material)

    config = _build_config(
        repo_root=repo_root,
        assets=assets,
        selected=selected,
        run_dir=run_dir,
        mode=mode,
        working_material=working_material,
        cap_port=cap_port,
        width=int(args.width),
        height=int(args.height),
        http_port=http_port,
        render_backend=render_backend,
        oracle_base=oracle_base,
        external_render_command=str(args.external_render_command or ""),
        optimizer=args.optimizer,
        target_score=float(args.target_score),
        search_param_space=str(args.search_param_space or ""),
        initial_params_override=str(args.initial_params_override or ""),
    )
    config_path = run_dir / "fit_config.json"
    _write_json(config_path, config)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["NODE_PATH"] = str((repo_root / "artifacts/real_laya_run/node_modules").resolve())

    queue_proc: subprocess.Popen[str] | None = None
    renderer_proc: subprocess.Popen[str] | None = None
    initial_params_render_dir: Path | None = None
    best_params_render_dir: Path | None = None
    raw_scene_render_dir: Path | None = None
    started = time.perf_counter()
    fit_returncode = 1
    try:
        if render_backend == "runtime":
            if engine_root is None:
                raise RuntimeError("runtime render backend requires a Laya engine root")
            queue_proc = _start_queue(repo_root=repo_root, run_dir=run_dir, cap_port=cap_port, env=env)
            renderer_proc = _start_renderer(
                repo_root=repo_root,
                run_dir=run_dir,
                cap_port=cap_port,
                width=int(args.width),
                height=int(args.height),
                engine_root=engine_root,
                selected=selected,
                env=env,
                headed=bool(args.headed),
            )
            raw_scene_render_dir = _render_raw_scene(run_dir=run_dir, config=config)
        fit_returncode = _run_fit(
            repo_root=repo_root,
            run_dir=run_dir,
            config_path=config_path,
            iterations=int(args.iterations),
            target_score=float(args.target_score),
            optimizer=args.optimizer,
            max_runtime_sec=float(args.max_runtime_sec),
            env=env,
        )
        if fit_returncode == 0 and render_backend == "runtime":
            best_params_render_dir = _render_best_params(run_dir=run_dir, config=config)
        elif fit_returncode == 0 and render_backend == "oracle":
            initial_params_render_dir = _render_oracle_params(
                run_dir=run_dir,
                config=config,
                params_path=run_dir / "output/initial_params.json",
                output_dir=run_dir / "output/initial_render_preview",
            )
            best_params_path = run_dir / "output" / "auto_adjust" / "best" / "params.json"
            if best_params_path.exists():
                best_params_render_dir = _render_oracle_params(
                    run_dir=run_dir,
                    config=config,
                    params_path=best_params_path,
                    output_dir=run_dir / "output/best_render",
                )
    finally:
        _terminate_process(renderer_proc)
        _terminate_process(queue_proc)

    elapsed_s = time.perf_counter() - started
    summary = _write_summary(
        run_dir=run_dir,
        platform_name=args.platform_name or platform.system().lower(),
        mode=mode,
        fit_returncode=fit_returncode,
        elapsed_s=elapsed_s,
        cap_port=cap_port,
        assets=assets,
        selected=selected,
        raw_scene_render_dir=raw_scene_render_dir if "raw_scene_render_dir" in locals() else None,
        initial_params_render_dir=initial_params_render_dir,
        best_params_render_dir=best_params_render_dir,
        render_backend=render_backend,
        http_port=http_port,
        oracle_base=oracle_base,
    )
    sheet_path = _write_contact_sheet(run_dir=run_dir, repo_root=repo_root, summary=summary)
    if sheet_path:
        summary["contact_sheet"] = str(sheet_path)
        _write_json(run_dir / "summary.json", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(fit_returncode)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a complete fish material-fit experiment.")
    parser.add_argument(
        "--mode",
        choices=("finetune", "material", "zero_start", "zero_searchable"),
        required=True,
        help="'finetune' starts from the real material; 'zero_searchable' zeros only searchable params.",
    )
    parser.add_argument("--iterations", type=int, default=120)
    parser.add_argument("--target-score", type=float, default=0.98)
    parser.add_argument("--optimizer", default="pattern16")
    parser.add_argument(
        "--search-param-space",
        default="",
        help="Optional optimizer search-space override, for example pattern16 with cold_start_hybrid.",
    )
    parser.add_argument(
        "--initial-params-override",
        default="",
        help="Optional params.json used as the optimizer initial point for two-stage handoff runs.",
    )
    parser.add_argument("--width", type=int, default=900)
    parser.add_argument("--height", type=int, default=700)
    parser.add_argument("--cap-port", type=int, default=0, help="0 selects an available local port.")
    parser.add_argument("--http-port", type=int, default=0, help="0 selects an available local HTTP port.")
    parser.add_argument(
        "--render-backend",
        choices=("auto", "runtime", "oracle", "external"),
        default="auto",
        help="runtime starts the local renderer; oracle reuses the persistent Laya daemon; external calls a renderer command.",
    )
    parser.add_argument("--oracle-base", default="", help="Path to material_fit_render_oracle on Linux servers.")
    parser.add_argument(
        "--external-render-command",
        default="",
        help="Renderer command used with --render-backend external; params.json and output_dir are appended.",
    )
    parser.add_argument("--engine-root", default="", help="Laya engine libs directory; defaults to LAYA_ENGINE_LIBS.")
    parser.add_argument("--output-root", default="", help="Parent directory for the run; defaults to <repo>/artifacts.")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--platform-name", default="", help="Override label written to summary.json.")
    parser.add_argument("--max-runtime-sec", type=float, default=0.0)
    parser.add_argument("--headed", action="store_true", help="Open a visible Chromium window for renderer debugging.")
    parser.add_argument(
        "--baseline",
        choices=("auto", "source"),
        default="auto",
        help=(
            "Baseline material/scene selection. auto/source use the original scene-bound fish_jxs_test material."
        ),
    )
    return parser.parse_args(argv)


def _normalize_mode(raw: str) -> str:
    value = raw.strip().lower()
    if value in {"finetune", "material"}:
        return "material"
    if value in {"zero_start", "zero_searchable"}:
        return "zero_searchable"
    raise ValueError(f"unsupported mode: {raw}")


def _default_run_name(mode: str) -> str:
    label = "finetune" if mode == "material" else "zero_searchable"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"core_{platform.system().lower()}_fish_{label}_{stamp}"


def _resolve_engine_root(raw: str) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    env_root = os.environ.get("LAYA_ENGINE_LIBS")
    if env_root:
        return Path(env_root).expanduser().resolve()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            return Path(local_app_data, "Programs", "LayaAirIDE", "resources", "engine", "libs").resolve()
    volcano_engine = Path(
        "/vepfs-mlp2/c20250508/lizikang/material_fit_render_oracle/tools/layaair/3.4.0/Resources/engine/libs"
    )
    if volcano_engine.exists():
        return volcano_engine.resolve()
    return Path("/opt/LayaAirIDE/resources/engine/libs").resolve()


def _resolve_oracle_base(raw: str) -> Path | None:
    candidates = []
    if raw:
        candidates.append(Path(raw).expanduser())
    env_base = os.environ.get("MATERIAL_FIT_REMOTE_BASE")
    if env_base:
        candidates.append(Path(env_base).expanduser())
    candidates.append(Path("/vepfs-mlp2/c20250508/lizikang/material_fit_render_oracle"))
    for candidate in candidates:
        base = candidate.resolve()
        if (base / "bin/ensure_persistent_multiview_daemon.sh").exists():
            return base
    return None


def _resolve_render_backend(raw: str, *, oracle_base: Path | None) -> str:
    value = raw.strip().lower()
    if value == "auto":
        return "runtime"
    if value == "oracle" and oracle_base is None:
        raise FileNotFoundError(
            "oracle render backend requested, but material_fit_render_oracle was not found. "
            "Set MATERIAL_FIT_REMOTE_BASE or pass --oracle-base."
        )
    return value


def _require_laya_engine(engine_root: Path) -> None:
    missing = [name for name in REQUIRED_LAYA_ENGINE_FILES if not (engine_root / name).exists()]
    if missing:
        joined = "\n".join(str(engine_root / name) for name in missing)
        raise FileNotFoundError(
            "Laya engine libs are incomplete. Set LAYA_ENGINE_LIBS or pass --engine-root.\n" + joined
        )


def _ensure_playwright_chromium(repo_root: Path) -> None:
    work_dir = repo_root / "artifacts/real_laya_run"
    node_modules = work_dir / "node_modules/playwright-chromium"
    if node_modules.exists():
        return
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    if not node or not npm:
        raise RuntimeError("Node.js 18+ and npm are required to install playwright-chromium.")
    work_dir.mkdir(parents=True, exist_ok=True)
    if not (work_dir / "package.json").exists():
        subprocess.run([npm, "init", "-y"], cwd=work_dir, check=True)
    subprocess.run([npm, "install", "playwright-chromium", "--no-save"], cwd=work_dir, check=True)


def _find_free_port(*, exclude: set[int] | None = None) -> int:
    excluded = set(exclude or set()) | CHROMIUM_UNSAFE_PORTS
    for _ in range(128):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        if port not in excluded:
            return port
    raise RuntimeError(f"could not find a free port outside {sorted(excluded)}")


def _select_assets_for_mode(assets: FishSceneAssets, mode: str, baseline: str = "auto") -> dict[str, Any]:
    if baseline not in {"auto", "source"}:
        raise ValueError(f"unsupported baseline: {baseline}")
    return {
        "asset_set_name": FINETUNE_ASSET_SET_NAME if mode == "material" else ZERO_ASSET_SET_NAME,
        "laya_project_dir": assets.source_laya_project_dir,
        "scene_path": assets.source_scene_path,
        "baseline_material_path": assets.source_material_path,
        "scene_material_uuid": assets.source_scene_material_uuid,
        "baseline_material_name": assets.source_scene_material_name,
    }


def _persistent_queue_config(
    *,
    run_dir: Path,
    cap_port: int,
    http_port: int,
    width: int,
    height: int,
    alpha_source: str,
    render_backend: str,
    oracle_base: Path | None,
) -> dict[str, Any]:
    state_dir = run_dir / ("oracle_persistent_queue" if render_backend == "oracle" else "persistent_queue")
    queue_cfg: dict[str, Any] = {
        "enabled": render_backend != "external",
        "state_dir": str(state_dir),
        "timeout_s": 180,
        "poll_s": 0.02,
        "cap_port": cap_port,
        "http_port": http_port,
        "width": width,
        "height": height,
        "alpha_source": alpha_source,
        "freeze_animators": True,
        "fixed_animation_state": "idle1",
        "fixed_animation_layer": 0,
        "fixed_animation_time": 0.0,
        "restore_animators_after_capture": False,
        "freeze_scene_scripts": True,
        "visual_quality_guard": {"enabled": False},
    }
    if render_backend != "oracle":
        return queue_cfg

    if oracle_base is None:
        raise ValueError("oracle_base is required for oracle render backend")
    log_dir = state_dir / "logs"
    env = {
        "MATERIAL_FIT_REMOTE_BASE": str(oracle_base),
        "MATERIAL_FIT_PERSISTENT_STATE_DIR": str(state_dir),
        "MATERIAL_FIT_PERSISTENT_LOG_DIR": str(log_dir),
        "MATERIAL_FIT_PERSISTENT_RESTART_ON_MISMATCH": os.environ.get(
            "MATERIAL_FIT_PERSISTENT_RESTART_ON_MISMATCH",
            "1",
        ),
        "MATERIAL_FIT_PERSISTENT_START_TIMEOUT_SEC": os.environ.get(
            "MATERIAL_FIT_PERSISTENT_START_TIMEOUT_SEC",
            "90",
        ),
        "HTTP_PORT": str(http_port),
        "CAP_PORT": str(cap_port),
        "CAP_WIDTH": str(width),
        "CAP_HEIGHT": str(height),
        "CAP_ALPHA_SOURCE": alpha_source,
    }
    queue_cfg.update(
        {
            "state_dir": str(state_dir),
            "queue_dir": str(state_dir / "queue"),
            "result_dir": str(state_dir / "results"),
            "ready_file": str(state_dir / "ready.json"),
            "ensure_command": [str(oracle_base / "bin/ensure_persistent_multiview_daemon.sh")],
            "stop_command": [str(oracle_base / "bin/stop_persistent_multiview_daemon.sh")],
            "capture_ensure_output": True,
            "startup_settle_s": 0.0,
            "environment": env,
        }
    )
    return queue_cfg


def _build_config(
    *,
    repo_root: Path,
    assets: FishSceneAssets,
    selected: dict[str, Any],
    run_dir: Path,
    mode: str,
    working_material: Path,
    cap_port: int,
    width: int,
    height: int,
    optimizer: str,
    target_score: float,
    http_port: int = 0,
    render_backend: str = "runtime",
    oracle_base: Path | None = None,
    external_render_command: str = "",
    search_param_space: str = "",
    initial_params_override: str = "",
) -> dict[str, Any]:
    refs_root = assets.unity_reference_dir
    reference_images = [
        {"view_id": view["view_id"], "path": str(refs_root / view["file_name"])}
        for view in FISH_VIEWS
    ]
    alpha_source = "silhouette_mask" if mode == "zero_searchable" else "render_alpha"
    browser_score_objective = (
        {"mode": "reference_foreground_mae", "foreground_threshold": 3.0}
        if mode == "zero_searchable"
        else {"mode": "mean"}
    )
    persistent_queue = _persistent_queue_config(
        run_dir=run_dir,
        cap_port=cap_port,
        http_port=http_port,
        width=width,
        height=height,
        alpha_source=alpha_source,
        render_backend=render_backend,
        oracle_base=oracle_base,
    )
    render_command = [external_render_command] if render_backend == "external" else []
    config: dict[str, Any] = {
        "case_name": run_dir.name,
        "asset_set": {
            "name": selected["asset_set_name"],
            "laya_project_dir": str(selected["laya_project_dir"]),
            "scene_path": str(selected["scene_path"]),
            "baseline_material_path": str(selected["baseline_material_path"]),
            "unity_reference_dir": str(assets.unity_reference_dir),
            "scene_material_uuid": selected["scene_material_uuid"],
            "source_laya_project_dir": str(assets.source_laya_project_dir),
            "source_scene_path": str(assets.source_scene_path),
            "source_scene_material_uuid": assets.source_scene_material_uuid,
            "source_scene_material_name": assets.source_scene_material_name,
            "baseline_material_name": selected["baseline_material_name"],
        },
        "laya_shader_path": str(assets.shader_path),
        "laya_material_path": str(working_material),
        "unity_shader_path": "",
        "unity_material_params_path": "",
        "image_pairs": [],
        "initial_params_mode": mode,
        "auto_adjust_target_score": target_score,
        "capture_screen_after_apply": False,
        "fit_score_mode": "research",
        "browser_score_context_render": {"enabled": True},
        "browser_score_objective": browser_score_objective,
        "analysis_performance": {
            "multiview_workers": "auto",
            "evaluation_batch_size": 1,
            "evaluation_workers": 1,
            "evaluation_parallel_safe": False,
            "full_rerank_top_k": 0,
            "best_full_validation": False,
            "target_full_validation": False,
            "snapshot_interval": 1,
            "research_metrics_profile": "tiered",
            "fast_score_only": True,
            "keep_last_n_artifacts": 8,
            "always_keep_best_artifact": True,
            "always_keep_first_artifact": True,
        },
        "optimizer": optimizer,
        "output_dir": str(run_dir / "output"),
        "external_backup_dir": str(run_dir / "external_backups"),
        "dry_run": False,
        "render_command": render_command,
        "render_backend": render_backend,
        "oracle_base": str(oracle_base) if oracle_base is not None else "",
        "laya_window": {"process_pattern": "", "title_pattern": "", "settle_ms": 0},
        "laya_editor_capture": {"enabled": False},
        "laya_capture": {
            "persistent_queue": persistent_queue,
            "browser_score": {
                "enabled": True,
                "metric": "browser_fast_rgba_mae_v1",
                "reference_images": reference_images,
                "rgb_weight": 0.85,
                "alpha_weight": 0.15,
            },
            "target_name": "model",
            "camera_name": "Capture Camera",
            "capture_mode": "rotate_target",
            "render_backend": "draw_scene",
            "return_images": True,
            "use_orthographic": True,
            "orthographic_vertical_size": 8.0,
            "distance_scale": 2.2,
            "min_distance": 1.0,
            "yaw_offset": 0.0,
            "pitch_offset": 0.0,
            "target_yaw_sign": -1.0,
            "target_pitch_sign": -1.0,
            "transparent_background": True,
            "zero_transparent_rgb": True,
            "alpha_from_rgb": True,
            "alpha_from_rgb_threshold": 1.0,
            "visual_background_color": [255, 255, 255, 255],
            "mask_alpha_mode": "binary",
            "mask_alpha_threshold": 1.0,
            "flip_y": False,
            "render_texture_srgb": True,
            "freeze_animators": True,
            "fixed_animation_state": "idle1",
            "fixed_animation_layer": 0,
            "fixed_animation_time": 0.0,
            "restore_animators_after_capture": False,
            "views": FISH_VIEWS,
        },
    }
    if search_param_space:
        config["search_param_space"] = search_param_space
    if initial_params_override:
        config["initial_params_override_path"] = initial_params_override
    return config


def _start_queue(*, repo_root: Path, run_dir: Path, cap_port: int, env: dict[str, str]) -> subprocess.Popen[str]:
    state_dir = run_dir / "persistent_queue"
    log_dir = state_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = (log_dir / "persistent_queue_stdout.log").open("w", encoding="utf-8")
    stderr = (log_dir / "persistent_queue_stderr.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "material_fit.laya_capture.persistent_queue_daemon",
            "--state-dir",
            str(state_dir),
            "--host",
            "127.0.0.1",
            "--port",
            str(cap_port),
            "--timeout-s",
            "120",
        ],
        cwd=repo_root,
        env=env,
        stdout=stdout,
        stderr=stderr,
        text=True,
    )
    _wait_for_file(state_dir / "ready.json", proc=proc, timeout_s=15, label="persistent queue")
    return proc


def _start_renderer(
    *,
    repo_root: Path,
    run_dir: Path,
    cap_port: int,
    width: int,
    height: int,
    engine_root: Path,
    selected: dict[str, Any],
    env: dict[str, str],
    headed: bool,
) -> subprocess.Popen[str]:
    log_dir = run_dir / "renderer_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ready_file = run_dir / "renderer_ready.json"
    stdout = (log_dir / "runtime_renderer_stdout.log").open("w", encoding="utf-8")
    stderr = (log_dir / "runtime_renderer_stderr.log").open("w", encoding="utf-8")
    args = [
        shutil.which("node") or "node",
        str(repo_root / "material_fit/laya_capture/run_runtime_renderer.js"),
        "--server",
        f"http://127.0.0.1:{cap_port}",
        "--width",
        str(width),
        "--height",
        str(height),
        "--engineRoot",
        str(engine_root),
        "--projectRoot",
        str(selected["laya_project_dir"]),
        "--scene",
        str(selected["scene_path"]),
        "--readyFile",
        str(ready_file),
        "--debugMaterial",
        "true",
    ]
    if headed:
        args.extend(["--headed", "true"])
    proc = subprocess.Popen(args, cwd=repo_root, env=env, stdout=stdout, stderr=stderr, text=True)
    _wait_for_file(ready_file, proc=proc, timeout_s=60, label="runtime renderer")
    return proc


def _run_fit(
    *,
    repo_root: Path,
    run_dir: Path,
    config_path: Path,
    iterations: int,
    target_score: float,
    optimizer: str,
    max_runtime_sec: float,
    env: dict[str, str],
) -> int:
    log_dir = run_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "fit_stdout.log"
    stderr_path = log_dir / "fit_stderr.log"
    cmd = [
        sys.executable,
        "-m",
        "material_fit.fit_material",
        "--config",
        str(config_path),
        "--auto-adjust",
        "--iterations",
        str(iterations),
        "--target-score",
        str(target_score),
        "--optimizer",
        optimizer,
        "--write-candidate-lmat",
        "--apply-lmat",
        "--fit-score-mode",
        "research",
    ]
    started = time.perf_counter()
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        try:
            completed = subprocess.run(
                cmd,
                cwd=repo_root,
                env=env,
                stdout=stdout,
                stderr=stderr,
                text=True,
                timeout=max_runtime_sec if max_runtime_sec > 0 else None,
            )
            return int(completed.returncode)
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - started
            stderr.write(f"\nfish_core_experiment timed out after {elapsed:.3f}s\n")
            return 124


def _render_raw_scene(*, run_dir: Path, config: dict[str, Any]) -> Path | None:
    capture_cfg = config.get("laya_capture") if isinstance(config.get("laya_capture"), dict) else {}
    queue_cfg = capture_cfg.get("persistent_queue") if isinstance(capture_cfg.get("persistent_queue"), dict) else {}
    state_dir = Path(str(queue_cfg.get("state_dir") or run_dir / "persistent_queue"))
    queue_dir = state_dir / "queue"
    result_dir = state_dir / "results"
    output_dir = run_dir / "raw_scene_render"
    request_id = f"raw_scene_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns()}"
    result_path = result_dir / f"{request_id}.result.json"
    command = _build_raw_scene_command(capture_cfg=capture_cfg, queue_cfg=queue_cfg, output_dir=output_dir)
    request = {"request_id": request_id, "command": command}
    queue_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    request_path = queue_dir / f"{request_id}.request.json"
    tmp_path = request_path.with_suffix(request_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(request_path)
    deadline = time.monotonic() + float(queue_cfg.get("timeout_s", 180) or 180)
    while time.monotonic() < deadline:
        if result_path.exists() and result_path.stat().st_size > 0:
            result = _read_queue_result_json(result_path)
            if result.get("ok"):
                return output_dir
            raise RuntimeError(f"raw scene render failed: {result.get('error') or result}")
        time.sleep(float(queue_cfg.get("poll_s", 0.02) or 0.02))
    raise TimeoutError(f"timed out waiting for raw scene render: {result_path}")


def _render_best_params(*, run_dir: Path, config: dict[str, Any]) -> Path | None:
    best_params_path = run_dir / "output" / "auto_adjust" / "best" / "params.json"
    best_params = _read_json_or_empty(best_params_path)
    if not best_params:
        return None

    capture_cfg = config.get("laya_capture") if isinstance(config.get("laya_capture"), dict) else {}
    queue_cfg = capture_cfg.get("persistent_queue") if isinstance(capture_cfg.get("persistent_queue"), dict) else {}
    state_dir = Path(str(queue_cfg.get("state_dir") or run_dir / "persistent_queue"))
    queue_dir = state_dir / "queue"
    result_dir = state_dir / "results"
    output_dir = run_dir / "output" / "best_render"
    output_dir.mkdir(parents=True, exist_ok=True)

    params_path = output_dir / "params.json"
    _write_json(params_path, best_params)
    request_id = f"best_render_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns()}"
    result_path = result_dir / f"{request_id}.result.json"
    command = _build_raw_scene_command(capture_cfg=capture_cfg, queue_cfg=queue_cfg, output_dir=output_dir)
    command["paramsPath"] = str(params_path)
    command["material_patch"] = {
        "target_name": str(capture_cfg.get("target_name") or "model"),
        "values": copy.deepcopy(best_params),
    }
    command["nonce"] = request_id
    request = {"request_id": request_id, "params_path": str(params_path), "command": command}
    queue_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    request_path = queue_dir / f"{request_id}.request.json"
    tmp_path = request_path.with_suffix(request_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(request_path)

    deadline = time.monotonic() + float(queue_cfg.get("timeout_s", 180) or 180)
    while time.monotonic() < deadline:
        if result_path.exists() and result_path.stat().st_size > 0:
            result = _read_queue_result_json(result_path)
            (output_dir / "persistent_render_result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            expected = len(FISH_VIEWS)
            png_count = sum(1 for view in FISH_VIEWS if (output_dir / view["file_name"]).exists())
            if result.get("ok") and png_count == expected:
                return output_dir
            raise RuntimeError(f"best params render failed: {result.get('error') or result}")
        time.sleep(float(queue_cfg.get("poll_s", 0.02) or 0.02))
    raise TimeoutError(f"timed out waiting for best params render: {result_path}")


def _render_oracle_params(
    *,
    run_dir: Path,
    config: dict[str, Any],
    params_path: Path,
    output_dir: Path,
) -> Path | None:
    if not params_path.exists():
        return None
    capture_cfg = config.get("laya_capture") if isinstance(config.get("laya_capture"), dict) else {}
    queue_cfg = capture_cfg.get("persistent_queue") if isinstance(capture_cfg.get("persistent_queue"), dict) else {}
    env_cfg = queue_cfg.get("environment") if isinstance(queue_cfg.get("environment"), dict) else {}
    oracle_base = Path(str(env_cfg.get("MATERIAL_FIT_REMOTE_BASE") or config.get("oracle_base") or "")).expanduser()
    command = oracle_base / "bin/render_params_persistent.sh"
    if not command.exists():
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({str(key): str(value) for key, value in env_cfg.items()})
    env.setdefault("MATERIAL_FIT_PERSISTENT_AUTOSTART", "1")
    env.setdefault("MATERIAL_FIT_PERSISTENT_RESTART_ON_MISMATCH", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    completed = subprocess.run(
        [str(command), str(params_path), str(output_dir)],
        cwd=run_dir,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=float(queue_cfg.get("timeout_s", 180) or 180),
    )
    (output_dir / "render_params_persistent_stdout.log").write_text(completed.stdout, encoding="utf-8")
    (output_dir / "render_params_persistent_stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            "oracle preview render failed "
            f"returncode={completed.returncode}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return output_dir


def _read_queue_result_json(path: Path) -> dict[str, Any]:
    last_error: Exception | None = None
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error
    return json.loads(path.read_text(encoding="utf-8"))


def _build_raw_scene_command(
    *,
    capture_cfg: dict[str, Any],
    queue_cfg: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    command: dict[str, Any] = {
        key: copy.deepcopy(value)
        for key, value in capture_cfg.items()
        if key not in {"persistent_queue", "browser_score", "runtime_bridge", "workers"}
    }
    command.setdefault("views", copy.deepcopy(FISH_VIEWS))
    command.setdefault("camera_name", "Capture Camera")
    command.setdefault("target_name", "model")
    command.setdefault("capture_mode", "rotate_target")
    command.setdefault("render_backend", "draw_scene")
    command.setdefault("return_images", True)
    command.setdefault("use_orthographic", True)
    command.setdefault("orthographic_vertical_size", 8.0)
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
    command.setdefault("visual_background_color", [255, 255, 255, 255])
    command.setdefault("mask_alpha_mode", "binary")
    command.setdefault("mask_alpha_threshold", 1.0)
    command.setdefault("flip_y", False)
    command.setdefault("render_texture_srgb", True)
    command.setdefault("freeze_animators", bool(queue_cfg.get("freeze_animators", True)))
    command.setdefault("freeze_scene_scripts", bool(queue_cfg.get("freeze_scene_scripts", True)))
    command["width"] = int(queue_cfg.get("width", 900) or 900)
    command["height"] = int(queue_cfg.get("height", 700) or 700)
    command["alpha_source"] = str(queue_cfg.get("alpha_source") or "render_alpha")
    command["browser_score"] = {"enabled": False}
    command["output_dir"] = str(output_dir)
    command["nonce"] = f"raw_scene_{int(time.time() * 1000)}"
    command.pop("material_patch", None)
    return command


def _wait_for_file(path: Path, *, proc: subprocess.Popen[str], timeout_s: float, label: str) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return
        if proc.poll() is not None:
            raise RuntimeError(f"{label} exited before ready file was written: {path}")
        time.sleep(0.1)
    raise TimeoutError(f"timed out waiting for {label}: {path}")


def _terminate_process(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _write_summary(
    *,
    run_dir: Path,
    platform_name: str,
    mode: str,
    fit_returncode: int,
    elapsed_s: float,
    cap_port: int,
    assets: FishSceneAssets,
    selected: dict[str, Any],
    raw_scene_render_dir: Path | None,
    initial_params_render_dir: Path | None,
    best_params_render_dir: Path | None,
    render_backend: str,
    http_port: int,
    oracle_base: Path | None,
) -> dict[str, Any]:
    output_dir = run_dir / "output"
    state_path = output_dir / "auto_adjust/state.json"
    policy_path = output_dir / "optimizer_param_policy.json"
    state = _read_json_or_empty(state_path)
    policy = _read_json_or_empty(policy_path)
    history = state.get("history") if isinstance(state.get("history"), list) else []
    best_history_iter = _best_iteration(history)
    best_render_dir = _resolve_best_render_dir(
        output_dir=output_dir,
        fallback_iteration=best_history_iter,
        explicit_best_render_dir=best_params_render_dir,
    )
    best_render_iter = _iteration_from_render_dir(best_render_dir)
    summary = {
        "ok": fit_returncode == 0,
        "platform": platform_name,
        "mode": mode,
        "run_dir": str(run_dir),
        "config": str(run_dir / "fit_config.json"),
        "output_dir": str(output_dir),
        "fit_exit_code": fit_returncode,
        "elapsed_s": round(elapsed_s, 3),
        "render_backend": render_backend,
        "iterations_completed": state.get("iteration"),
        "best_fit_score": state.get("best_fit_score"),
        "best_diff_score": state.get("best_score"),
        "best_iteration": best_render_iter if best_render_iter is not None else best_history_iter,
        "best_history_iteration": best_history_iter,
        "initial_render_dir": str(initial_params_render_dir or output_dir / "iterations/iter_-001"),
        "raw_scene_render_dir": str(raw_scene_render_dir) if raw_scene_render_dir is not None else None,
        "best_render_dir": str(best_render_dir) if best_render_dir is not None else None,
        "cap_port": cap_port,
        "http_port": http_port,
        "oracle_base": str(oracle_base) if oracle_base is not None else None,
        "asset_set": selected["asset_set_name"],
        "laya_project_dir": str(selected["laya_project_dir"]),
        "scene_path": str(selected["scene_path"]),
        "baseline_material_path": str(selected["baseline_material_path"]),
        "unity_reference_dir": str(assets.unity_reference_dir),
        "scene_material_uuid": selected["scene_material_uuid"],
        "source_laya_project_dir": str(assets.source_laya_project_dir),
        "source_scene_path": str(assets.source_scene_path),
        "source_scene_material_uuid": assets.source_scene_material_uuid,
        "source_scene_material_name": assets.source_scene_material_name,
        "baseline_material_name": selected["baseline_material_name"],
        "searchable_param_count": policy.get("searchable_param_count"),
        "locked_param_count": policy.get("locked_param_count"),
        "initial_params_mode": policy.get("initial_params_mode"),
        "initial_params_override_path": policy.get("initial_params_override_path"),
        "summary_path": str(run_dir / "summary.json"),
    }
    _write_json(run_dir / "summary.json", summary)
    return summary


def _best_iteration(history: list[Any]) -> int | None:
    best: tuple[float, int] | None = None
    for record in history:
        if not isinstance(record, dict):
            continue
        score = record.get("fit_score_before")
        iteration = record.get("iteration")
        if not isinstance(score, (int, float)) or not isinstance(iteration, int):
            continue
        if best is None or float(score) > best[0]:
            best = (float(score), int(iteration))
    return best[1] if best is not None else None


def _resolve_best_render_dir(
    *,
    output_dir: Path,
    fallback_iteration: int | None,
    explicit_best_render_dir: Path | None = None,
) -> Path | None:
    if explicit_best_render_dir is not None and explicit_best_render_dir.exists():
        return explicit_best_render_dir

    best_params = _read_json_or_empty(output_dir / "auto_adjust/best/params.json")
    initial_params = _read_json_or_empty(output_dir / "initial_params.json")
    initial_dir = output_dir / "iterations/iter_-001"
    if best_params and initial_params and best_params == initial_params and initial_dir.exists():
        return initial_dir

    iterations_dir = output_dir / "iterations"
    if best_params and iterations_dir.exists():
        for params_path in sorted(iterations_dir.glob("iter_*/params.json")):
            if _read_json_or_empty(params_path) == best_params:
                return params_path.parent

    if fallback_iteration is not None:
        fallback = output_dir / "iterations" / f"iter_{fallback_iteration:04d}"
        if fallback.exists() and best_params and _read_json_or_empty(fallback / "params.json") == best_params:
            return fallback
    return None


def _iteration_from_render_dir(render_dir: Path | None) -> int | None:
    if render_dir is None:
        return None
    name = render_dir.name
    if not name.startswith("iter_"):
        return None
    try:
        return int(name.removeprefix("iter_"))
    except ValueError:
        return None


def _write_contact_sheet(*, run_dir: Path, repo_root: Path, summary: dict[str, Any]) -> Path | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    mode = str(summary.get("mode") or "")
    if summary.get("initial_params_override_path"):
        start_label = "Handoff start"
    else:
        start_label = "Zero-searchable start" if mode == "zero_searchable" else "Material start"
    unity_reference_dir = Path(str(summary.get("unity_reference_dir") or ""))
    columns = [
        ("Unity reference", [unity_reference_dir / view["file_name"] for view in FISH_VIEWS]),
    ]
    columns.append((start_label, [Path(str(summary["initial_render_dir"])) / view["file_name"] for view in FISH_VIEWS]))
    best_dir = summary.get("best_render_dir")
    if best_dir:
        columns.append(("Best render", [Path(str(best_dir)) / view["file_name"] for view in FISH_VIEWS]))
    if any(not path.exists() for _, paths in columns for path in paths):
        return None

    cell_w, cell_h = 320, 240
    label_h = 40
    gutter = 12
    sheet_w = len(columns) * cell_w + (len(columns) + 1) * gutter
    sheet_h = len(FISH_VIEWS) * (cell_h + label_h) + gutter
    sheet = Image.new("RGB", (sheet_w, sheet_h), (242, 244, 247))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()

    for col_index, (label, paths) in enumerate(columns):
        x = gutter + col_index * (cell_w + gutter)
        for row_index, path in enumerate(paths):
            y = gutter + row_index * (cell_h + label_h)
            view_id = FISH_VIEWS[row_index]["view_id"]
            draw.text((x, y), f"{label} | {view_id}", fill=(20, 24, 31), font=font)
            with Image.open(path) as source:
                image = _image_on_background(source, (255, 255, 255))
                image.thumbnail((cell_w, cell_h))
                px = x + (cell_w - image.width) // 2
                py = y + label_h + (cell_h - image.height) // 2
                sheet.paste(image, (px, py))

    out = run_dir / "fish_contact_sheet.png"
    sheet.save(out)
    return out


def _image_on_background(image: Any, color: tuple[int, int, int]) -> Any:
    from PIL import Image

    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (*color, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _read_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
