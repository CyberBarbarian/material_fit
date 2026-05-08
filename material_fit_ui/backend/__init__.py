"""Material Fit UI backend package.

Stage A goal: read-only visualization of existing
``tools/material_fit/output/<case>/`` artefacts. The backend wraps
file-system access with a tiny FastAPI service so the Vue frontend can
load case overviews, iteration timelines, diff analyses and image
files without learning the on-disk layout.
"""

__all__ = ["main", "case_loader"]
