# Examples

This directory contains a small fish material fitting example copied from the Volcano render environment.

## Fish Laya Project

```text
examples/fish_laya_project/
```

This is a minimal Laya project for the fish asset used in the material fitting experiments. Important files:

```text
assets/resources/game.ls
assets/resources/model/1504/prefab/1504.lh
assets/resources/model/1504/mat/1504_body.lmat
assets/resources/model/1504/shader/
assets/resources/model/1504/tex/
assets/resources/shader/Custom_low.shader
```

The project keeps the Laya `library/` resource database because the converted `.lm`, `.lh`, `.ktx`, shader, and animation resources are needed by the runtime/editor project. Machine-local UI state such as `.chat/`, `local/`, and temporary library cache folders was removed.

## Unity References

```text
examples/fish_unity_refs/
```

The reference set contains eight PNG views:

```text
laya_v000_yaw0_pitch0.png
laya_v001_yaw45_pitch0.png
laya_v002_yaw90_pitch0.png
laya_v003_yaw135_pitch0.png
laya_v004_yaw180_pitch0.png
laya_v005_yaw225_pitch0.png
laya_v006_yaw270_pitch0.png
laya_v007_yaw315_pitch0.png
```

Despite the `laya_v...` filenames, this folder is the target reference set used by the optimizer. When creating a UI project, set the Unity reference directory to `examples/fish_unity_refs` and set the Laya material path to `examples/fish_laya_project/assets/resources/model/1504/mat/1504_body.lmat`.

## Local Fast Path

Start the no-IDE runtime renderer from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_local_laya_runtime_renderer.ps1
```

Then create or run a Material Fit project that points to the files above. The
runtime renderer loads `examples/fish_laya_project/assets/resources/game.ls` by
default through a local static server, so the no-IDE path starts on the real fish
scene without extra project arguments.
