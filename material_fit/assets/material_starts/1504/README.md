# 1504 Material Start Registry

This directory records material-start candidates for the maintained 1504 fish
experiments without changing the live Laya scene binding.

## Active Finetune Start

The maintained finetune experiment now uses:

```text
active/1504_new_test.lmat
sha256: 9ba22d81c3f800ebdb380314e83b59dc95334bbdf798b0be6849173a62745e9c
source: user-provided WeChat file 1504_new_test(2).lmat, 2026-07
```

Inspection and render probe:

```text
type: Custom/FishStandar_Low
texture_count: 6
param_count: 56
render_probe: artifacts/render_new_start2_fishshader_20260709_195828
contact_sheet: artifacts/render_new_start2_fishshader_20260709_195828/new_start2_raw_scene_contact_sheet.png
```

The Laya scene still binds the source material UUID
`4adc3c2d-41bc-4cad-87df-77ecfb84a558`. The runtime runner keeps that scene
binding and uses this active `.lmat` as the optimizer start material.

## Archived Previous Start

```text
archive/fish_jxs_test_legacy_20260709.lmat
sha256: 9521e1e1671dffdfcc67c07e4dd95314155bf7ed541768ce0ca7e158c0a1f7d3
role: previous scene-bound finetune start
```

## Human-Adjusted Target

```text
human_adjusted/1504_body.lmat
sha256: 01a77e868d6f0d8f317e5ff64022781fec27a95fee1091a7f50a6895116dd0a8
role: human-adjusted finished material; offline reference for search-space design and visual evaluation
```

This file is not an optimization start for maintained finetune runs. The
maintained optimizers must not load it at runtime as a teacher target or
proposal direction. It is also not the default Phase 1 Laya-oracle target,
because its shader defines differ from the active/source same-define parameter
space in the current runtime.

## Rejected Candidate

```text
rejected/1504_new_test_unlit_rejected_20260709.lmat
sha256: 1d9b0741a0bbaaf0572d51b9c9d9bf3ad4dcea917712955db95a4ff029c815aa
reason: Unlit material; rendered as all-white/empty in the current 1504 fish scene.
```
