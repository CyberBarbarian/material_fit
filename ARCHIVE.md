# Material Fit archival snapshot

Material Fit was retired from active development and the server-migration
working set on 2026-10-20 at the owner's request. This repository preserves the
code, packaged assets, configuration, installation recipes and documented
experimental progress. Future work requires an explicit decision to resume it.

The fixed archive tag is `archive-2026-10-20`. The preceding published source
revision is `946325b39f9f105601ee01ee91af2685bcd2c73c`.

## Preserved project

- The shared V86 single-view policy and its hash-checked child configurations.
- Stage 1 human-reference fitting, Phase 0.5 recovery, Stage 2 Unity-to-Laya
  fitting and the retained Pattern16 baseline.
- Python source and tests, Windows/Linux wrappers, dependency lockfiles and
  bootstrap/doctor commands.
- Tracked example assets and Unity reference PNGs, plus the existing vendored
  LayaAir runtime files and their provenance.
- Architecture, input-boundary rules, accepted results and known limitations in
  [`material_fit/docs/`](material_fit/docs/).

The archive does not introduce a new project or third-party license. Existing
component provenance and any included license files remain unchanged.

## Last documented accepted evidence

The detailed records and their original run identifiers are in
[`EXPERIMENTS.md`](material_fit/docs/EXPERIMENTS.md),
[`SINGLE_VIEW_THREE_STAGE.md`](material_fit/docs/SINGLE_VIEW_THREE_STAGE.md) and
[`STAGE2.md`](material_fit/docs/STAGE2.md).

The accepted Linux V6 turtle work recorded on 2026-07-22 includes:

| Workflow | Recorded result |
| --- | --- |
| Phase 0.5 | Two independent starts reached V6 scores 0.981888 and 0.980053. |
| Stage 1 | V6 score 0.764382 to 0.953396 within the declared material budget. |
| Stage 2 | Optimized V6 score 0.833833; best/start DISTS-distance ratio 0.751708. |

These results retain their original mode, platform and acceptance boundaries.
They do not establish a new Windows V6 end-to-end acceptance or acceptance of
the clipped fish/crocodile multi-view Unity references. No renderer run,
training or benchmark was launched for this archival update.

The original selected [Stage 1 comparison](archive/2026-10-20/stage1-target-start-best.png)
and [Stage 2 comparison](archive/2026-10-20/stage2-unity-start-human-best.png) accompany
this snapshot. [Provenance](archive/2026-10-20/provenance.json) identifies their bytes
and the private raw reports without publishing original machine details.

## Independent data archive

The owner's private companion repository,
[`CyberBarbarian/material_fit-archive`](https://github.com/CyberBarbarian/material_fit-archive),
preserves the selected raw research data independently of the original server.
Its `archive-2026-10-20` release holds the historical maintained source snapshot,
accepted V6 evidence, retained archive payloads and their restore metadata, and
the exact perceptual-model data used by the recorded workflow. Chunk manifests,
original-file SHA-256 values and reconstruction instructions accompany the data.

The private data archive is for provenance and historical recovery. It is not a
dependency of the packaged public source installation. Access requires the
owner's authorization; original server paths are source labels, not the backup.

Virtual environments, Node/Chromium installations and compiler/package caches
are excluded. No claim is made that every disposable intermediate from every
historical run was retained. The manifest identifies the exact preserved set.

## Restore

```bash
git clone --branch archive-2026-10-20 https://github.com/CyberBarbarian/material_fit.git
cd material_fit
```

Use the README's platform bootstrap and doctor instructions only when resuming
work deliberately. Archiving establishes preservation of source and records;
it does not reinstall or revalidate a runtime on a new host.
