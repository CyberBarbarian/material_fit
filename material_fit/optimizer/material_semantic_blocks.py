"""Asset-independent semantic blocks for the shared material shader space."""

from __future__ import annotations


MATERIAL_SEMANTIC_BLOCKS = (
    (
        "rim",
        ("u_RimColor", "u_RimIntensity", "u_RimWidth", "u_RimOffet"),
        0.18,
    ),
    (
        "specular",
        (
            "u_SpecularColor",
            "u_SpecularIntensity",
            "u_SpecularPower",
            "u_SpecularThreshold",
            "u_SpecularSmoothness",
            "u_SpeOffet",
        ),
        0.14,
    ),
    (
        "tone_shadow",
        (
            "u_Color",
            "u_Contrast",
            "u_HueShift",
            "u_EmissionPow",
            "u_ShadowSmoothness",
            "u_ShadowColor1",
            "u_ShadowThreshold1",
        ),
        0.12,
    ),
    (
        "base_surface",
        (
            "u_GammaPower",
            "u_Saturation",
            "u_TexPower",
            "u_AoPower",
            "u_IndirectStrength",
            "u_NormalScale",
            "u_ReflectColor",
        ),
        0.12,
    ),
)


MATERIAL_SEMANTIC_BLOCK_BY_NAME = {
    name: (tuple(param_names), float(sigma))
    for name, param_names, sigma in MATERIAL_SEMANTIC_BLOCKS
}


__all__ = ["MATERIAL_SEMANTIC_BLOCKS", "MATERIAL_SEMANTIC_BLOCK_BY_NAME"]
