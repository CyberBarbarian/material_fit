"""Benchmark: warm-started CMA-ES vs vanilla CMA-ES vs random search.

This is the §7.1-Day-3 "minimal experiment" from
``tools/material_fit/docs/RelatedWork_Survey.md``. It validates the
*method* claim — that heuristic warm-start meaningfully accelerates
CMA-ES on a problem whose structure mirrors our real cross-engine
material fitting setting — *without* having to run a real Laya
screenshot loop.

Why a synthetic objective?

    Our true objective is :math:`\\mathcal{L}(\\theta) = \\| R_{Laya}(\\theta)
    - I_{Unity} \\|`. Computing :math:`R_{Laya}` from one parameter
    set takes ~30s of Editor + screenshot + diff_analysis pipeline,
    so 200 evaluations × 4 algorithms × 5 seeds = 4000 evaluations =
    33 hours. We can't afford that on a feasibility study, and even
    if we could, the wall-clock cost would dwarf the algorithm-level
    signal we are looking for. Phase-1 §7.1-Day-3 is explicitly
    scoped to "verify in <0.5 day that the cmaes library + WS-MGD
    do what they advertise", which is exactly what a synthetic
    objective with the right *structure* lets us do.

Synthetic objective design (see :func:`material_like_objective`)
matches the FishStandard problem on three properties identified in the
survey as the things that break naive optimizers:

1. **Box-bounded** axes with widely different scales (color ∈ [0,1],
   gamma ∈ [0.05, 10], intensity ∈ [0, 8]). Sigma scaling matters.
2. **Multiplicative coupling** (gamma · brightness · saturation):
   independent coordinate descent fails because moving any one of the
   three doesn't make local progress at the optimum surface — the
   surface is a curved manifold in (gamma, brightness, sat) space.
3. **Multi-modality**: each axis has a small Rastrigin-style ripple
   on top of the quadratic term, so pure gradient descent gets stuck.

Algorithms compared
-------------------

* ``random_search`` — uniform sampling inside bounds. Worst-case
  reference.
* ``cma_cold`` — vanilla CMA-ES, started at the noisy "current Laya"
  parameter point. This is "best black-box optimizer with no prior".
* ``cma_warm_good`` — WS-CMA-ES seeded from a *high-quality* heuristic
  trajectory (samples with mean near the true optimum and small std).
  This emulates the case where our heuristic's first 10 iterations
  *did* land in a good basin — the regime where WS-CMA-ES is
  supposed to shine.
* ``cma_warm_noisy`` — WS-CMA-ES seeded from a noisy / biased prior
  (samples far from the true optimum). This is the "what if our
  heuristic gives bad warm-start?" stress test.

Outputs
-------

The script writes into
``tools/material_fit/experiments_out/cma_es_warm_start_benchmark/<timestamp>/``:

* ``results.json`` — per-(algorithm, seed) best-so-far curves, final
  scores, configuration used.
* ``summary.txt`` — human-readable convergence comparison.
* ``convergence.png`` — best-so-far vs evaluations (mean ± stddev),
  if ``matplotlib`` is available; otherwise skipped with a warning.

Run with::

    python tools/material_fit/experiments/cma_es_warm_start_benchmark.py
    python tools/material_fit/experiments/cma_es_warm_start_benchmark.py --seeds 5 --budget 200

"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.material_fit.optimizer.cma_es_optimizer import (  # noqa: E402
    CmaesConfig,
    CmaesOptimizer,
    ParameterEncoder,
)
from tools.material_fit.shared.models import ShaderParam  # noqa: E402


# ----------------------------------------------------------------------
# Synthetic problem


def _shader_params() -> list[ShaderParam]:
    """A FishStandard-like shader subset that produces a 25-axis encoder."""
    return [
        ShaderParam("u_BaseColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_Gamma_Power", "Range", default=1.0, range_min=0.05, range_max=10.0),
        ShaderParam("u_Metallic", "Range", default=0.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_Smoothness", "Range", default=1.0, range_min=0.0, range_max=1.0),
        ShaderParam("u_OcclusionStrength", "Range", default=1.0, range_min=0.0, range_max=10.0),
        ShaderParam("u_GIIntensity", "Float", default=1.0),
        ShaderParam("u_DiffuseThreshold", "Range", default=0.5, range_min=0.0, range_max=1.0),
        ShaderParam("u_DiffuseSmoothness", "Range", default=0.1, range_min=0.0, range_max=1.0),
        ShaderParam("u_ShadowColor", "Color", default=[0, 0, 0, 1]),
        ShaderParam("u_IBLMapColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_IBLMapIntensity", "Float", default=0.3),
        ShaderParam("u_SpecularColor", "Color", default=[1, 1, 1, 1]),
        ShaderParam("u_SpecularIntensity", "Float", default=1.0),
        ShaderParam("u_FresnelColor", "Color", default=[1, 0, 0, 0]),
        ShaderParam("u_FresnelIntensity", "Float", default=1.0),
        ShaderParam("u_AdjustHue", "Float", default=0.0),
        ShaderParam("u_AdjustSaturation", "Float", default=0.0),
        ShaderParam("u_AdjustLightness", "Float", default=0.0),
        ShaderParam("u_ContrastScale", "Float", default=0.0),
        ShaderParam("u_EmissionColor", "Color", default=[0, 0, 0, 0]),
        ShaderParam("u_EmissionScale", "Float", default=1.0),
    ]


def _initial_params() -> dict[str, object]:
    """Match the iter_0000 params.json from the real fish_1580 case."""
    return {
        "u_BaseColor": [0.32, 0.27, 0.07, 1.0],
        "u_Gamma_Power": 2.2,
        "u_Metallic": 0.0,
        "u_Smoothness": 1.0,
        "u_OcclusionStrength": 1.0,
        "u_GIIntensity": 1.0,
        "u_DiffuseThreshold": 0.5,
        "u_DiffuseSmoothness": 0.1,
        "u_ShadowColor": [0.0, 0.0, 0.0, 1.0],
        "u_IBLMapColor": [1.0, 1.0, 1.0, 1.0],
        "u_IBLMapIntensity": 0.3,
        "u_SpecularColor": [1.0, 1.0, 1.0, 1.0],
        "u_SpecularIntensity": 1.0,
        "u_FresnelColor": [1.0, 0.0, 0.0, 0.0],
        "u_FresnelIntensity": 1.0,
        "u_AdjustHue": 0.0,
        "u_AdjustSaturation": 0.0,
        "u_AdjustLightness": 0.0,
        "u_ContrastScale": 0.0,
        "u_EmissionColor": [0.0, 0.0, 0.0, 0.0],
        "u_EmissionScale": 1.0,
    }


def _build_encoder() -> ParameterEncoder:
    return ParameterEncoder(_initial_params(), _shader_params())


def _normalize(x: np.ndarray, encoder: ParameterEncoder) -> np.ndarray:
    """Map ``x`` from raw bounds to [0, 1] for objective definition."""
    return (x - encoder.lower_bounds) / (encoder.upper_bounds - encoder.lower_bounds)


def material_like_objective(
    x: np.ndarray,
    target_norm: np.ndarray,
    encoder: ParameterEncoder,
    *,
    coupling_pairs: list[tuple[int, int]],
    rastrigin_amp: float = 0.05,
    rastrigin_freq: float = 6.0,
) -> float:
    """A loss that imitates the empirical structure of cross-engine fitting.

    Components:

    * **Quadratic to target** in normalized [0,1] coordinates — the
      first-order signal that any reasonable optimizer should follow.
    * **Multiplicative coupling** for selected axis pairs ``(i, j)``:
      adds ``(x_i * x_j - target_i * target_j) ** 2``. This penalty is
      *zero* on a curved manifold, not an axis-aligned point, so naive
      coordinate descent can get stuck in the manifold without
      reducing it.
    * **Rastrigin ripple** (multi-modality): small high-frequency
      cosine bumps that create local minima in every direction.

    All sub-losses live on roughly the same scale (≤1 each) so the
    overall objective stays in O(1) for the box.
    """
    x_norm = _normalize(x, encoder)
    quad = float(np.sum((x_norm - target_norm) ** 2))
    coupling = 0.0
    for i, j in coupling_pairs:
        coupling += float((x_norm[i] * x_norm[j] - target_norm[i] * target_norm[j]) ** 2)
    ripple = float(np.sum(rastrigin_amp * (1.0 - np.cos(rastrigin_freq * math.pi * (x_norm - target_norm)))))
    return quad + 0.5 * coupling + ripple


def make_target(encoder: ParameterEncoder, *, seed: int) -> np.ndarray:
    """Pick a random ground-truth in normalized [0.15, 0.85] per axis.

    Avoiding the very edges keeps the optimum strictly inside bounds so
    bound-clipping doesn't accidentally help algorithms that hug the
    walls.
    """
    rng = np.random.default_rng(seed)
    return rng.uniform(0.15, 0.85, size=encoder.dim)


def make_initial_in_bounds(encoder: ParameterEncoder, target_norm: np.ndarray, *, seed: int, offset: float = 0.35) -> np.ndarray:
    """Return a noisy starting point ``offset`` away from the target.

    Uses additive Gaussian noise of stddev ``offset`` in normalized
    coords, then clipped back to [0,1]. Mirrors how a freshly-imported
    Laya material differs from the Unity ground-truth.
    """
    rng = np.random.default_rng(seed + 1_000)
    init_norm = np.clip(target_norm + rng.normal(0.0, offset, size=target_norm.shape), 0.05, 0.95)
    return encoder.lower_bounds + init_norm * (encoder.upper_bounds - encoder.lower_bounds)


def make_warm_start_history(
    encoder: ParameterEncoder,
    target_norm: np.ndarray,
    *,
    n: int,
    quality: str,
    seed: int,
    objective: Callable[[np.ndarray], float],
) -> list[tuple[dict, float]]:
    """Synthesize ``n`` (params, fitness) pairs that imitate a heuristic prior.

    ``quality``:

    * ``"good"`` — samples drawn near ``target_norm`` (stddev 0.10),
      mimicking a heuristic that quickly homed in on the right basin.
    * ``"noisy"`` — samples drawn with a biased mean (target shifted
      by 0.3 in a random direction) and large stddev (0.25). Mimics a
      heuristic that got stuck in a wrong basin like the user observed.
    """
    rng = np.random.default_rng(seed + 2_000)
    if quality == "good":
        center = target_norm
        spread = 0.10
    elif quality == "noisy":
        bias = rng.normal(0.0, 0.30, size=target_norm.shape)
        center = np.clip(target_norm + bias, 0.05, 0.95)
        spread = 0.25
    else:
        raise ValueError(f"unknown quality {quality!r}")

    history: list[tuple[dict, float]] = []
    for _ in range(n):
        norm = np.clip(center + rng.normal(0.0, spread, size=center.shape), 0.0, 1.0)
        x = encoder.lower_bounds + norm * (encoder.upper_bounds - encoder.lower_bounds)
        params = encoder.decode(x)
        fitness = float(objective(x))
        history.append((params, fitness))
    return history


# ----------------------------------------------------------------------
# Algorithm runners


@dataclass
class RunResult:
    algorithm: str
    seed: int
    best_per_eval: list[float] = field(default_factory=list)  # length = budget
    final_best: float = math.inf
    extras: dict = field(default_factory=dict)


def _track_best(curve: list[float], current_best: float, fitness: float) -> tuple[list[float], float]:
    new_best = fitness if fitness < current_best else current_best
    curve.append(new_best)
    return curve, new_best


def run_random_search(
    encoder: ParameterEncoder,
    initial_x: np.ndarray,
    objective: Callable[[np.ndarray], float],
    budget: int,
    seed: int,
) -> RunResult:
    rng = np.random.default_rng(seed)
    res = RunResult(algorithm="random_search", seed=seed)
    best = math.inf
    # Eval the initial point first so all algorithms share the same
    # "iteration 0" baseline.
    f0 = float(objective(initial_x))
    res.best_per_eval, best = _track_best(res.best_per_eval, best, f0)
    for _ in range(budget - 1):
        norm = rng.uniform(0.0, 1.0, size=encoder.dim)
        x = encoder.lower_bounds + norm * (encoder.upper_bounds - encoder.lower_bounds)
        f = float(objective(x))
        res.best_per_eval, best = _track_best(res.best_per_eval, best, f)
    res.final_best = best
    return res


def run_cma_cold(
    encoder: ParameterEncoder,
    initial_x: np.ndarray,
    objective: Callable[[np.ndarray], float],
    budget: int,
    seed: int,
) -> RunResult:
    """Vanilla CMA-ES, started at ``initial_x`` (per-seed Laya init point).

    Crucial detail: we share the *outer* ``encoder`` (its bounds and
    axis ordering) across every algorithm so that ``objective(x)`` and
    every algorithm see the same coordinate system. Constructing a
    second :class:`ParameterEncoder` here would silently produce a
    different axis order (Python dict iteration), which previously made
    cold CMA-ES look catastrophically worse than random search — see
    git history for the bug.
    """
    opt = CmaesOptimizer(
        encoder,
        config=CmaesConfig(seed=seed),
        initial_mean=initial_x,
    )
    res = RunResult(algorithm="cma_cold", seed=seed, extras={"pop": opt.population_size})
    best = math.inf
    f0 = float(objective(initial_x))
    res.best_per_eval, best = _track_best(res.best_per_eval, best, f0)
    while opt.evaluations < budget - 1 and not opt.should_stop():
        params = opt.ask()
        x = encoder.encode(params)
        f = float(objective(x))
        opt.tell(f)
        res.best_per_eval, best = _track_best(res.best_per_eval, best, f)
    while len(res.best_per_eval) < budget:
        res.best_per_eval.append(best)
    res.final_best = best
    return res


def run_cma_warm(
    encoder: ParameterEncoder,
    initial_x: np.ndarray,
    objective: Callable[[np.ndarray], float],
    history: list[tuple[dict, float]],
    budget: int,
    seed: int,
    label: str,
) -> RunResult:
    opt = CmaesOptimizer(
        encoder,
        config=CmaesConfig(seed=seed),
        warm_start_samples=history,
        initial_mean=initial_x,
    )
    assert opt.warm_started
    res = RunResult(
        algorithm=label,
        seed=seed,
        extras={"pop": opt.population_size, "history_size": len(history)},
    )
    best = math.inf
    # Charge the warm-start history against the budget — that's the
    # honest comparison (those samples really were evaluated by the
    # heuristic, just before CMA-ES took over).
    for _, f in history[: budget - 1]:
        res.best_per_eval, best = _track_best(res.best_per_eval, best, float(f))
    consumed = min(len(history), budget - 1)
    if consumed < budget:
        f0 = float(objective(initial_x))
        res.best_per_eval, best = _track_best(res.best_per_eval, best, f0)
        consumed += 1
    while consumed < budget and not opt.should_stop():
        params = opt.ask()
        x = encoder.encode(params)
        f = float(objective(x))
        opt.tell(f)
        res.best_per_eval, best = _track_best(res.best_per_eval, best, f)
        consumed += 1
    while len(res.best_per_eval) < budget:
        res.best_per_eval.append(best)
    res.final_best = best
    return res


# ----------------------------------------------------------------------
# Orchestration


@dataclass
class ExperimentConfig:
    seeds: list[int]
    budget: int = 200
    history_size: int = 12
    coupling_pair_count: int = 4

    def to_dict(self) -> dict:
        return asdict(self)


def run_experiment(config: ExperimentConfig) -> dict:
    encoder = _build_encoder()
    rng = np.random.default_rng(20260506)
    coupling_pairs = []
    for _ in range(config.coupling_pair_count):
        i, j = rng.choice(encoder.dim, size=2, replace=False)
        coupling_pairs.append((int(i), int(j)))

    all_results: list[RunResult] = []
    summary_rows: list[str] = []

    for seed in config.seeds:
        target_norm = make_target(encoder, seed=seed)
        initial_x = make_initial_in_bounds(encoder, target_norm, seed=seed, offset=0.30)

        def objective(x: np.ndarray, _t=target_norm, _enc=encoder, _cp=coupling_pairs) -> float:
            return material_like_objective(x, _t, _enc, coupling_pairs=_cp)

        history_good = make_warm_start_history(
            encoder, target_norm, n=config.history_size, quality="good",
            seed=seed, objective=objective,
        )
        history_noisy = make_warm_start_history(
            encoder, target_norm, n=config.history_size, quality="noisy",
            seed=seed, objective=objective,
        )

        rs = run_random_search(encoder, initial_x, objective, config.budget, seed=seed)
        cold = run_cma_cold(encoder, initial_x, objective, config.budget, seed=seed)
        warm_good = run_cma_warm(
            encoder, initial_x, objective, history_good, config.budget, seed=seed,
            label="cma_warm_good",
        )
        warm_noisy = run_cma_warm(
            encoder, initial_x, objective, history_noisy, config.budget, seed=seed,
            label="cma_warm_noisy",
        )

        for r in (rs, cold, warm_good, warm_noisy):
            all_results.append(r)
            summary_rows.append(
                f"seed={seed:>4d}  {r.algorithm:<16s}  final={r.final_best:.6f}"
            )

    return {
        "config": {
            "encoder_dim": encoder.dim,
            "lower_bounds": encoder.lower_bounds.tolist(),
            "upper_bounds": encoder.upper_bounds.tolist(),
            "coupling_pairs": coupling_pairs,
            **config.to_dict(),
        },
        "results": [
            {
                "algorithm": r.algorithm,
                "seed": r.seed,
                "best_per_eval": r.best_per_eval,
                "final_best": r.final_best,
                "extras": r.extras,
            }
            for r in all_results
        ],
        "summary_rows": summary_rows,
    }


# ----------------------------------------------------------------------
# Aggregation + reporting


def aggregate_curves(results: dict) -> dict[str, dict[str, list[float]]]:
    """Group by algorithm; return {alg: {"mean": [...], "std": [...]}}."""
    by_alg: dict[str, list[list[float]]] = {}
    for r in results["results"]:
        by_alg.setdefault(r["algorithm"], []).append(r["best_per_eval"])
    out: dict[str, dict[str, list[float]]] = {}
    for alg, curves in by_alg.items():
        arr = np.array(curves, dtype=np.float64)  # shape (seeds, budget)
        out[alg] = {
            "mean": arr.mean(axis=0).tolist(),
            "std": arr.std(axis=0).tolist(),
            "final_mean": float(arr[:, -1].mean()),
            "final_std": float(arr[:, -1].std()),
        }
    return out


def write_summary_text(out_dir: Path, results: dict, aggregated: dict) -> Path:
    lines: list[str] = []
    cfg = results["config"]
    lines.append("CMA-ES Warm-Start Benchmark")
    lines.append("=" * 60)
    lines.append(f"dim={cfg['encoder_dim']}  budget={cfg['budget']}  seeds={cfg['seeds']}  history_size={cfg['history_size']}")
    lines.append("")

    lines.append("Aggregated final best (lower is better)")
    lines.append("-" * 60)
    for alg in sorted(aggregated.keys()):
        agg = aggregated[alg]
        lines.append(f"{alg:<20s}  final={agg['final_mean']:.6f} ± {agg['final_std']:.6f}")
    lines.append("")

    # Convergence speed comparison: how many evals to reach 50%/10% of cold-final
    if "cma_cold" in aggregated:
        cold_final = aggregated["cma_cold"]["final_mean"]
        thresholds = [0.5 * cold_final, 0.1 * cold_final]
        lines.append("Evaluations to reach (50% / 10%) of cma_cold final")
        lines.append("-" * 60)
        for alg in sorted(aggregated.keys()):
            mean_curve = np.array(aggregated[alg]["mean"])
            evals_50 = _first_below(mean_curve, thresholds[0])
            evals_10 = _first_below(mean_curve, thresholds[1])
            lines.append(f"{alg:<20s}  ≤50%: {_fmt_eval(evals_50)}   ≤10%: {_fmt_eval(evals_10)}")
        lines.append("")

    lines.append("Per-run summary")
    lines.append("-" * 60)
    for row in results["summary_rows"]:
        lines.append(row)

    txt = "\n".join(lines) + "\n"
    target = out_dir / "summary.txt"
    target.write_text(txt, encoding="utf-8")
    return target


def _first_below(curve: np.ndarray, threshold: float) -> int | None:
    idx = np.where(curve <= threshold)[0]
    return int(idx[0]) if len(idx) else None


def _fmt_eval(n: int | None) -> str:
    return "never" if n is None else f"{n:>4d}"


def write_plot(out_dir: Path, aggregated: dict, budget: int, dim: int) -> Path | None:
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except ImportError:
        print("[benchmark] matplotlib not available — skipping plot", file=sys.stderr)
        return None
    fig, ax = plt.subplots(figsize=(8, 5), dpi=120)
    xs = np.arange(budget)
    palette = {
        "random_search": "#888888",
        "cma_cold": "#1f77b4",
        "cma_warm_good": "#2ca02c",
        "cma_warm_noisy": "#d62728",
    }
    for alg in sorted(aggregated.keys()):
        agg = aggregated[alg]
        mean = np.array(agg["mean"])
        std = np.array(agg["std"])
        color = palette.get(alg, None)
        ax.plot(xs, mean, label=alg, color=color, linewidth=2)
        ax.fill_between(xs, mean - std, mean + std, alpha=0.15, color=color)
    ax.set_xlabel("Evaluations")
    ax.set_ylabel("Best fitness so far (lower is better)")
    ax.set_title(f"CMA-ES warm-start benchmark — material-like {dim}-D objective")
    ax.set_yscale("log")
    ax.grid(True, which="both", linestyle=":", alpha=0.5)
    ax.legend(loc="upper right")
    fig.tight_layout()
    target = out_dir / "convergence.png"
    fig.savefig(target)
    plt.close(fig)
    return target


# ----------------------------------------------------------------------
# CLI


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--seeds", type=int, default=5, help="number of random seeds")
    p.add_argument("--budget", type=int, default=200, help="evaluations per algorithm per seed")
    p.add_argument("--history-size", type=int, default=12, help="how many heuristic samples to feed WS")
    p.add_argument("--coupling-pairs", type=int, default=4)
    p.add_argument("--out-dir", type=Path, default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    seeds = list(range(1, args.seeds + 1))
    config = ExperimentConfig(
        seeds=seeds,
        budget=args.budget,
        history_size=args.history_size,
        coupling_pair_count=args.coupling_pairs,
    )

    if args.out_dir is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_dir = REPO_ROOT / "tools" / "material_fit" / "experiments_out" / "cma_es_warm_start_benchmark" / ts
    else:
        out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[benchmark] running with seeds={seeds} budget={args.budget} history={args.history_size}")
    print(f"[benchmark] output dir: {out_dir}")
    t0 = time.time()
    results = run_experiment(config)
    print(f"[benchmark] {len(results['results'])} runs completed in {time.time() - t0:.1f}s")

    aggregated = aggregate_curves(results)

    (out_dir / "results.json").write_text(
        json.dumps({"experiment": results, "aggregated": aggregated}, indent=2),
        encoding="utf-8",
    )
    summary_path = write_summary_text(out_dir, results, aggregated)
    plot_path = write_plot(out_dir, aggregated, args.budget, results["config"]["encoder_dim"])

    print(f"[benchmark] summary  -> {summary_path}")
    if plot_path:
        print(f"[benchmark] plot     -> {plot_path}")
    print()
    print((out_dir / "summary.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
