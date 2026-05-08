# Laya 材质自动拟合工具：大模型上下文与提示词规范

> ⚠️ **历史文档**（2025 年版本）。本文规划了把工具与 LLM API 结合的提示词规范。当前实现里 **LLM 辅助还没接入主流程**（`LlmAssistView.vue` 仅占位）。本文留作未来接入 LLM 时的参考资料。**当前已 ship 的能力以 [`docs/ExperimentLog.md`](docs/ExperimentLog.md) §0 为准**。新接手 agent 请先读 [`AGENT_ONBOARDING.md`](AGENT_ONBOARDING.md)。

本文档用于把当前依赖项目开发者/人工助手理解的“上下文判断能力”，沉淀为后续可接入大模型 API 的独立工具提示词规范。目标是让工具在脱离完整工程对话上下文后，仍能让模型理解：我们要解决什么问题、输入数据代表什么、应该如何映射 Unity 与 Laya 材质参数、哪些结论必须保守输出、以及最终应该产出什么。

## 1. 工具目标

本工具的目标不是简单复制同名参数，而是把 Unity 中某个角色/鱼/炮台等美术资源的材质效果，尽量迁移和拟合到 LayaAir 项目的自定义 Shader 材质 `.lmat` 中。

典型场景：

1. Unity 原工程使用自定义 Shader，例如 `CustomStandardV2`。
2. Unity 材质实例中包含大量真实调参结果，例如基础色倍率、自发光、金属/光滑度 remap、Rim、HSV、对比度、流光、受击色等。
3. Laya 项目中有目标材质，例如 `Custom/Fish/FishStandard` 的 `.lmat`。
4. 两边 Shader 不是 1:1 实现，参数名、贴图语义、宏开关和渲染公式都可能不同。
5. 工具需要基于 Unity 导出 JSON、Laya Shader、Laya 材质和可选截图评分，生成更接近 Unity 原版的 Laya 材质参数。

## 2. 当前工具中大模型的职责

大模型不应替代确定性解析器，也不应凭空猜测资源。它负责的是“语义映射与策略判断”。

### 2.1 确定性工具负责

- 从 Unity 导出材质实例真实数据：float/range/color/vector/texture/keyword/renderQueue/render state。
- 解析 Laya Shader 的 `uniformMap`、`defines`、默认值、参数类型和隐藏条件。
- 读取、备份、改写 Laya `.lmat`。
- 查询 Laya 项目资源中是否存在可绑定贴图。
- 执行 JSON 校验、类型校验、资源引用校验。
- 可选：渲染截图、图像对齐、评分、输出差异图。

### 2.2 大模型负责

- 判断 Unity 参数的渲染语义，例如 `_ColorScale` 是基础色强度倍率，`_EmissionColor` 是 HDR 自发光色，`_RimColor/_RimPower/_RimSpread/_RimOffset` 是边缘光，`_AdjustSaturation` 是 HSV/Photoshop 类后处理。
- 在 Laya Shader 可用参数中寻找最接近的目标参数，例如把 Unity Rim 映射到 Laya Fresnel。
- 判断是否需要开启 Laya define，例如 `EMISSION`、`ADJUST_HSV`、`ENABLE_CONTRAST`。
- 在 Shader 公式不一致时给出保守近似，而不是声称完全等价。
- 判断无法映射、资源缺失、语义冲突、风险参数，并在报告中明确说明。
- 生成结构化的材质修改建议和解释报告。

## 3. 大模型输入包建议

接入大模型时，不应只给一个 Unity JSON。建议工具组装一个完整的 `LLMContextPackage`，包含以下内容。

