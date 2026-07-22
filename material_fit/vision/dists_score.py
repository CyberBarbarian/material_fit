from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from material_fit.vision.cross_engine_alignment import (
    foreground_mask,
    trusted_intersection_core,
)
from material_fit.vision.cross_engine_score import score_cross_engine_pair_v3
DISTS_METRIC = "foreground_dists_v1"
DISTS_MATERIAL_METRIC = "foreground_dists_material_v1"
DISTS_ALIGNED_RGB_V3_METRIC = "foreground_dists_aligned_rgb_v3"
DISTS_ALIGNED_RGB_V5_METRIC = "foreground_dists_aligned_rgb_v5"
DISTS_ALIGNED_RGB_METRIC = "foreground_dists_aligned_rgb_v6"
DISTS_MATERIAL_DISTS_WEIGHT = 0.25
DISTS_MATERIAL_ALIGNED_WEIGHT = 0.75
DISTS_ALIGNED_RGB_V5_DISTS_WEIGHT = 0.90
DISTS_ALIGNED_RGB_V5_PIXEL_WEIGHT = 0.10
DISTS_ALIGNED_RGB_DISTS_WEIGHT = 0.75
DISTS_ALIGNED_RGB_PIXEL_WEIGHT = 0.05
DISTS_ALIGNED_RGB_LOCAL_CONTRAST_WEIGHT = 0.20
DISTS_ALIGNED_RGB_DESCRIPTOR_WEIGHT = 4.0
DISTS_ALIGNED_RGB_V3_DISTS_WEIGHT = 0.15
DISTS_ALIGNED_RGB_V3_PIXEL_WEIGHT = 0.85
DISTS_ALIGNED_RGB_V3_DESCRIPTOR_WEIGHT = 4.0
DEFAULT_ALIGNED_RGB_IMAGE_SIZE = 32
DEFAULT_LOCAL_CONTRAST_IMAGE_SIZE = 128
LOCAL_CONTRAST_DISTANCE_SCALE = 6.0
DEFAULT_DISTS_IMAGE_SIZE = 256
DEFAULT_DISTS_DEVICE = "auto"
DEFAULT_DISTS_TORCH_THREADS = 10
DEFAULT_DISTS_RESIDUAL_SKETCH_SIZE = 4096
DEFAULT_DISTS_RESIDUAL_SKETCH_TABLES = 4
DISTS_RESIDUAL_CONTRACT = "weighted_dists_factor_count_sketch_v1"
DISTS_MATERIAL_RESIDUAL_CONTRACT = (
    "weighted_dists_and_aligned_material_descriptor_v1"
)
DEFAULT_MATERIAL_RESIDUAL_GRID_SIZE = 16


def normalized_foreground_tensor(
    image: Image.Image,
    *,
    image_size: int = DEFAULT_DISTS_IMAGE_SIZE,
    allow_empty: bool = False,
    foreground: np.ndarray | None = None,
) -> Any:
    """Crop an object from a white or transparent render into a square tensor."""

    try:
        import torch
    except ImportError as exc:  # pragma: no cover - checked by deployment doctor
        raise RuntimeError(
            "DISTS scoring requires the perceptual dependency set: "
            "pip install -e '.[perceptual]'"
        ) from exc

    size = int(image_size)
    if size <= 0:
        raise ValueError(f"image_size must be positive, got {image_size}")
    canvas = _normalized_foreground_canvas(
        image,
        image_size=size,
        allow_empty=allow_empty,
        foreground=foreground,
    )
    values = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1) / 127.5 - 1.0
    return torch.from_numpy(values).unsqueeze(0)


