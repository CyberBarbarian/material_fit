# Laya 材质自动拟合工具方案

> ⚠️ **历史文档**（2025 年最初设计稿）。本文是工具刚立项时的技术设计书，描述了"打算怎么做"。截至 2026-05，工具已实际落地了文中规划的大部分内容（启发式 + CMA-ES + 评分体系 + 探针 + 窗口聚焦），并加了若干文中没预料到的能力（背景统一、hint-bias、UI）。**当前实现状态以 [`ExperimentLog.md`](ExperimentLog.md) §0 头部表为准**，本文留作背景资料。新接手 agent 请先读 [`../AGENT_ONBOARDING.md`](../AGENT_ONBOARDING.md)。

## 1. 背景与目标

Unity 与 Laya 使用同一模型、同一套贴图时，最终渲染效果仍可能存在明显差异。Unity 侧 Shader 往往更复杂，可能包含更完整的光照、反射探针、后处理、复杂高光、渐变贴图、菲涅尔、材质球捕捉贴图或自定义 ShaderGraph 逻辑；Laya 侧 Shader 为了适配小游戏平台，需要控制采样次数、分支复杂度和运行时性能。

本工具的目标不是从头实现一个 Unity 或 Laya 的渲染器，也不是直接把 Unity Shader 完整移植到 Laya，而是：

> 使用真实的 Laya 运行环境渲染结果作为反馈，自动调整 Laya 材质中暴露给 Inspector 的参数，使 Laya 渲染结果尽量接近 Unity 参考效果。

工具的行为应类似技术美术在 Inspector 中反复调参，但实现方式不是鼠标点击 Inspector，而是自动修改材质实例参数、驱动真实引擎渲染、截图、评分和迭代。

## 2. 关键认识

### 2.1 Shader 代码只能告诉我们“有哪些参数可以调”

Shader 中暴露给 Inspector 的参数，一般只是参数定义，例如名称、显示名、类型、默认值、取值范围。它们说明“人类可以调什么”，但通常不能说明“当前材质实例真实用了什么值”。

例如 Unity Shader 中可能有：

```shader
Properties
{
    _BaseColor ("Base Color", Color) = (1,1,1,1)
    _Smoothness ("Smoothness", Range(0,1)) = 0.5
}
```

这里的 `(1,1,1,1)` 和 `0.5` 只是默认值。真实项目中，美术通常会在 Material Inspector 中把它们改成别的值，因此真实参数需要从 Unity 材质实例中读取，而不是只看 Shader 文件。

### 2.2 真实参数应来自材质实例，而不是 Shader 默认值

完整输入应分为两类：

1. **Shader 参数定义**：来自 Unity Shader 和 Laya Shader，用于知道有哪些参数可调、参数类型是什么、范围是什么。
2. **材质实例参数**：来自 Unity Material、Laya `.lmat` 或导出的参数表，用于知道当前真实使用的参数值。

因此工具不能只解析 Shader，还要读取或导出材质实例数据。

### 2.3 工具不模拟渲染引擎，而是驱动真实引擎渲染

工具不会自己实现 Unity 或 Laya 的渲染公式。正确流程是：

```text
生成一组 Laya 候选参数
→ 写入 Laya 材质实例或运行时材质
→ 用真实 Laya 运行环境渲染模型
→ 自动截图
→ 与 Unity 参考截图比较
→ 根据评分继续生成下一组参数
```

也就是说，视觉变化是在真实 Laya 中产生的，不是工具离线模拟出来的。

## 3. 工具总体架构

```text
Unity 侧输入
  ├─ Unity Shader 参数定义
  ├─ Unity Material 真实参数
  ├─ Unity 参考截图
  └─ 贴图资源

Laya 侧输入
  ├─ Laya Shader 参数定义
  ├─ Laya 材质真实参数
  ├─ Laya 对标场景
  └─ 同套贴图资源

自动拟合流程
  ├─ 参数解析与映射
  ├─ 候选参数生成
  ├─ 修改 Laya 材质参数
  ├─ 真实 Laya 渲染截图
  ├─ 图像差异评分
  ├─ 分阶段搜索优化
  └─ 输出最优材质与报告
```

## 4. 为什么不直接操作 Inspector

工具追求的是“像人类调 Inspector 一样调参数”，但不建议真的自动点击 Inspector 界面。

原因：

- Inspector 界面自动化不稳定，窗口大小、焦点、控件布局变化都会影响操作。
- 自动拟合可能需要几十到几百轮迭代，界面操作效率太低。
- 鼠标操作不利于记录、回滚、批量处理和中断恢复。
- 后续如果批量处理多条鱼，界面操作成本会很高。