```jsonc
{
  "task": {
    "goal": "fit_unity_material_to_laya_lmat",
    "asset_kind": "fish|boss|pet|cannon|unknown",
    "quality_target": "closer_to_unity_reference",
    "allow_shader_edit": false,
    "allow_texture_rebind": true,
    "allow_missing_resource_guess": false
  },
  "unity_material": {
    "material_name": "fish_1580_lvbu_diff_01",
    "shader_name": "CustomStandardV2",
    "source_path": "Assets/.../fish_1580_lvbu_diff_01.mat",
    "floats": {},
    "colors": {},
    "vectors": {},
    "textures": {},
    "keywords": [],
    "render_queue": 2000,
    "unsupported_properties": [],
    "missing_properties": []
  },
  "laya_shader": {
    "shader_name": "Custom/Fish/FishStandard",
    "uniforms": {},
    "defines": {},
    "important_formula_notes": []
  },
  "laya_material": {
    "path": "assets/resources/play/fish/1580/mat/1580_body.lmat",
    "props": {},
    "textures": []
  },
  "resource_lookup": {
    "texture_candidates": [],
    "missing_unity_textures": []
  },
  "optional_visual_feedback": {
    "unity_reference_images": [],
    "laya_candidate_images": [],
    "scores": []
  }
}
```

## 4. 必须提供给模型的 Laya Shader 语义摘要

独立工具不能假设模型已经看过项目代码。调用模型前，应由工具从 Shader 解析或手写知识库中注入当前目标 Laya Shader 的语义摘要。

以 `Custom/Fish/FishStandard` 为例，至少应注入：

- `u_BaseMap`：基础色贴图。
- `u_BaseColor`：基础色乘色，会直接乘到 albedo。
- `u_Gamma_Power`：对 base/emission/matcap 等贴图执行 `pow(texture, Gamma_Power)`。
- `u_MAER`：复合贴图；当前 Shader 中使用 `r=metallic`、`g=occlusion`、`b=emission mask/additive channel`、`a=smoothness`。
- `u_MetallicRemapMin/Max`：对 MAER.r remap。
- `u_SmoothnessRemapMin/Max`：对 MAER.a remap；注意当前 Shader 代码是 `mix(max, min, m.a)`，方向可能与 Unity 约定相反，映射时必须谨慎。
- `u_Metallic`：金属度总强度。
- `u_Smoothness`：光滑度总强度。
- `u_BumpMap/u_BumpScale`：法线贴图与强度。
- `u_EmissionTexture/u_EmissionColor/u_EmissionScale`：自发光；需要 define `EMISSION` 生效。
- `u_FresnelColor/u_fresnelOffset/u_FresnelThreshold/u_FresnelSmooth/u_FresnelIntensity/u_FresnelPow/u_FresnelUesF0/u_FresnelUseMoldeNormal`：Laya 侧 Fresnel/边缘光近似；可用于近似 Unity Rim。
- `u_AdjustHue/u_AdjustSaturation/u_AdjustLightness/u_saturationProtection`：需要 define `ADJUST_HSV` 生效。
- `u_ContrastScale`：需要 define `ENABLE_CONTRAST`，且当前 Shader 中它嵌套在 `ADJUST_HSV` 内部，因此只开 `ENABLE_CONTRAST` 不够。
- `u_MatcapMap/u_MatcapStrength`、`u_MatcapAddMap/u_MatcapAddStrength`：需要实际资源存在才可绑定，不允许凭空填 UUID。
- `defines`：材质中必须包含对应宏，否则部分 uniform 即使写入也不会参与渲染。

## 5. Unity 到 Laya 的常用语义映射规则

以下规则是启发式，不是硬编码真理。模型应结合实际 Shader 代码、资源和截图评分修正。