def _normalized_foreground_canvas(
    image: Image.Image,
    *,
    image_size: int,
    allow_empty: bool,
    foreground: np.ndarray | None = None,
) -> Image.Image:
    rgba = image.convert("RGBA")
    mask = foreground
    if mask is None:
        mask, _ = foreground_mask(rgba)
    if mask.shape != (rgba.height, rgba.width):
        raise ValueError(
            f"foreground mask shape {mask.shape} does not match image "
            f"{(rgba.height, rgba.width)}"
        )
    rows = np.flatnonzero(mask.any(axis=1))
    columns = np.flatnonzero(mask.any(axis=0))
    size = int(image_size)
    if len(columns) == 0 or len(rows) == 0:
        if not allow_empty:
            raise ValueError("cannot perceptually score an empty foreground")
        return Image.new("RGB", (size, size), "white")

    left, top = int(columns[0]), int(rows[0])
    right, bottom = int(columns[-1]) + 1, int(rows[-1]) + 1
    crop = rgba.crop((left, top, right, bottom))
    crop_mask = Image.fromarray(mask[top:bottom, left:right].astype(np.uint8) * 255)
    isolated = Image.new("RGB", crop.size, "white")
    isolated.paste(crop.convert("RGB"), mask=crop_mask)
    scale = min(size / isolated.width, size / isolated.height)
    resized = isolated.resize(
        (
            max(1, round(isolated.width * scale)),
            max(1, round(isolated.height * scale)),
        ),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGB", (size, size), "white")
    canvas.paste(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
    return canvas


@dataclass(frozen=True)
class DISTSScore:
    fit_score: float
    distance: float
    residual_features: tuple[float, ...]
    preprocess_ms: float
    inference_ms: float
    device: str
    image_size: int
    candidate_foreground_pixels: int
    residual_contract: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": DISTS_METRIC,
            "fit_score": self.fit_score,
            "score": self.fit_score,
            "diff_score": 1.0 - self.fit_score,
            "dists_distance": self.distance,
            "residual_features": list(self.residual_features),
            "preprocess_ms": self.preprocess_ms,
            "inference_ms": self.inference_ms,
            "device": self.device,
            "image_size": self.image_size,
            "candidate_foreground_pixels": self.candidate_foreground_pixels,
            "residual_contract": self.residual_contract,
        }


@dataclass(frozen=True)
class DISTSMaterialScore:
    fit_score: float
    dists: DISTSScore
    aligned_material_score: float
    aligned_material_payload: dict[str, Any]
    residual_features: tuple[float, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.dists.as_dict(),
            "metric": DISTS_MATERIAL_METRIC,
            "fit_score": self.fit_score,
            "score": self.fit_score,
            "diff_score": 1.0 - self.fit_score,
            "dists_fit_score": self.dists.fit_score,
            "aligned_material_fit_score": self.aligned_material_score,
            "composite_weights": {
                "dists": DISTS_MATERIAL_DISTS_WEIGHT,
                "aligned_material": DISTS_MATERIAL_ALIGNED_WEIGHT,
            },
            "aligned_material": self.aligned_material_payload,
            "residual_features": list(self.residual_features),
            "residual_contract": DISTS_MATERIAL_RESIDUAL_CONTRACT,
        }


@dataclass(frozen=True)
class DISTSAlignedRGBScore:
    fit_score: float
    dists: DISTSScore
    aligned_rgb_score: float
    normalized_rgb_mae: float
    residual_features: tuple[float, ...]
    aligned_rgb_image_size: int
    metric: str
    dists_weight: float
    aligned_rgb_weight: float
    local_contrast_score: float
    local_contrast_distance: float
    local_contrast_weight: float
    local_contrast_image_size: int
    residual_contract: str

    def as_dict(self) -> dict[str, Any]:
        payload = {
            **self.dists.as_dict(),
            "metric": self.metric,
            "fit_score": self.fit_score,
            "score": self.fit_score,
            "diff_score": 1.0 - self.fit_score,
            "dists_fit_score": self.dists.fit_score,
            "aligned_rgb_fit_score": self.aligned_rgb_score,
            "normalized_rgb_mae": self.normalized_rgb_mae,
            "aligned_rgb_image_size": self.aligned_rgb_image_size,
            "composite_weights": {
                "dists": self.dists_weight,
                "aligned_rgb": self.aligned_rgb_weight,
            },
            "residual_features": list(self.residual_features),
            "residual_contract": self.residual_contract,
        }
        if self.local_contrast_weight > 0.0:
            payload.update(
                {
                    "local_contrast_fit_score": self.local_contrast_score,
                    "local_contrast_distance": self.local_contrast_distance,
                    "local_contrast_image_size": self.local_contrast_image_size,
                }
            )
            payload["composite_weights"]["local_contrast"] = (
                self.local_contrast_weight
            )
        return payload


class ForegroundDISTSScorer:
    """Cached foreground DISTS scorer for the single-view optimization line."""

    def __init__(
        self,
        *,
        image_size: int = DEFAULT_DISTS_IMAGE_SIZE,
        device: str = DEFAULT_DISTS_DEVICE,
        torch_threads: int = DEFAULT_DISTS_TORCH_THREADS,
        emit_residual_features: bool = False,
        residual_sketch_size: int = DEFAULT_DISTS_RESIDUAL_SKETCH_SIZE,
        residual_sketch_tables: int = DEFAULT_DISTS_RESIDUAL_SKETCH_TABLES,
    ) -> None:
        try:
            import DISTS_pytorch
            import torch
            from DISTS_pytorch import DISTS
        except ImportError as exc:  # pragma: no cover - exercised by deployment doctor
            raise RuntimeError(
                "DISTS scoring requires the perceptual dependency set: "
                "pip install -e '.[perceptual]'"
            ) from exc

        requested_device = str(device).strip().lower()
        if requested_device == "auto":
            requested_device = "cuda" if torch.cuda.is_available() else "cpu"
        if requested_device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("DISTS device is cuda but torch.cuda.is_available() is false")
        if requested_device not in {"cpu", "cuda"}:
            raise ValueError(f"unsupported DISTS device: {device}")
        if requested_device == "cpu" and int(torch_threads) > 0:
            torch.set_num_threads(int(torch_threads))

        self.image_size = int(image_size)
        if self.image_size <= 0:
            raise ValueError(f"image_size must be positive, got {image_size}")
        self.device = requested_device
        self.emit_residual_features = bool(emit_residual_features)
        self.residual_sketch_size = int(residual_sketch_size)
        self.residual_sketch_tables = int(residual_sketch_tables)
        if self.residual_sketch_size <= 0:
            raise ValueError("DISTS residual_sketch_size must be positive")
        if not 1 <= self.residual_sketch_tables <= self.residual_sketch_size:
            raise ValueError(
                "DISTS residual_sketch_tables must be between 1 and "
                "residual_sketch_size"
            )
        if self.residual_sketch_size % self.residual_sketch_tables != 0:
            raise ValueError(
                "DISTS residual_sketch_size must be divisible by "
                "residual_sketch_tables"
            )
        self._torch = torch
        self._model = DISTS(load_weights=False)
        package_root = Path(DISTS_pytorch.__file__).resolve().parent
        weights_path = package_root / "weights.pt"
        if not weights_path.is_file():
            raise RuntimeError(f"DISTS package is missing learned weights: {weights_path}")
        try:
            weights = torch.load(weights_path, map_location="cpu", weights_only=True)
        except TypeError:  # pragma: no cover - compatibility with older supported torch
            weights = torch.load(weights_path, map_location="cpu")
        self._model.alpha.data.copy_(weights["alpha"])
        self._model.beta.data.copy_(weights["beta"])
        self._model = self._model.to(self.device).eval()
        self._reference_cache: dict[tuple[str, int, int], tuple[Any, list[Any]]] = {}
        self._count_sketch_cache: dict[
            tuple[int, int, str, str], tuple[tuple[Any, Any], ...]
        ] = {}
        self._lock = threading.Lock()

    def score_paths(self, reference_path: str | Path, candidate_path: str | Path) -> DISTSScore:
        with Image.open(candidate_path) as candidate:
            candidate.load()
            return self.score_image(reference_path, candidate)

    def score_rgba(
        self,
        reference_path: str | Path,
        rgba: bytes,
        *,
        width: int,
        height: int,
    ) -> DISTSScore:
        expected = int(width) * int(height) * 4
        if len(rgba) != expected:
            raise ValueError(f"RGBA payload has {len(rgba)} bytes, expected {expected}")
        image = Image.frombytes("RGBA", (int(width), int(height)), rgba)
        return self.score_image(reference_path, image)

    def score_image(self, reference_path: str | Path, candidate: Image.Image) -> DISTSScore:
        started = time.perf_counter()
        candidate_rgba = candidate.convert("RGBA")
        candidate_mask, _ = foreground_mask(candidate_rgba)
        candidate_tensor = self._prepare_tensor(
            candidate_rgba,
            allow_empty=True,
            foreground=candidate_mask,
        )
        foreground_pixels = int(np.count_nonzero(candidate_mask))
        preprocess_ms = (time.perf_counter() - started) * 1000.0

        with self._lock, self._torch.inference_mode():
            _, reference_features = self._reference_representation(Path(reference_path))
            inference_started = time.perf_counter()
            candidate_features = self._model.forward_once(candidate_tensor)
            distance = self._distance_from_features(reference_features, candidate_features)
            residual = (
                self._residual_from_features(reference_features, candidate_features)
                if self.emit_residual_features
                else np.empty(0, dtype=np.float32)
            )
            if self.device == "cuda":
                self._torch.cuda.synchronize()
            inference_ms = (time.perf_counter() - inference_started) * 1000.0

        scalar_distance = max(0.0, float(distance.item()))
        return DISTSScore(
            fit_score=float(math.exp(-scalar_distance)),
            distance=scalar_distance,
            residual_features=tuple(float(value) for value in residual),
            preprocess_ms=preprocess_ms,
            inference_ms=inference_ms,
            device=self.device,
            image_size=self.image_size,
            candidate_foreground_pixels=foreground_pixels,
            residual_contract=(
                DISTS_RESIDUAL_CONTRACT if self.emit_residual_features else None
            ),
        )

    def _prepare_tensor(
        self,
        image: Image.Image,
        *,
        allow_empty: bool = False,
        foreground: np.ndarray | None = None,
    ) -> Any:
        normalized = normalized_foreground_tensor(
            image,
            image_size=self.image_size,
            allow_empty=allow_empty,
            foreground=foreground,
        )
        return ((normalized + 1.0) * 0.5).to(self.device)

    def _reference_representation(self, path: Path) -> tuple[Any, list[Any]]:
        resolved = path.expanduser().resolve()
        stat = resolved.stat()
        key = (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))
        cached = self._reference_cache.get(key)
        if cached is not None:
            return cached
        with Image.open(resolved) as source:
            source.load()
            tensor = self._prepare_tensor(source)
        representation = (tensor, self._model.forward_once(tensor))
        if len(self._reference_cache) >= 16:
            self._reference_cache.pop(next(iter(self._reference_cache)))
        self._reference_cache[key] = representation
        return representation

    def _distance_from_features(self, reference: list[Any], candidate: list[Any]) -> Any:
        c1 = 1.0e-6
        c2 = 1.0e-6
        weight_sum = self._model.alpha.sum() + self._model.beta.sum()
        alpha = self._torch.split(self._model.alpha / weight_sum, self._model.chns, dim=1)
        beta = self._torch.split(self._model.beta / weight_sum, self._model.chns, dim=1)
        structure_similarity: Any = 0
        texture_similarity: Any = 0
        for index, (left, right) in enumerate(zip(reference, candidate, strict=True)):
            left_mean = left.mean((2, 3), keepdim=True)
            right_mean = right.mean((2, 3), keepdim=True)
            structure = (2.0 * left_mean * right_mean + c1) / (
                left_mean.square() + right_mean.square() + c1
            )
            left_var = (left - left_mean).square().mean((2, 3), keepdim=True)
            right_var = (right - right_mean).square().mean((2, 3), keepdim=True)
            covariance = (left * right).mean((2, 3), keepdim=True) - left_mean * right_mean
            texture = (2.0 * covariance + c2) / (left_var + right_var + c2)
            structure_similarity += (alpha[index] * structure).sum(1, keepdim=True)
            texture_similarity += (beta[index] * texture).sum(1, keepdim=True)
        return 1.0 - (structure_similarity + texture_similarity).squeeze()

    def _residual_from_features(
        self,
        reference: list[Any],
        candidate: list[Any],
    ) -> np.ndarray:
        c1 = 1.0e-6
        c2 = 1.0e-6
        weight_sum = self._model.alpha.sum() + self._model.beta.sum()
        alpha = self._torch.split(self._model.alpha / weight_sum, self._model.chns, dim=1)
        beta = self._torch.split(self._model.beta / weight_sum, self._model.chns, dim=1)
        structure_rows: list[Any] = []
        texture_sketch = self._torch.zeros(
            self.residual_sketch_size,
            dtype=candidate[0].dtype,
            device=candidate[0].device,
        )
        offset = 0
        for index, (left, right) in enumerate(zip(reference, candidate, strict=True)):
            left_mean = left.mean((2, 3), keepdim=True)
            right_mean = right.mean((2, 3), keepdim=True)
            mean_scale = (left_mean.square() + right_mean.square() + c1).sqrt()
            structure_rows.append(
                alpha[index].clamp_min(0.0).sqrt()
                * (right_mean - left_mean)
                / mean_scale
            )

            left_centered = left - left_mean
            right_centered = right - right_mean
            left_var = left_centered.square().mean((2, 3), keepdim=True)
            right_var = right_centered.square().mean((2, 3), keepdim=True)
            spatial_count = max(int(left.shape[2]) * int(left.shape[3]), 1)
            texture_scale = (
                beta[index].clamp_min(0.0).sqrt()
                / ((left_var + right_var + c2) * spatial_count).sqrt()
            )
            texture_factor = texture_scale * (right_centered - left_centered)
            self._count_sketch_add(texture_sketch, texture_factor.flatten(), offset)
            offset += int(texture_factor.numel())

        structure = self._torch.cat([row.flatten() for row in structure_rows])
        residual = self._torch.cat((structure, texture_sketch))
        return residual.detach().cpu().numpy().astype(np.float32, copy=False)

    def _count_sketch_add(self, output: Any, values: Any, offset: int) -> None:
        table_count = self.residual_sketch_tables
        table_width = self.residual_sketch_size // table_count
        prime = 2_147_483_647
        seeds = (
            (1_000_003, 97_409, 1_000_033, 65_537),
            (1_000_037, 193_939, 1_000_081, 131_071),
            (1_000_099, 389_171, 1_000_117, 262_147),
            (1_000_121, 778_357, 1_000_169, 524_309),
        )
        cache_key = (
            int(values.numel()),
            int(offset),
            str(values.device),
            str(values.dtype),
        )
        projections = self._count_sketch_cache.get(cache_key)
        if projections is None:
            indices = self._torch.arange(
                int(values.numel()),
                dtype=self._torch.int64,
                device=values.device,
            ) + int(offset)
            generated: list[tuple[Any, Any]] = []
            for table_index in range(table_count):
                hash_a, hash_b, sign_a, sign_b = seeds[table_index % len(seeds)]
                bins = ((indices * hash_a + hash_b) % prime) % table_width
                parity = ((indices * sign_a + sign_b) % prime) & 1
                signs = self._torch.where(parity == 0, 1.0, -1.0).to(values.dtype)
                generated.append((bins, signs))
            projections = tuple(generated)
            self._count_sketch_cache[cache_key] = projections
        table_scale = math.sqrt(float(table_count))
        for table_index, (bins, signs) in enumerate(projections):
            start = table_index * table_width
            output[start : start + table_width].scatter_add_(
                0,
                bins,
                values * signs / table_scale,
            )


