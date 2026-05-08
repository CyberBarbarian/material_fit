"""Material auto-fit tool package.

The package is split by responsibility:

- ``unity``: Unity-side material and shader data export.
- ``laya``: Laya-side shader/material IO and render invocation.
- ``vision``: screenshot comparison and image scoring.
- ``optimizer``: parameter planning and search algorithms.
- ``shared``: common data models and reporting helpers.
"""

__all__ = [
    "unity",
    "laya",
    "vision",
    "optimizer",
    "shared",
]