| Unity 常见参数 | 语义 | Laya FishStandard 候选映射 | 注意事项 |
|---|---|---|---|
| `_MainTex` | 基础色贴图 | `u_BaseMap` | 通常由资源导入阶段处理，模型只报告是否匹配 |
| `_Color` | 基础乘色 | `u_BaseColor` | 若有 `_ColorScale`，可合并到 RGB |
| `_ColorScale` | 基础色/HDR 强度 | `u_BaseColor.rgb *= scale` 或降低到安全范围 | 可能导致过曝，需结合截图调小 |
| `_Metallic` | 金属度 | `u_Metallic` | 若 Unity 为 0，Laya 不应强行高金属 |
| `_MetallicGlossMap` / `_MAER` | 金属/遮蔽/光滑等复合图 | `u_MAER` | 通道约定必须核对 |
| `_MetallicRemapMin/Max` | 金属 remap | `u_MetallicRemapMin/Max` | 可直接近似 |
| `_GlossMapScale` / `_Smoothness` | 光滑度强度 | `u_Smoothness` | 名称和公式可能不同 |
| `_SmoothnessRemapMin/Max` | 光滑度 remap | `u_SmoothnessRemapMin/Max` | 注意 Laya Shader 中 alpha remap 方向 |
| `_BumpMap` | 法线贴图 | `u_BumpMap` | 贴图格式必须正确 |
| `_BumpScale` | 法线强度 | `u_BumpScale` | 可直接近似 |
| `_EmissionTexture` | 自发光贴图 | `u_EmissionTexture` | 需要 `EMISSION` |
| `_EmissionColor` | HDR 自发光颜色 | `u_EmissionColor` | HDR 值可大于 1，过亮时降低 |
| `_RimColor` | 边缘光颜色 | `u_FresnelColor` | 近似，不是完全等价 |
| `_RimPower` | Rim 幂次/宽度 | `u_FresnelPow` | 不同 Shader 公式差异大 |
| `_RimSpread` | Rim 扩散/阈值 | `u_FresnelThreshold/u_FresnelSmooth` | 需要启发式转换 |
| `_RimOffset` | Rim 方向偏移 | `u_fresnelOffset` | 近似 |
| `_AdjustHue` | 色相调整 | `u_AdjustHue` | 需要 `ADJUST_HSV` |
| `_AdjustSaturation` | 饱和度调整 | `u_AdjustSaturation` | Unity 与 Laya 取值方向可能相反，需确认公式 |
| `_AdjustLightness` | 明度调整 | `u_AdjustLightness` | 需要 `ADJUST_HSV` |
| `_ContrastScale` | 对比度 | `u_ContrastScale` | 需要 `ADJUST_HSV` + `ENABLE_CONTRAST` |
| `_ReflectCubMap` | 反射/Matcap/Cubemap | `u_IBLMap` 或 `u_MatcapMap` | 必须资源存在且类型匹配 |
| `_Streamer*` | 流光 | 无或自定义扩展 | 当前 FishStandard 不一定支持 |
| `_Hit*` | 受击效果 | 通常不写入静态 lmat | 可能属于运行时逻辑 |

## 6. 推荐的模型输出 JSON Schema

模型输出必须结构化，供工具确定性应用。禁止只输出自然语言。

```jsonc
{
  "summary": "本次调整目标和总体策略",
  "confidence": "high|medium|low",
  "changes": [
    {
      "target": "props.u_BaseColor",
      "action": "set",
      "value": [1.56, 1.60, 1.65, 1],
      "source": ["_Color", "_ColorScale"],
      "reason": "Unity 基础色乘色与颜色强度合并到 Laya 基础色",
      "risk": "可能过亮，截图阶段可下调"
    }
  ],
  "define_changes": [
    {
      "define": "EMISSION",
      "enabled": true,
      "reason": "Unity 启用了自发光贴图/keyword"
    }
  ],
  "texture_changes": [
    {
      "target": "u_MatcapMap",
      "action": "keep",
      "reason": "Unity 贴图在 Laya 资源中未找到，不能凭空绑定"
    }
  ],
  "unmapped_unity_properties": [
    {
      "name": "_StreamerTex",
      "reason": "目标 Laya Shader 无流光实现或当前 Unity keyword 关闭"
    }
  ],
  "warnings": [
    "Unity Rim 与 Laya Fresnel 公式不同，本次为近似映射"
  ],
  "next_validation": [
    "执行 Laya 预览截图，与 Unity 参考图比较整体亮度、边缘光和金属高光"
  ]
}
```

## 7. 系统提示词模板

下面是接入模型时建议使用的 System Prompt 基础模板。