class ForegroundDISTSMaterialScorer(ForegroundDISTSScorer):
    """DISTS regularized by an aligned, foreground-only material score."""

    def score_image(
        self,
        reference_path: str | Path,
        candidate: Image.Image,
    ) -> DISTSMaterialScore:
        dists = super().score_image(reference_path, candidate)
        with Image.open(reference_path) as source:
            source.load()
            aligned_payload = score_cross_engine_pair_v3(source, candidate)
            aligned_residual = aligned_material_residual_features(source, candidate)
        aligned_score = (
            float(aligned_payload["score"])
            if aligned_payload.get("status") == "ok"
            and isinstance(aligned_payload.get("score"), (int, float))
            else 0.0
        )
        fit_score = (
            DISTS_MATERIAL_DISTS_WEIGHT * dists.fit_score
            + DISTS_MATERIAL_ALIGNED_WEIGHT * aligned_score
        )
        residual_features: tuple[float, ...] = ()
        if self.emit_residual_features:
            dists_scale = math.sqrt(DISTS_MATERIAL_DISTS_WEIGHT)
            material_scale = math.sqrt(DISTS_MATERIAL_ALIGNED_WEIGHT)
            residual_features = tuple(
                [dists_scale * value for value in dists.residual_features]
                + [material_scale * value for value in aligned_residual]
            )
        return DISTSMaterialScore(
            fit_score=max(0.0, min(1.0, float(fit_score))),
            dists=dists,
            aligned_material_score=max(0.0, min(1.0, aligned_score)),
            aligned_material_payload=aligned_payload,
            residual_features=residual_features,
        )


