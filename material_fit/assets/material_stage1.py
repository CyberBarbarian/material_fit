"""Asset adapters for PNG-only human-reference Stage 1 fitting."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from material_fit.assets.fish_scene import resolve_fish_scene_assets
from material_fit.assets.material_phase05 import MaterialAssetSpec, resolve_material_asset


TURTLE_HUMAN_MATERIAL = Path(
    "examples/turtle_laya_project/assets/resources/model/1506/mat/1506_mat.lmat"
)
CROCODILE_HUMAN_MATERIAL = Path(
    "examples/crocodile_laya_project/assets/1503/mat/1503_body.lmat"
)


@dataclass(frozen=True)
class MaterialStage1AssetSpec:
    asset_id: str
    project_root: Path
    scene_path: Path
    shader_path: Path
    start_material_path: Path
    target_material_path: Path
    profile: dict[str, Any]

    def manifest(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["profile"] = copy.deepcopy(self.profile)
        for key in (
            "project_root",
            "scene_path",
            "shader_path",
            "start_material_path",
            "target_material_path",
        ):
            payload[key] = str(payload[key])
        return payload

    def phase05_spec(self, *, target_material_path: Path | None = None) -> MaterialAssetSpec:
        return MaterialAssetSpec(
            asset_id=self.asset_id,
            project_root=self.project_root,
            scene_path=self.scene_path,
            shader_path=self.shader_path,
            target_material_path=target_material_path or self.target_material_path,
            profile=copy.deepcopy(self.profile),
        )


def resolve_material_stage1_asset(
    repo_root: Path,
    asset_id: str,
    *,
    profile_path: str | Path | None = None,
    start_material_path: str | Path | None = None,
    target_material_path: str | Path | None = None,
    shader_path: str | Path | None = None,
) -> MaterialStage1AssetSpec:
    """Resolve files only; this adapter does not select optimizer behavior."""

    base = resolve_material_asset(
        repo_root,
        asset_id,
        profile_path=profile_path,
        target_material_path=start_material_path,
        shader_path=shader_path,
    )
    if target_material_path:
        target = Path(target_material_path).expanduser().resolve()
    elif base.asset_id == "fish_1504":
        target = resolve_fish_scene_assets(repo_root).human_adjusted_material_path
    elif base.asset_id == "turtle_1506":
        target = (repo_root / TURTLE_HUMAN_MATERIAL).resolve()
    elif base.asset_id == "crocodile_1503":
        target = (repo_root / CROCODILE_HUMAN_MATERIAL).resolve()
    else:
        raise ValueError(f"unsupported Stage 1 asset: {base.asset_id}")
    if not target.is_file():
        raise FileNotFoundError(f"Stage 1 target material is unavailable: {target}")
    return MaterialStage1AssetSpec(
        asset_id=base.asset_id,
        project_root=base.project_root,
        scene_path=base.scene_path,
        shader_path=base.shader_path,
        start_material_path=base.target_material_path,
        target_material_path=target,
        profile=copy.deepcopy(base.profile),
    )