更合适的实现方式是：

- Unity 侧：从 Material 资产或导出的参数表读取真实参数。
- Laya 侧：直接修改 `.lmat`，或在运行时对材质对象调用参数设置接口。
- 渲染侧：使用真实 Laya 页面、调试场景或构建产物自动截图。

这样得到的结果仍然是“真实 Inspector 参数变化后的渲染效果”，只是绕过了低效且不稳定的界面点击。

## 5. Unity 侧输入方案

### 5.1 Shader 参数定义

如果是传统 Unity ShaderLab，可以解析 `Properties` 块，得到：

- 参数名；
- Inspector 显示名；
- 类型；
- 默认值；
- 范围；
- 是否贴图。

如果是 ShaderGraph，则需要解析 `.shadergraph` 或导出的 Shader。第一版可以先支持传统 ShaderLab，后续再扩展 ShaderGraph。

### 5.2 Material 真实参数

Unity 的真实材质参数应通过以下方式之一提供：

1. 直接提供 `.mat` 文件文本内容；
2. 使用 Unity Editor 脚本导出 `material_params.json`；
3. 提供 Inspector 截图，作为辅助信息；
4. 如果有多个材质球，需要逐个导出。

推荐使用 Unity Editor 脚本导出，格式示例：

```json
{
  "shader": "Custom/Fish/FishStandardUnity",
  "floats": {
    "_Metallic": 0.2,
    "_Smoothness": 0.75,
    "_RimPower": 3.5
  },
  "colors": {
    "_BaseColor": [1.0, 0.82, 0.65, 1.0],
    "_EmissionColor": [0.4, 0.8, 1.0, 1.0]
  },
  "textures": {
    "_BaseMap": "base.png",
    "_NormalMap": "normal.png",
    "_MaskMap": "mask.png"
  }
}
```

### 5.3 Unity 参考截图

Unity 截图用于给自动评分器提供目标效果。推荐至少提供三个角度：

- 正面；
- 侧面；
- 斜侧。

如果 Unity 截图带后处理，需要同时说明是否启用了 Bloom、色调映射、颜色分级、曝光或抗锯齿。否则工具可能把后处理差异误判成材质参数差异。

## 6. Laya 侧输入与执行方案

### 6.1 Laya Shader 参数定义

从 Laya Shader 中解析可调参数，用于知道工具可以调整哪些 Inspector 参数。以 `FishStandard.shader` 为例，工具可解析基础色、主贴图、金属度、光滑度、高光、环境反射、材质球捕捉贴图、菲涅尔、自发光、调色等参数。

### 6.2 Laya 材质真实参数

Laya 当前真实参数应来自 `.lmat` 或运行时材质对象，而不是 Shader 默认值。工具需要支持：

- 读取 `.lmat` 中已有参数；
- 修改指定参数；
- 写出候选材质；
- 保存最优材质；
- 保留原材质备份。

### 6.3 Laya 自动渲染截图

工具需要一个固定的 Laya 对标场景。该场景负责：

1. 加载目标模型；
2. 应用候选材质；
3. 固定相机、灯光、背景和模型姿势；
4. 切换多个标准视角；
5. 等待若干帧；
6. 输出截图。

这一步必须使用真实 Laya 渲染结果，不能用离线模拟替代。

涉及屏幕尺寸、输入或场景加载时，需要遵守 `src/Base/Orientation/README.md` 的项目约束：屏幕坐标和尺寸走 `Screen` 门面，场景加载走 `SceneLoading.loadScene`。

## 7. 自动拟合流程

### 7.1 阶段一：参数解析

输入 Unity Shader、Unity Material、Laya Shader、Laya Material。

产出：

```text
unity_shader_params.json
unity_material_params.json
laya_shader_params.json
initial_params.json
run_manifest.json
```

### 7.2 阶段二：参数映射

根据名称、类型、显示名、使用语义建立候选映射，例如：

```text
Unity _BaseColor       → Laya u_BaseColor
Unity _BaseMap         → Laya u_BaseMap
Unity _Metallic        → Laya u_Metallic
Unity _Smoothness      → Laya u_Smoothness
Unity _NormalMap       → Laya u_BumpMap
Unity _BumpScale       → Laya u_BumpScale
Unity _EmissionColor   → Laya u_EmissionColor
Unity _RimColor        → Laya u_FresnelColor
Unity _RimPower        → Laya u_FresnelPow
```

