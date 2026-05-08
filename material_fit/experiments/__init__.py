"""Reproducible experiments for the material-fitting research roadmap.

Each experiment is a single self-contained script. They write all
artifacts (results.json, plots, .txt convergence logs) into a sibling
``experiments_out/`` directory keyed by the experiment name + timestamp,
so re-running an experiment never silently clobbers old data.
"""
