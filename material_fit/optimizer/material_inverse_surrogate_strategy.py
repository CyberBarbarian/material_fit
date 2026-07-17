"""Online inverse surrogate for asset-independent material fitting."""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ..shared.models import ShaderParam
from .strategy_core import OptimizerStrategy, StrategyContext
from .structured_fish_proposals import parameter_changes, residual_feature_vector
from .structured_fish_space import FishSearchCoordinate, structured_fish_coordinates


class MaterialInverseSurrogateStrategy(OptimizerStrategy):
    """Learn residual-to-parameter proposals from renderer-generated samples."""

    name = "material_inverse_surrogate"

    def __init__(
        self,
        *,
        initial_params: dict[str, Any],
        shader_params: Sequence[ShaderParam],
        search_param_names: Sequence[str] | None,
        config: dict[str, Any] | None = None,
    ) -> None:
        cfg = config if isinstance(config, dict) else {}
        self._coordinates = structured_fish_coordinates(
            initial_params,
            shader_params=shader_params,
            search_param_names=search_param_names,
        )
        if not self._coordinates:
            raise ValueError("material_inverse_surrogate has no searchable coordinates")
        self._base_params = copy.deepcopy(initial_params)
        self._initial_vector = self._encode(initial_params)
        self._local_probe_radius = _bounded_float(
            cfg.get("local_probe_radius"), 0.10, 0.005, 0.50
        )
        self._sample_count = max(
            int(cfg.get("sample_count", 384)),
            2 * len(self._coordinates),
        )
        radii = cfg.get("global_radii", (0.08, 0.16, 0.32, 0.55))
        self._global_radii = tuple(
            _bounded_float(value, 0.20, 0.01, 1.0) for value in radii
        ) or (0.08, 0.16, 0.32, 0.55)
        self._feature_count = max(int(cfg.get("feature_count", 192)), 8)
        self._feature_selection = str(cfg.get("feature_selection", "correlation")).strip().lower()
        self._hidden_features = max(int(cfg.get("hidden_features", 96)), 8)
        self._ridge_values = tuple(
            max(float(value), 1.0e-8)
            for value in cfg.get("ridge_values", (1.0e-3, 1.0e-2, 1.0e-1))
        )
        self._random_feature_scales = tuple(
            max(float(value), 1.0e-3)
            for value in cfg.get("random_feature_scales", (0.35, 0.75, 1.5))
        )
        self._blend_scales = tuple(
            float(value)
            for value in cfg.get("prediction_blend_scales", (0.5, 1.0, 1.5))
            if float(value) > 0.0
        ) or (0.5, 1.0, 1.5)
        self._seed = int(cfg.get("seed", 20260715))
        self._max_model_cycles = max(int(cfg.get("max_model_cycles", 1)), 1)
        dataset_output = str(cfg.get("dataset_output_path") or "").strip()
        self._dataset_output_path = Path(dataset_output).expanduser() if dataset_output else None

        self._sample_queue = self._build_sample_queue()
        self._prediction_queue: list[dict[str, Any]] = []
        self._samples: list[dict[str, Any]] = []
        self._pending: dict[str, Any] | None = None
        self._initial_recorded = False
        self._models_built = 0
        self._prediction_count = 0
        self._seen_prediction_keys: set[tuple[float, ...]] = set()
        self._selected_feature_count = 0
        self._feature_size: int | None = None
        self._discarded_feature_samples = 0
        self._best_params = copy.deepcopy(initial_params)
        self._best_score: float | None = None
        self._best_observed_score: float | None = None
        self._stop_reason: str | None = None

    def wants_global_no_improve_check(self) -> bool:
        return False

    def stop_reason(self) -> str | None:
        return self._stop_reason

    def propose(self, ctx: StrategyContext) -> tuple[dict[str, Any], dict[str, Any]]:
        self._consume_pending(ctx)
        self._record_best(ctx)
        if not self._initial_recorded:
            features = self._features(ctx)
            if features is None:
                self._stop_reason = "missing_structured_residual_features"
                return copy.deepcopy(ctx.current_params), self._decision("stopped")
            self._samples.append(
                {
                    "vector": self._encode(ctx.current_params),
                    "features": features,
                    "score": float(ctx.fit_score),
                }
            )
            self._initial_recorded = True

        if self._sample_queue:
            vector = self._sample_queue.pop(0)
            candidate = self._decode(vector)
            self._pending = {"role": "training_sample", "vector": vector}
            return candidate, self._decision("training_sample", candidate=candidate)

        if not self._prediction_queue and self._models_built < self._max_model_cycles:
            self._prediction_queue = self._build_predictions()
            self._models_built += 1
            self._prediction_count += len(self._prediction_queue)
            if not self._prediction_queue:
                self._stop_reason = "inverse_surrogate_no_predictions"
                self._persist_dataset()
                return copy.deepcopy(self._best_params), self._decision("stopped")

        if self._prediction_queue:
            item = self._prediction_queue.pop(0)
            vector = np.asarray(item["vector"], dtype=np.float64)
            candidate = self._decode(vector)
            self._pending = {
                "role": "inverse_prediction",
                "vector": vector,
                "model": item["model"],
            }
            return candidate, self._decision(
                "inverse_prediction",
                candidate=candidate,
                model=str(item["model"]),
            )

        self._stop_reason = "inverse_surrogate_predictions_exhausted"
        self._persist_dataset()
        return copy.deepcopy(self._best_params), self._decision("complete")

    def research_summary(self) -> dict[str, Any]:
        return {
            "profile": "material_inverse_surrogate_v1",
            "asset_independent": True,
            "feedback_source": "online_target_png_signed_residuals_only",
            "target_params_visible": False,
            "coordinate_count": len(self._coordinates),
            "planned_training_samples": self._sample_count,
            "recorded_training_samples": len(self._samples),
            "selected_feature_count": self._selected_feature_count,
            "feature_selection": self._feature_selection,
            "residual_feature_size": self._feature_size,
            "discarded_incomplete_feature_samples": self._discarded_feature_samples,
            "models_built": self._models_built,
            "maximum_model_cycles": self._max_model_cycles,
            "prediction_count": self._prediction_count,
            "best_score": self._best_score,
            "best_observed_score": self._best_observed_score,
            "stop_reason": self._stop_reason,
        }

    def _consume_pending(self, ctx: StrategyContext) -> None:
        pending = self._pending
        if pending is None:
            return
        self._pending = None
        self._record_best(ctx)
        features = self._features(ctx)
        if features is None:
            return
        self._samples.append(
            {
                "vector": np.asarray(pending["vector"], dtype=np.float64),
                "features": features,
                "score": float(ctx.fit_score),
            }
        )

    def _record_best(self, ctx: StrategyContext) -> None:
        score = float(ctx.fit_score)
        if self._best_observed_score is None or score > self._best_observed_score:
            self._best_observed_score = score
        if self._best_score is None or score > self._best_score:
            self._best_score = score
            self._best_params = copy.deepcopy(ctx.current_params)

    def _features(self, ctx: StrategyContext) -> np.ndarray | None:
        raw = residual_feature_vector(ctx.analysis)
        if raw is None:
            self._discarded_feature_samples += 1
            return None
        values = np.asarray(raw, dtype=np.float64)
        if not np.all(np.isfinite(values)):
            self._discarded_feature_samples += 1
            return None
        if self._feature_size is None:
            self._feature_size = int(values.size)
        if values.size != self._feature_size:
            self._discarded_feature_samples += 1
            return None
        return values

    def _build_sample_queue(self) -> list[np.ndarray]:
        dimension = len(self._coordinates)
        queue: list[np.ndarray] = []
        for axis in range(dimension):
            for sign in (1.0, -1.0):
                vector = self._initial_vector.copy()
                vector[axis] = np.clip(
                    vector[axis] + sign * self._local_probe_radius,
                    0.0,
                    1.0,
                )
                queue.append(vector)
        remaining = self._sample_count - len(queue)
        primes = _first_primes(dimension)
        for index in range(remaining):
            unit = np.asarray(
                [_radical_inverse(index + 1 + self._seed % 997, prime) for prime in primes],
                dtype=np.float64,
            )
            radius = self._global_radii[index % len(self._global_radii)]
            queue.append(np.clip(self._initial_vector + radius * (2.0 * unit - 1.0), 0.0, 1.0))
        return queue

    def _build_predictions(self) -> list[dict[str, Any]]:
        if len(self._samples) < max(2 * len(self._coordinates) + 1, 8):
            return []
        features = np.vstack([sample["features"] for sample in self._samples])
        vectors = np.vstack([sample["vector"] for sample in self._samples])
        scores = np.asarray([sample["score"] for sample in self._samples], dtype=np.float64)
        self._persist_dataset(features=features, vectors=vectors, scores=scores)
        feature_count = min(self._feature_count, features.shape[0] - 1, features.shape[1])
        if self._feature_selection == "correlation":
            centered_features = features - np.mean(features, axis=0)
            centered_vectors = vectors - np.mean(vectors, axis=0)
            feature_norm = np.sqrt(np.sum(np.square(centered_features), axis=0))
            vector_norm = np.sqrt(np.sum(np.square(centered_vectors), axis=0))
            denominator = np.maximum(feature_norm[:, None] * vector_norm[None, :], 1.0e-12)
            correlation = (centered_features.T @ centered_vectors) / denominator
            selection_score = np.sum(np.square(correlation), axis=1)
        else:
            selection_score = np.var(features, axis=0)
        selected = np.argsort(selection_score)[-feature_count:]
        self._selected_feature_count = int(feature_count)

        ranked = np.argsort(scores)[::-1]
        subset_sizes = sorted(
            {
                len(self._samples),
                min(len(self._samples), max(96, len(self._samples) // 2)),
                min(len(self._samples), max(64, len(self._coordinates) * 2)),
            },
            reverse=True,
        )
        predictions: list[dict[str, Any]] = []
        for subset_size in subset_sizes:
            indices = ranked[:subset_size]
            raw = features[indices][:, selected]
            outputs = vectors[indices]
            mean = np.mean(raw, axis=0)
            std = np.std(raw, axis=0)
            std = np.where(std > 1.0e-7, std, 1.0)
            inputs = np.clip((raw - mean) / std, -8.0, 8.0)
            query = np.clip(-mean / std, -8.0, 8.0)

            for ridge in self._ridge_values:
                design = np.column_stack((np.ones(len(inputs)), inputs))
                query_design = np.concatenate(([1.0], query))
                prediction = _ridge_predict(design, outputs, query_design, ridge)
                self._append_prediction_family(
                    predictions,
                    prediction,
                    f"linear_n{subset_size}_ridge{ridge:g}",
                )

            for scale in self._random_feature_scales:
                rng = np.random.default_rng(self._seed + subset_size + int(scale * 1000))
                weights = rng.normal(
                    0.0,
                    1.0 / math.sqrt(max(inputs.shape[1], 1)),
                    size=(inputs.shape[1], self._hidden_features),
                )
                bias = rng.uniform(-1.0, 1.0, size=self._hidden_features)
                hidden = np.tanh(scale * (inputs @ weights) + bias)
                query_hidden = np.tanh(scale * (query @ weights) + bias)
                design = np.column_stack((np.ones(len(hidden)), hidden))
                query_design = np.concatenate(([1.0], query_hidden))
                for ridge in self._ridge_values:
                    prediction = _ridge_predict(design, outputs, query_design, ridge)
                    self._append_prediction_family(
                        predictions,
                        prediction,
                        f"elm_n{subset_size}_s{scale:g}_ridge{ridge:g}",
                    )
        unique = []
        for item in _deduplicate_predictions(predictions):
            vector = np.asarray(item["vector"], dtype=np.float64)
            key = tuple(np.round(vector, 8))
            if key in self._seen_prediction_keys:
                continue
            self._seen_prediction_keys.add(key)
            unique.append(item)
        return unique

    def _persist_dataset(
        self,
        *,
        features: np.ndarray | None = None,
        vectors: np.ndarray | None = None,
        scores: np.ndarray | None = None,
    ) -> None:
        if self._dataset_output_path is None or not self._samples:
            return
        if features is None:
            features = np.vstack([sample["features"] for sample in self._samples])
        if vectors is None:
            vectors = np.vstack([sample["vector"] for sample in self._samples])
        if scores is None:
            scores = np.asarray([sample["score"] for sample in self._samples], dtype=np.float64)
        self._dataset_output_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            self._dataset_output_path,
            features=features.astype(np.float32),
            vectors=vectors.astype(np.float32),
            scores=scores.astype(np.float32),
        )

    def _append_prediction_family(
        self,
        predictions: list[dict[str, Any]],
        prediction: np.ndarray,
        model: str,
    ) -> None:
        if not np.all(np.isfinite(prediction)):
            return
        direction = np.asarray(prediction, dtype=np.float64) - self._initial_vector
        for blend in self._blend_scales:
            predictions.append(
                {
                    "vector": np.clip(self._initial_vector + blend * direction, 0.0, 1.0),
                    "model": f"{model}_blend{blend:g}",
                }
            )

    def _encode(self, params: dict[str, Any]) -> np.ndarray:
        return np.asarray(
            [
                (coordinate.read(params) - coordinate.low)
                / max(coordinate.high - coordinate.low, 1.0e-12)
                for coordinate in self._coordinates
            ],
            dtype=np.float64,
        ).clip(0.0, 1.0)

    def _decode(self, vector: np.ndarray) -> dict[str, Any]:
        result = copy.deepcopy(self._base_params)
        for coordinate, normalized in zip(self._coordinates, vector, strict=True):
            result = coordinate.write(
                result,
                coordinate.low + float(normalized) * (coordinate.high - coordinate.low),
            )
        return result

    def _decision(
        self,
        role: str,
        *,
        candidate: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        return {
            "optimizer": self.name,
            "stage": {
                "name": f"material_inverse_surrogate_{role}",
                "description": "Online residual-to-parameter inverse surrogate",
            },
            "material_inverse_surrogate": {
                "role": role,
                "coordinate_count": len(self._coordinates),
                "training_samples_recorded": len(self._samples),
                "training_samples_remaining": len(self._sample_queue),
                "predictions_remaining": len(self._prediction_queue),
                "model": model,
                "best_score": self._best_score,
                "feedback_source": "online_target_png_signed_residuals_only",
                "target_params_visible": False,
            },
            "changes": parameter_changes(self._best_params, candidate or self._best_params),
            "stop_reason": self._stop_reason or "continue",
        }


def _ridge_predict(
    design: np.ndarray,
    outputs: np.ndarray,
    query: np.ndarray,
    ridge: float,
) -> np.ndarray:
    if design.shape[1] <= design.shape[0]:
        gram = design.T @ design
        penalty = ridge * np.eye(gram.shape[0])
        penalty[0, 0] = ridge * 1.0e-3
        try:
            coefficients = np.linalg.solve(gram + penalty, design.T @ outputs)
        except np.linalg.LinAlgError:
            coefficients = np.linalg.lstsq(gram + penalty, design.T @ outputs, rcond=None)[0]
        return np.asarray(query @ coefficients, dtype=np.float64)
    kernel = design @ design.T
    penalty = ridge * np.eye(kernel.shape[0])
    try:
        coefficients = np.linalg.solve(kernel + penalty, outputs)
    except np.linalg.LinAlgError:
        coefficients = np.linalg.lstsq(kernel + penalty, outputs, rcond=None)[0]
    return np.asarray((query @ design.T) @ coefficients, dtype=np.float64)


def _deduplicate_predictions(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen: set[tuple[float, ...]] = set()
    for item in predictions:
        vector = np.asarray(item["vector"], dtype=np.float64)
        key = tuple(np.round(vector, 8))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _radical_inverse(index: int, base: int) -> float:
    result = 0.0
    fraction = 1.0 / base
    while index > 0:
        index, remainder = divmod(index, base)
        result += remainder * fraction
        fraction /= base
    return result


def _first_primes(count: int) -> list[int]:
    primes: list[int] = []
    candidate = 2
    while len(primes) < count:
        if all(candidate % prime for prime in primes if prime * prime <= candidate):
            primes.append(candidate)
        candidate += 1
    return primes


def _bounded_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    if not math.isfinite(numeric):
        numeric = default
    return min(max(numeric, low), high)


__all__ = ["MaterialInverseSurrogateStrategy"]
