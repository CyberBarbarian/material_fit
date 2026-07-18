# Stage 2 Unity References

These are direct Unity 2020.3.47f1c1 exports for the three packaged Laya
models. They are isolated from the Stage 1 Laya-oracle targets and from the
older Pattern16 fish references.

| Directory | Unity prefab | Model |
| --- | --- | --- |
| `1503/` | `Assets/Fishes/FishBoss/Prefab/boss_1503/1503.prefab` | crocodile |
| `1504/` | `Assets/Fishes/FishBoss/Prefab/boss_1504/1504.prefab` | fish |
| `1506/` | `Assets/Fishes/FishBoss/Prefab/boss_1506/1506.prefab` | turtle |

Every directory contains eight `900x700` transparent PNGs and the metadata
written by `material_fit/unity/unity_multiview_capture.cs` version 1.1.0. The
tracked metadata keeps the Unity asset path and capture geometry but replaces
the exporter machine's absolute output paths with local file names.

The source archives received on 2026-07-18 were:

- `测试模型.zip`: SHA256
  `a673bbbbd39171772886e7e9893dcd00c1c729f7c852cb3de9bb05dc56383e36`
- `unity_multiview_capture.zip`: SHA256
  `725938d6719a1abdea338d7b44c9749ec444abcdb915371088e33b82856fb6c`

Run the structural audit with:

```bash
python -m material_fit.experiments.material_cross_engine_stage2_intake \
  --asset fish \
  --output-dir artifacts/stage2_fish_intake
```

The current 1503 and 1504 exports contain canvas-edge clipping in some views.
The validator records this separately from file validity. Do not start material
optimization until the geometry gate has passed or the affected views have
been explicitly excluded by a recorded Stage 2 policy.
