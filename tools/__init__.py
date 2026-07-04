"""Compatibility namespace for standalone Material Fit checkouts.

The source tree is often used directly as ``material_fit/`` plus
``material_fit_ui/`` at the repository root, while older docs and imports
refer to ``tools.material_fit``.  This package makes both layouts work.
"""

from __future__ import annotations

import importlib
import sys


def _alias_package(name: str) -> None:
    module = importlib.import_module(name)
    sys.modules[f"{__name__}.{name}"] = module
    globals()[name] = module


_alias_package("material_fit")
_alias_package("material_fit_ui")

__all__ = ["material_fit", "material_fit_ui"]