注意：映射只用于生成初始猜测和搜索范围，最终仍以 Laya 真实渲染截图评分为准。

### 7.3 阶段三：生成候选参数

工具按照阶段优先级生成候选参数。第一版推荐使用“分阶段粗到细搜索”：

1. 当前阶段只开放少量参数。
2. 粗粒度试探。
3. 找到较优范围。
4. 缩小范围继续细化。
5. 固定当前阶段结果，进入下一阶段。

### 7.4 阶段四：应用参数并渲染

每生成一组候选参数后，工具会：

1. 写入临时 `.lmat`，或传给 Laya 运行时材质；
2. 启动或刷新 Laya 对标场景；
3. 等待渲染稳定；
4. 自动截图；
5. 保存本轮结果。

### 7.5 阶段五：图像评分

工具将 Laya 截图与 Unity 参考图进行比较。

评分项可以包括：

- 平均颜色误差；
- 亮度误差；
- 饱和度误差；
- 高光区域误差；
- 边缘轮廓误差；
- 暗部范围误差；
- 结构相似度。

建议使用模型遮罩，只比较模型区域，避免背景影响评分。

### 7.6 阶段六：保存最优结果

工具记录当前最优参数、截图和评分。所有阶段完成后输出最终结果。

## 8. 参数优先级

### 8.1 基础色拟合

目标：整体颜色、亮度、饱和度接近 Unity。

优先参数：

- `u_BaseColor`
- `u_Gamma_Power`
- `u_AdjustHue`
- `u_AdjustSaturation`
- `u_AdjustLightness`
- `u_ContrastScale`

### 8.2 明暗层次拟合

目标：受光面、暗部范围、明暗边界接近 Unity。

优先参数：

- `u_DiffuseThreshold`
- `u_DiffuseSmoothness`
- `u_ShadowColor`
- 灯光方向；
- 灯光颜色；
- 灯光强度。

### 8.3 主高光拟合

目标：高光位置、强度、面积和锐利程度接近 Unity。

优先参数：

- `u_SpecularColor`
- `u_SpecularIntensity`
- `u_SpecularThreshold`
- `u_SpecularSmooth`
- `u_GGXSpecular`
- `u_Smoothness`
- `u_SmoothnessRemapMin`
- `u_SmoothnessRemapMax`
- `u_SpecularLightOffset`

### 8.4 环境反射拟合

目标：反射亮度、颜色、方向和湿润感接近 Unity。

优先参数：

- `u_IBLMapIntensity`
- `u_IBLMapPower`
- `u_IBLMapColor`
- `u_IBLMapRotateX`
- `u_IBLMapRotateY`
- `u_IBLMapRotateZ`
- `u_EnvironmentReflections`
- `u_Metallic`

### 8.5 材质球捕捉贴图与假反射拟合

目标：用低成本方式模拟 Unity 中复杂反射、鱼鳞闪光和局部亮斑。

优先参数：

- `u_MatcapStrength`
- `u_MatcapPow`
- `u_MatcapAngle`
- `u_MatcapColor`
- `u_MatcapAddStrength`
- `u_MatcapAddPow`
- `u_MatcapAddAngle`
- `u_MatcapAddColor`

### 8.6 菲涅尔和自发光拟合

目标：轮廓光、边缘通透感和发光纹路接近 Unity。

优先参数：

- `u_FresnelColor`
- `u_FresnelThreshold`
- `u_FresnelSmooth`
- `u_FresnelIntensity`
- `u_FresnelPow`
- `u_EmissionColor`
- `u_EmissionScale`

### 8.7 全局微调

目标：在前面阶段的基础上，小范围联动优化。此阶段可以开放前面阶段的低风险参数，但范围应限制在当前最优值附近。

## 9. 推荐目录结构

```text
tools/material_fit/
  README.md
  fit_config.example.json
  fit_material.py
  shader_parser.py
  unity_material_exporter.cs
  lmat_io.py
  image_score.py
  parameter_search.py
  render_driver.py
  report.py
  cases/
    fish_001/
      unity/
      laya/
      config.json
  output/
```

如果需要 Laya 内部配合自动截图，可以新增：

```text
src/Debug/MaterialFit/
  MaterialFitScene.ts
  MaterialFitController.ts
```

## 10. 实施步骤

### 阶段 0：准备标准测试用例

准备内容：

1. Unity Shader；
2. Unity 材质真实参数；
3. Unity 参考截图；
4. Laya Shader；
5. Laya `.lmat`；
6. 同一套贴图；
7. Laya 对标场景；
8. 目标平台性能限制。