class ForegroundDISTSAlignedRGBScorer(ForegroundDISTSScorer):
    """DISTS plus a dense signed material residual in an object-normalized frame."""

    def __init__(
        self,
        *,
        aligned_rgb_image_size: int = DEFAULT_ALIGNED_RGB_IMAGE_SIZE,
        metric: str = DISTS_ALIGNED_RGB_METRIC,
        dists_weight: float = DISTS_ALIGNED_RGB_DISTS_WEIGHT,
        aligned_rgb_weight: float = DISTS_ALIGNED_RGB_PIXEL_WEIGHT,
        material_descriptor_weight: float = DISTS_ALIGNED_RGB_DESCRIPTOR_WEIGHT,
        local_contrast_weight: float = DISTS_ALIGNED_RGB_LOCAL_CONTRAST_WEIGHT,
        local_contrast_image_size: int = DEFAULT_LOCAL_CONTRAST_IMAGE_SIZE,
        residual_contract: str = (
            "perceptual_dists_rgb_local_contrast_and_material_descriptor_v6"
        ),
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.aligned_rgb_image_size = int(aligned_rgb_image_size)
        if self.aligned_rgb_image_size <= 0:
            raise ValueError("aligned_rgb_image_size must be positive")
        self.metric = str(metric)
        self.dists_weight = float(dists_weight)
        self.aligned_rgb_weight = float(aligned_rgb_weight)
        self.material_descriptor_weight = float(material_descriptor_weight)
        self.local_contrast_weight = float(local_contrast_weight)
        self.local_contrast_image_size = int(local_contrast_image_size)
        if self.local_contrast_image_size <= 0:
            raise ValueError("local contrast image size must be positive")
        if not math.isclose(
            self.dists_weight + self.aligned_rgb_weight + self.local_contrast_weight,
            1.0,
            abs_tol=1.0e-9,
        ):
            raise ValueError("aligned RGB and contrast score weights must sum to one")
        if min(
            self.dists_weight,
            self.aligned_rgb_weight,
            self.local_contrast_weight,
        ) < 0.0:
            raise ValueError("aligned RGB and contrast score weights must be nonnegative")
        if self.material_descriptor_weight < 0.0:
            raise ValueError("material descriptor weight must be nonnegative")
        self.aligned_rgb_residual_contract = str(residual_contract)

    def score_image(
        self,
        reference_path: str | Path,
        candidate: Image.Image,
    ) -> DISTSAlignedRGBScore:
        dists = super().score_image(reference_path, candidate)
        with Image.open(reference_path) as source:
            source.load()
            rgb_mae, rgb_residual = normalized_foreground_rgb_residual(
                source,
                candidate,
                image_size=self.aligned_rgb_image_size,
            )
            if self.local_contrast_weight > 0.0:
                local_contrast_distance, local_contrast_residual = (
                    normalized_foreground_local_contrast_residual(
                        source,
                        candidate,
                        image_size=self.local_contrast_image_size,
                    )
                )
            else:
                local_contrast_distance, local_contrast_residual = 0.0, ()
            material_residual = (
                aligned_material_residual_features(source, candidate)
                if self.emit_residual_features
                and self.material_descriptor_weight > 0.0
                else ()
            )
        rgb_score = float(math.exp(-2.0 * rgb_mae))
        local_contrast_score = float(
            math.exp(-LOCAL_CONTRAST_DISTANCE_SCALE * local_contrast_distance)
        )
        fit_score = (
            self.dists_weight * dists.fit_score
            + self.aligned_rgb_weight * rgb_score
            + self.local_contrast_weight * local_contrast_score
        )
        residual_features: tuple[float, ...] = ()
        if self.emit_residual_features:
            dists_scale = math.sqrt(self.dists_weight)
            rgb_scale = math.sqrt(self.aligned_rgb_weight)
            local_contrast_scale = (
                math.sqrt(self.local_contrast_weight) * LOCAL_CONTRAST_DISTANCE_SCALE
            )
            residual_features = tuple(
                [dists_scale * value for value in dists.residual_features]
                + [rgb_scale * value for value in rgb_residual]
                + [
                    math.sqrt(self.material_descriptor_weight) * value
                    for value in material_residual
                ]
                + [
                    local_contrast_scale * value
                    for value in local_contrast_residual
                ]
            )
        return DISTSAlignedRGBScore(
            fit_score=max(0.0, min(1.0, fit_score)),
            dists=dists,
            aligned_rgb_score=max(0.0, min(1.0, rgb_score)),
            normalized_rgb_mae=rgb_mae,
            residual_features=residual_features,
            aligned_rgb_image_size=self.aligned_rgb_image_size,
            metric=self.metric,
            dists_weight=self.dists_weight,
            aligned_rgb_weight=self.aligned_rgb_weight,
            local_contrast_score=max(0.0, min(1.0, local_contrast_score)),
            local_contrast_distance=local_contrast_distance,
            local_contrast_weight=self.local_contrast_weight,
            local_contrast_image_size=self.local_contrast_image_size,
            residual_contract=self.aligned_rgb_residual_contract,
        )


def normalized_foreground_rgb_residual(
    reference: Image.Image,
    candidate: Image.Image,
    *,
    image_size: int = DEFAULT_ALIGNED_RGB_IMAGE_SIZE,
) -> tuple[float, tuple[float, ...]]:
    """Return fixed-size signed RGB feedback after target-independent framing."""

    size = int(image_size)
    reference_canvas = _normalized_foreground_canvas(
        reference,
        image_size=size,
        allow_empty=False,
    )
    candidate_canvas = _normalized_foreground_canvas(
        candidate,
        image_size=size,
        allow_empty=True,
    )
    reference_rgba = reference_canvas.convert("RGBA")
    reference_core = trusted_intersection_core(
        reference_rgba,
        reference_rgba,
        erosion_iterations=1,
    )
    core_count = int(np.count_nonzero(reference_core))
    if core_count == 0:
        feature_count = size * size * 3
        return 1.0, tuple(0.0 for _ in range(feature_count))

    reference_rgb = np.asarray(reference_canvas, dtype=np.float32) / 255.0
    candidate_rgb = np.asarray(candidate_canvas, dtype=np.float32) / 255.0
    signed = candidate_rgb - reference_rgb
    rgb_mae = float(np.abs(signed[reference_core]).mean())
    scale = 1.0 / math.sqrt(float(core_count) * 3.0)
    dense = np.zeros_like(signed, dtype=np.float32)
    dense[reference_core] = signed[reference_core] * scale
    return rgb_mae, tuple(float(value) for value in dense.reshape(-1))


def normalized_foreground_local_contrast_residual(
    reference: Image.Image,
    candidate: Image.Image,
    *,
    image_size: int = DEFAULT_LOCAL_CONTRAST_IMAGE_SIZE,
) -> tuple[float, tuple[float, ...]]:
    """Compare generic highlight/shadow structure without asset color priors."""

    size = int(image_size)
    reference_descriptor = _local_contrast_descriptor(
        reference,
        image_size=size,
        allow_empty=False,
    )
    candidate_descriptor = _local_contrast_descriptor(
        candidate,
        image_size=size,
        allow_empty=True,
    )
    residual = candidate_descriptor - reference_descriptor
    distance = float(np.abs(residual).mean())
    return distance, tuple(float(value) for value in residual)


def _local_contrast_descriptor(
    image: Image.Image,
    *,
    image_size: int,
    allow_empty: bool,
) -> np.ndarray:
    canvas = _normalized_foreground_canvas(
        image,
        image_size=image_size,
        allow_empty=allow_empty,
    ).convert("RGBA")
    core = trusted_intersection_core(
        canvas,
        canvas,
        erosion_iterations=2,
    )
    if not np.any(core):
        return np.zeros(33, dtype=np.float32)

    rgb = np.asarray(canvas, dtype=np.float32)[:, :, :3] / 255.0
    luma = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    local_quantiles = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
    rows: list[float] = []
    canvas_rgb = canvas.convert("RGB")
    for radius in (1.0, 3.0, 6.0):
        blurred = np.asarray(
            canvas_rgb.filter(ImageFilter.GaussianBlur(radius=radius)),
            dtype=np.float32,
        ) / 255.0
        blurred_luma = (
            0.2126 * blurred[:, :, 0]
            + 0.7152 * blurred[:, :, 1]
            + 0.0722 * blurred[:, :, 2]
        )
        rows.extend(
            float(value)
            for value in np.quantile(luma[core] - blurred_luma[core], local_quantiles)
        )

    gradient_y, gradient_x = np.gradient(luma)
    gradient = np.hypot(gradient_x, gradient_y)[core]
    rows.extend(
        float(value)
        for value in np.quantile(gradient, (0.25, 0.50, 0.75, 0.90, 0.95, 0.99))
    )
    return np.asarray(rows, dtype=np.float32)


def aligned_material_residual_features(
    reference: Image.Image,
    candidate: Image.Image,
    *,
    grid_size: int = DEFAULT_MATERIAL_RESIDUAL_GRID_SIZE,
) -> tuple[float, ...]:
    """Return signed, geometry-aware color residuals for inverse fitting.

    The scalar material score is robust and deliberately compact. A Jacobian
    optimizer additionally needs signed feedback telling it which colors and
    regions moved in the wrong direction. These features use the same eroded
    foreground intersection as the aligned material score, so background and
    silhouette-only differences cannot dominate the update.
    """

    reference_rgba = reference.convert("RGBA")
    candidate_rgba = candidate.convert("RGBA")
    if candidate_rgba.size != reference_rgba.size:
        candidate_rgba = candidate_rgba.resize(
            reference_rgba.size,
            Image.Resampling.BILINEAR,
        )
    core = trusted_intersection_core(
        reference_rgba,
        candidate_rgba,
        erosion_iterations=2,
    )
    size = max(1, int(grid_size))
    feature_count = size * size * 3 + 23
    core_count = int(np.count_nonzero(core))
    if core_count == 0:
        return tuple(0.0 for _ in range(feature_count))

    reference_rgb = np.asarray(reference_rgba, dtype=np.float32)[:, :, :3] / 255.0
    candidate_rgb = np.asarray(candidate_rgba, dtype=np.float32)[:, :, :3] / 255.0
    signed = candidate_rgb - reference_rgb
    height, width = core.shape
    rows: list[float] = []
    for grid_y in range(size):
        y0 = grid_y * height // size
        y1 = (grid_y + 1) * height // size
        for grid_x in range(size):
            x0 = grid_x * width // size
            x1 = (grid_x + 1) * width // size
            cell_mask = core[y0:y1, x0:x1]
            count = int(np.count_nonzero(cell_mask))
            if count == 0:
                rows.extend((0.0, 0.0, 0.0))
                continue
            cell_mean = signed[y0:y1, x0:x1][cell_mask].mean(axis=0)
            area_weight = math.sqrt(count / core_count)
            rows.extend(float(value * area_weight) for value in cell_mean)

    reference_core = reference_rgb[core]
    candidate_core = candidate_rgb[core]
    quantiles = (0.10, 0.25, 0.50, 0.75, 0.90)
    quantile_scale = 0.5 / math.sqrt(len(quantiles))
    for channel in range(3):
        reference_values = np.quantile(reference_core[:, channel], quantiles)
        candidate_values = np.quantile(candidate_core[:, channel], quantiles)
        rows.extend(
            float((candidate_value - reference_value) * quantile_scale)
            for reference_value, candidate_value in zip(
                reference_values,
                candidate_values,
                strict=True,
            )
        )

    reference_luma = (
        0.2126 * reference_core[:, 0]
        + 0.7152 * reference_core[:, 1]
        + 0.0722 * reference_core[:, 2]
    )
    candidate_luma = (
        0.2126 * candidate_core[:, 0]
        + 0.7152 * candidate_core[:, 1]
        + 0.0722 * candidate_core[:, 2]
    )
    reference_luma_quantiles = np.quantile(reference_luma, quantiles)
    candidate_luma_quantiles = np.quantile(candidate_luma, quantiles)
    rows.extend(
        float((candidate_value - reference_value) * quantile_scale)
        for reference_value, candidate_value in zip(
            reference_luma_quantiles,
            candidate_luma_quantiles,
            strict=True,
        )
    )

    reference_opponent = _chroma_opponent_descriptor(reference_core)
    candidate_opponent = _chroma_opponent_descriptor(candidate_core)
    rows.extend(
        float((candidate_value - reference_value) / math.sqrt(3.0))
        for reference_value, candidate_value in zip(
            reference_opponent,
            candidate_opponent,
            strict=True,
        )
    )
    return tuple(rows)


def _chroma_opponent_descriptor(rgb: np.ndarray) -> tuple[float, float, float]:
    maximum = rgb.max(axis=1)
    minimum = rgb.min(axis=1)
    return (
        float((maximum - minimum).mean()),
        float((rgb[:, 0] - 0.5 * (rgb[:, 1] + rgb[:, 2])).mean()),
        float((rgb[:, 1] - rgb[:, 2]).mean()),
    )


__all__ = [
    "DEFAULT_DISTS_DEVICE",
    "DEFAULT_DISTS_IMAGE_SIZE",
    "DEFAULT_DISTS_RESIDUAL_SKETCH_SIZE",
    "DEFAULT_DISTS_RESIDUAL_SKETCH_TABLES",
    "DEFAULT_DISTS_TORCH_THREADS",
    "DEFAULT_ALIGNED_RGB_IMAGE_SIZE",
    "DEFAULT_LOCAL_CONTRAST_IMAGE_SIZE",
    "DEFAULT_MATERIAL_RESIDUAL_GRID_SIZE",
    "DISTS_MATERIAL_RESIDUAL_CONTRACT",
    "DISTS_ALIGNED_RGB_DISTS_WEIGHT",
    "DISTS_ALIGNED_RGB_DESCRIPTOR_WEIGHT",
    "DISTS_ALIGNED_RGB_LOCAL_CONTRAST_WEIGHT",
    "DISTS_ALIGNED_RGB_METRIC",
    "DISTS_ALIGNED_RGB_V3_METRIC",
    "DISTS_ALIGNED_RGB_V5_DISTS_WEIGHT",
    "DISTS_ALIGNED_RGB_V5_METRIC",
    "DISTS_ALIGNED_RGB_V5_PIXEL_WEIGHT",
    "DISTS_ALIGNED_RGB_PIXEL_WEIGHT",
    "DISTS_ALIGNED_RGB_V3_DISTS_WEIGHT",
    "DISTS_ALIGNED_RGB_V3_DESCRIPTOR_WEIGHT",
    "DISTS_ALIGNED_RGB_V3_PIXEL_WEIGHT",
    "DISTS_RESIDUAL_CONTRACT",
    "DISTS_METRIC",
    "DISTS_MATERIAL_ALIGNED_WEIGHT",
    "DISTS_MATERIAL_DISTS_WEIGHT",
    "DISTS_MATERIAL_METRIC",
    "DISTSScore",
    "DISTSAlignedRGBScore",
    "DISTSMaterialScore",
    "ForegroundDISTSScorer",
    "ForegroundDISTSAlignedRGBScorer",
    "ForegroundDISTSMaterialScorer",
    "aligned_material_residual_features",
    "normalized_foreground_tensor",
    "normalized_foreground_rgb_residual",
    "normalized_foreground_local_contrast_residual",
]
