# material_fit

This directory contains the algorithm and CLI layer for Material Fit Inspector:

- `.lmat` parsing, writing, backup, and verification.
- Unity and Laya shader/material parsing helpers.
- Black-box optimization strategies.
- Image scoring and diff analysis.
- Laya capture bridge support.
- Pytest coverage for the core workflow.

Use the repository root [README.md](../README.md) for environment setup and the recommended fast Laya runtime path.

## CLI

Run commands from the repository root:

```powershell
python -m material_fit.fit_material --help
```

Typical optimization command:

```powershell
python -m material_fit.fit_material `
  --config material_fit/output/<project_id>/runs/<run_id>/fit_config.json `
  --auto-adjust `
  --iterations 100 `
  --target-score 0.98 `
  --optimizer semantic_group `
  --fit-score-mode human_accept `
  --apply-lmat
```

Do not run `python material_fit/fit_material.py` directly; module mode keeps package imports stable. The older `tools.material_fit...` namespace remains as a compatibility alias for existing configs.

## Tests

```powershell
python -m pytest material_fit/tests -q
```

## Main Subdirectories

```text
material_fit/
├── auto_adjust/       # Auto-adjust orchestration and scoring helpers
├── docs/              # Architecture, scoring, capture, and experiment notes
├── experiments/       # Benchmark and research scripts
├── laya/              # Laya shader parsing and .lmat IO
├── laya_capture/      # Queue daemon, HTTP bridge, runtime renderer
├── optimizer/         # Search strategies and parameter encoding
├── shared/            # Shared models and report helpers
├── tests/             # Pytest suite
├── unity/             # Unity shader/material helpers
└── vision/            # Image scoring and diff analysis
```