### 阶段 1：实现 Shader 参数解析器

目标：从 Unity 和 Laya Shader 中提取可调参数定义。

产出：

```text
unity_shader_params.json
laya_shader_params.json
```

### 阶段 2：实现 Unity 材质参数导出

目标：获取 Unity Inspector 中真实材质参数，而不是 Shader 默认值。

推荐方式：编写 Unity Editor 导出脚本，将当前 Material 的 Float、Color、Texture、Vector 等参数导出为 `material_params.json`。

### 阶段 3：实现 Laya 材质读写

目标：读取和修改 `.lmat` 或运行时材质参数。

需要支持：

- 读取当前参数；
- 修改候选参数；
- 写入临时材质；
- 输出最优材质；
- 备份原始材质。

### 阶段 4：实现 Laya 自动截图场景

目标：用真实 Laya 渲染候选材质。

需要支持：

- 加载目标模型；
- 应用候选材质；
- 切换标准视角；
- 固定灯光和背景；
- 输出截图。

### 阶段 5：实现图像评分器

目标：自动比较 Unity 参考图与 Laya 截图。

第一版评分建议包括：

- 颜色误差；
- 亮度误差；
- 饱和度误差；
- 高光误差；
- 边缘误差；
- 结构相似度。

### 阶段 6：实现分阶段搜索器

目标：按照参数优先级逐步优化。

第一版推荐：

```text
分阶段搜索 + 坐标下降 + 局部细化
```

后续可以扩展为贝叶斯优化、遗传算法、粒子群或模拟退火。

### 阶段 7：实现报告生成

报告内容：

1. 输入资源摘要；
2. Unity 真实参数；
3. Laya 初始参数；
4. 参数映射表；
5. 每阶段搜索范围；
6. 每阶段最佳结果；
7. 最终参数；
8. Unity、Laya、差异图对比；
9. 仍无法拟合的效果；
10. 是否建议扩展 Shader。

## 11. MVP 范围

第一版建议控制范围，先跑通完整链路。

### 11.1 第一版支持

- 只支持 `FishStandard.shader`；
- 只调整 Laya 材质参数；
- 只处理静态模型截图；
- 支持一到三个参考角度；
- 支持基础色、明暗、高光、材质球捕捉贴图、菲涅尔几个阶段；
- 输出最优 `.lmat`、参数表和报告。

### 11.2 第一版不支持

- 不自动改 Shader 代码；
- 不自动生成贴图；
- 不处理 Timeline 动画；
- 不处理粒子特效；
- 不完整复刻 Unity 后处理；
- 不支持所有 ShaderGraph 复杂节点。

## 12. 工具输出

建议输出：

```text
tools/material_fit/output/fish_001/
  best_material.lmat
  best_params.json
  report.md
  compare_front.png
  compare_side.png
  compare_45.png
  score_curve.json
  iterations/
```

`best_material.lmat` 是最终材质；`best_params.json` 记录最终参数；`report.md` 解释优化过程和剩余差异。

## 13. 风险与限制

1. 如果 Unity 与 Laya 的相机角度、模型姿势、光照或背景不一致，图像评分会误判。
2. 如果 Unity 截图包含后处理，而 Laya 没有对应后处理，只靠材质参数很难完全一致。
3. 如果 Laya Shader 缺少 Unity 中关键效果，例如各向异性高光、多层渐变、复杂流光或屏幕空间反射，自动调参只能接近，无法完全复刻。
4. 如果 Shader 参数受宏开关影响，工具必须同时处理开关状态，否则会调整无效参数。
5. 如果贴图导入设置、压缩格式、颜色空间不同，会导致参数搜索偏离真实原因。

## 14. 结论

自动材质拟合工具应以真实引擎渲染为闭环，而不是离线模拟渲染。Shader 文件用于识别“可以调哪些参数”，材质实例用于读取“当前真实参数值”，Laya 自动截图用于观察“参数变化后的真实效果”，图像评分和搜索算法用于决定“下一轮怎么调”。

推荐先围绕 `FishStandard.shader` 实现 MVP：

```text
解析 Shader 可调参数
→ 导出 Unity 真实材质参数
→ 读取 Laya 真实材质参数
→ 修改 Laya 候选参数
→ 用真实 Laya 渲染截图
→ 与 Unity 参考图评分
→ 分阶段搜索最优参数
→ 输出最优材质和报告
```

这条链路跑通后，再扩展更多 Shader、更多鱼模型、批量处理、自动 Shader 能力缺口分析，以及必要的低成本 Laya Shader 增强。