```text
你是一个游戏美术材质迁移与 Shader 参数拟合专家，任务是把 Unity 材质实例尽量迁移到 LayaAir 自定义 Shader 材质。

你必须遵守以下原则：
1. 只基于输入包中的 Unity 材质 JSON、Laya Shader 语义、Laya .lmat、资源查询结果和截图评分做判断。
2. 不允许凭空创造贴图 UUID、资源路径或不存在的 Shader 参数。
3. 如果 Unity 与 Laya Shader 公式不一致，必须说明这是近似映射，不能声称完全等价。
4. 需要开启 define 才生效的参数，必须同时输出 define 修改。
5. 对无法映射、资源缺失、运行时效果参数，必须放入 unmapped 或 warnings。
6. 输出必须是合法 JSON，符合调用方提供的 schema，不要输出 Markdown。
7. 优先保证 Laya 材质 JSON 可用和渲染稳定，再追求视觉接近。
8. 若参数可能导致过曝、颜色偏移或高光异常，应在 risk 或 warnings 中说明。

你的核心目标：生成一组可应用到 Laya .lmat 的参数修改建议，使 Laya 渲染效果更接近 Unity 参考效果。
```

## 8. 用户提示词模板

```text
请根据以下输入包，为目标 Laya 材质生成一版更接近 Unity 原材质的参数修改建议。

要求：
- 输出 JSON，不要输出 Markdown。
- 只修改目标 Laya Shader 中存在的参数。
- 如果某个效果需要 define，请在 define_changes 中明确开启。
- 如果 Unity 贴图在 resource_lookup 中没有匹配资源，不要绑定，只输出 warning。
- 如果某个 Unity 参数无法映射，请放入 unmapped_unity_properties。
- 如果存在截图评分，请优先解释哪些参数会改善当前分数。

输入包：
{{LLM_CONTEXT_PACKAGE_JSON}}
```

## 9. 1580 吕布材质案例中的关键上下文

以当前 `fish_1580_lvbu_diff_01` 到 `1580_body.lmat` 的迁移为例，人工/模型判断依赖的关键信息包括：

- Unity 导出 JSON 表明材质参数导出完整，`missingProperties=[]`、`unsupportedProperties=[]`。
- Unity 材质 Shader 为 `CustomStandardV2`，不是简单 PBR。
- 已绑定核心贴图包括：基础色、MAER、法线、自发光。
- Unity `_ColorScale≈1.65`，可合并到 Laya `u_BaseColor.rgb`。
- Unity `_EmissionColor≈[3.95,3.95,3.95,1]`，可写入 Laya `u_EmissionColor`，并需要 `EMISSION`。
- Unity 金属/光滑度 remap 可近似写入 Laya `u_MetallicRemapMin`、`u_SmoothnessRemapMin` 等。
- Unity Rim 参数可近似映射到 Laya Fresnel，但公式不完全一致。
- Unity HSV/对比度参数可映射到 Laya `ADJUST_HSV`、`ENABLE_CONTRAST` 相关参数。
- Unity `_ReflectCubMap=matcap01_01` 在当前 Laya 资源中未找到，所以不能强行绑定。

这个案例应作为后续自动化测试样例之一：模型输出不应只是“复制数值”，而应解释哪些是直接映射，哪些是近似映射，哪些因资源缺失而保持不变。

## 10. 产品化落地建议

建议将大模型能力作为 `optimizer/llm_mapper.py` 或独立模块接入，形成如下流程：

1. `unity_material_exporter.cs` 导出 Unity 材质实例 JSON。
2. `laya/shader_parser.py` 解析目标 Laya Shader。
3. `laya/lmat_io.py` 读取目标 `.lmat`。
4. 资源索引模块扫描 Laya 资源，生成贴图候选和缺失列表。
5. 上下文构建器生成 `LLMContextPackage`。
6. `llm_mapper.py` 调用模型，得到结构化修改建议。
7. 确定性 validator 校验输出：参数存在、类型正确、范围合理、贴图存在、define 合法。
8. `lmat_io.py` 应用修改并备份原文件。
9. 可选渲染截图评分，进入下一轮模型解释或数值优化。
10. 输出最终 `.lmat`、转换报告、未映射列表、风险列表和截图对比。

在产品级工具中，大模型永远不应直接写文件；它只产生结构化建议，由工具验证后应用。