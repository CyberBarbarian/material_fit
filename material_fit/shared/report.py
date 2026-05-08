from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import FitStage, ShaderInfo


def write_summary_report(
    output_path: str | Path,
    laya_shader: ShaderInfo | None,
    unity_shader: ShaderInfo | None,
    laya_material_params: dict[str, Any],
    stages: list[FitStage],
    extra: dict[str, Any] | None = None,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    adjustment_result = extra.get("adjustment_result") if isinstance(extra, dict) else None
    lines = [
        "# Material Fit Report",
        "",
        "## Input Summary",
        "",
        f"- Laya shader: `{laya_shader.path if laya_shader else ''}`",
        f"- Laya shader params: {len(laya_shader.params) if laya_shader else 0}",
        f"- Unity shader: `{unity_shader.path if unity_shader else ''}`",
        f"- Unity shader params: {len(unity_shader.params) if unity_shader else 0}",
        f"- Laya material params: {len(laya_material_params)}",
        "",
        "## Optimization Algorithm",
        "",
        "当前自动调优使用的是**分阶段、启发式、闭环反馈调参算法**，不是神经网络训练，也不是随机搜索。核心流程如下：",
        "",
        "1. 对 Unity 参考图和 Laya 候选图计算图像差异，主停止分数为 `fit_score = 1 - RGB_MAE`，越高越好。",
        "2. 图像分析会额外按材质语义拆分通道，例如基础色/主贴图、暗部遮蔽、高光/光滑度、环境反射/Matcap、Fresnel/自发光、全局 HSV/对比度。",
        "3. 调参顺序采用 coarse-to-fine：先改大面积基础色和亮度，再改暗部/漫反射，然后改高光、反射、边缘光、自发光，最后做全局颜色微调。",
        "4. 每轮只选择当前最需要优化的阶段，读取该阶段相关通道的 `candidate - reference` signed bias，并对相关 shader 参数做反向修正。",
        "5. 每轮增益会衰减：`gain = max(0.35, 0.72 * 0.86^iteration)`，避免后期过冲。",
        "6. 如果启用 `--apply-lmat --capture-screen-after-apply`，每轮会真实写入 Laya `.lmat`，等待重渲染，截取新 Laya 图，然后下一轮用新图继续分析。",
        "",
        "该算法可理解为：**基于材质语义分组的坐标下降/反馈控制器**。它不是穷举所有参数，而是按阶段只调整少量高影响参数。",
        "",
        "## Stage Plan",
        "",
    ]
    for stage in stages:
        lines.append(f"- **{stage.name}**: {', '.join(stage.params)}")
        if getattr(stage, "description", ""):
            lines.append(f"  - {stage.description}")
    if isinstance(adjustment_result, dict):
        lines.extend(_format_adjustment_result(adjustment_result))
    if extra:
        lines.extend(["", "## Extra", "", "```json", json.dumps(extra, ensure_ascii=False, indent=2), "```"])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_adjustment_result(adjustment_result: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "## Auto-adjust Result",
        "",
        f"- Status: `{adjustment_result.get('status', '')}`",
        f"- Target fit score: `{adjustment_result.get('target_score', '')}`",
        f"- Best diff score / RGB_MAE: `{adjustment_result.get('best_score', '')}`",
        f"- Best fit score: `{adjustment_result.get('best_fit_score', '')}`",
        f"- State file: `{adjustment_result.get('state_path', '')}`",
        "",
        "## Per-iteration Parameter Changes",
        "",
    ]
    iterations = adjustment_result.get("iterations", [])
    if not isinstance(iterations, list) or not iterations:
        lines.append("No auto-adjust iterations were recorded.")
        return lines

    for item in iterations:
        if not isinstance(item, dict):
            continue
        decision = item.get("decision", {}) if isinstance(item.get("decision"), dict) else {}
        changes = decision.get("changes", []) if isinstance(decision.get("changes"), list) else []
        stage = decision.get("stage", {}) if isinstance(decision.get("stage"), dict) else {}
        capture = item.get("screen_capture_after_apply", {}) if isinstance(item.get("screen_capture_after_apply"), dict) else {}
        lines.extend(
            [
                f"### Iteration {item.get('iteration')}",
                "",
                f"- Input candidate image: `{_get_nested(item, 'input_pair', 'candidate')}`",
                f"- Diff score / RGB_MAE before adjustment: `{item.get('diff_score_before', '')}`",
                f"- Fit score before adjustment: `{item.get('fit_score_before', '')}`",
                f"- Selected stage: `{item.get('selected_stage', '')}`",
                f"- Stop reason: `{decision.get('stop_reason', '')}`",
            ]
        )
        if stage:
            lines.extend(
                [
                    f"- Stage description: {stage.get('description', '')}",
                    f"- Stage adjustable params: `{', '.join(stage.get('params', []))}`",
                    f"- Iteration gain: `{decision.get('iteration_gain', '')}`",
                ]
            )
        if decision.get("applied_lmat"):
            lines.append(f"- Applied Laya material: `{decision.get('applied_lmat')}`")
        if decision.get("backup_lmat"):
            lines.append(f"- Backup material: `{decision.get('backup_lmat')}`")
        if capture:
            lines.append(f"- Captured refreshed Laya image: `{capture.get('output_path', '')}`")
            if capture.get("region"):
                lines.append(f"- Capture region: `{capture.get('region')}`")
        lines.append("")
        if changes:
            lines.append("| Param | Old | New | Reason |")
            lines.append("|---|---:|---:|---|")
            for change in changes:
                if not isinstance(change, dict):
                    continue
                lines.append(
                    "| "
                    + str(change.get("param", ""))
                    + " | `"
                    + _compact_json(change.get("old"))
                    + "` | `"
                    + _compact_json(change.get("new"))
                    + "` | "
                    + str(change.get("reason", ""))
                    + " |"
                )
        else:
            lines.append("No parameter changes in this iteration.")
        lines.append("")
    return lines


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _get_nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return current if current is not None else ""
