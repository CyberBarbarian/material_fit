from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


JsonDict = dict[str, Any]


@dataclass
class ShaderParam:
    """A parameter exposed by a shader for material editing."""

    name: str
    param_type: str
    default: Any = None
    display_name: Optional[str] = None
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    hidden: Optional[str] = None
    source: str = ""


@dataclass
class ShaderDefine:
    """A shader feature switch exposed by the shader."""

    name: str
    define_type: str = "bool"
    default: Any = False
    position: Optional[str] = None


@dataclass
class ShaderInfo:
    """Parsed shader metadata."""

    path: Path
    name: str = ""
    params: list[ShaderParam] = field(default_factory=list)
    defines: list[ShaderDefine] = field(default_factory=list)


@dataclass
class FitStage:
    """A coarse optimization stage with a limited parameter set."""

    name: str
    params: list[str]
    description: str = ""


@dataclass
class CandidateResult:
    """A rendered candidate and its score."""

    params: JsonDict
    score: float
    artifacts: JsonDict = field(default_factory=dict)
