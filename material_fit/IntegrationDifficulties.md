# 材质自动拟合四个关键难点实施说明

> ⚠️ **历史文档**（2025 年版本）。本文写于工具开发早期，描述当时计划的 4 个关键难点和最小闭环。截至 2026-05，文中的"还需要做"部分大多已通过 E-001 .. E-012 实验完成。**当前实现状态以 [`docs/ExperimentLog.md`](docs/ExperimentLog.md) §0 头部表为准**，本文留作背景资料。新接手 agent 请先读 [`AGENT_ONBOARDING.md`](AGENT_ONBOARDING.md)。

本文说明材质自动拟合工具后续真正跑通闭环时，四个关键难点应如何处理。目标不是一次性把所有自动化都做完，而是先明确每个难点的可行路径、最小闭环、需要人工配合的边界，以及后续工具应如何扩展。

## 1. Unity 端：获取材质实例真实参数

### 1.1 问题本质

Unity Shader 文件里的 `Properties` 默认值只能说明“这个 Shader 有哪些可调项，以及默认值是什么”，不能代表当前 Material Inspector 中真实使用的值。真实参数必须来自 Unity 材质实例，包括：

- Float / Range；
- Color；
- Vector；
- Texture 引用；
- Shader Keyword；
- Render Queue、Pass 开关、GI/Instancing 等材质级配置；
- 如果对象运行时动态改材质，还需要区分 `sharedMaterial` 与实例化后的 `material`。

### 1.2 推荐接入 unity-mcp

你提到已经在 Unity 端接入了 `unity-mcp`。根据 `https://github.com/CoplayDev/unity-mcp` 当前说明，推荐流程如下：

1. Unity 中安装包：

   ```text
   https://github.com/CoplayDev/unity-mcp.git?path=/MCPForUnity#main
   ```

2. 在 Unity 菜单打开：

   ```text
   Window > MCP for Unity
   ```

3. 点击 **Start Server**，默认会启动 HTTP 服务：

   ```text
   http://localhost:8080/mcp
   ```

4. VS Code / AI IDE 侧配置 MCP。

   如果使用 VS Code 原生 MCP 配置，文档示例是：

   ```json
   {
     "servers": {
       "unityMCP": {
         "type": "http",
         "url": "http://localhost:8080/mcp"
       }
     }
   }
   ```

   当前本项目根目录已有 `.mcp.json`，格式是：

   ```json
   {
     "mcp": {
       "servers": {
         "laya_mcp_server": {
           "type": "http",
           "url": "https://laya-knowledge-mcp.layaair.com/mcp"
         }
       }
     }
   }
   ```

   如果当前 AI IDE 使用的是这个项目内 `.mcp.json` 格式，则可以在 `mcp.servers` 下追加：

   ```json
   {
     "mcp": {
       "servers": {
         "unityMCP": {
           "type": "http",
           "url": "http://localhost:8080/mcp"
         }
       }
     }
   }
   ```

   注意：不要删除已有的 `laya_mcp_server`，只是在同级追加 `unityMCP`。配置后通常需要重启 AI IDE、刷新 MCP 或重新加载窗口。

### 1.3 能否直接看到 Unity 中所有模型材质 Inspector 当前参数

结论：**理论上可以，但建议不要依赖“直接读 Inspector UI”，而是通过 Unity Editor API 导出材质实例参数。**

`unity-mcp` 已提供 `manage_material`、`manage_asset`、`find_gameobjects`、`manage_components`、`execute_custom_tool`、`editor_selection` 等能力。它适合让 AI 侧查询 Unity 场景、选中对象、材质资源和组件信息。但“所有模型的所有材质 Inspector 当前参数”这个需求，为了稳定和批量化，推荐走下面两层方案：

#### 方案 A：用 unity-mcp 调用现有材质/对象查询工具

适合快速检查：

- 当前选中对象挂了哪些 Renderer；
- Renderer 上有哪些 shared materials；
- 某个 Material 使用哪个 Shader；
- 某个 Material 的部分属性。

风险：不同版本 `unity-mcp` 对 `manage_material` 的返回字段可能不同；复杂 Shader、ShaderGraph 或自定义 Inspector 的显示字段不一定完整。

#### 方案 B：写 Unity Editor 导出脚本或 MCP Custom Tool

这是推荐方案。它不读 Inspector UI，而是直接用 Unity Editor API：

- 遍历场景内所有 `Renderer`；
- 收集 `renderer.sharedMaterials`；
- 对每个 `Material` 读取 `material.shader`；
- 用 `shader.GetPropertyCount()`、`GetPropertyName()`、`GetPropertyType()` 枚举 Shader 属性；
- 对每个属性调用 `GetFloat`、`GetColor`、`GetVector`、`GetTexture`；
- 同时导出 `material.shaderKeywords`、`renderQueue`、`enableInstancing` 等配置；
- 写出 `unity_material_instances.json`。

本工具目录已有草案：

```text
tools/material_fit/unity/unity_material_exporter.cs
```

后续应把它升级为两种模式：

1. **导出选中 Material**：用于单个材质调试；
2. **导出当前场景所有 Renderer 材质**：用于自动批量处理模型。

推荐输出格式：

```json
{
  "scene": "FishCompareScene",
  "materials": [
    {
      "assetPath": "Assets/Fish/1205/Materials/1205_body.mat",
      "name": "1205_body",
      "shader": "Custom/Fish/FishStandardUnity",
      "renderers": ["Fish_1205/BodyRenderer"],
      "keywords": ["_NORMALMAP", "_EMISSION"],
      "renderQueue": 2450,
      "floats": {
        "_Metallic": 0.1,
        "_Smoothness": 0.72
      },
      "colors": {
        "_BaseColor": [1.0, 0.82, 0.65, 1.0]
      },
      "vectors": {},
      "textures": {
        "_BaseMap": "Assets/Fish/1205/Textures/body_base.png"
      }
    }
  ]
}
```

### 1.4 我们后续如何确认 MCP 是否接好了

AI IDE 侧配置好 `unityMCP` 后，确认步骤应是：

1. Unity 中 `Window > MCP for Unity` 显示服务已启动；
2. AI IDE 的 MCP 面板或日志能看到 `unityMCP`；
3. 能读取 `unity_instances` 或 `editor_state`；
4. 能查询当前选中对象或场景对象；
5. 能查询或导出一个选中 Material 的参数；
6. 最后再做“导出当前场景所有 Renderer 材质参数”。

如果第 5 步返回的 Material 参数完整，我们就可以把它作为自动拟合工具的 Unity 真实参数输入。如果不完整，就用 `execute_custom_tool` 或 Unity Editor 脚本导出 JSON。

## 2. Laya 端：读取并真实改写当前渲染材质参数

### 2.1 问题本质

Laya 端也不能只看 Shader 默认值。当前模型真实渲染效果来自：

- `.lmat` 文件中的 `props`；
- 模型、Prefab 或场景中绑定的材质引用；
- 运行时脚本是否又改过材质；
- Shader 宏开关 `defines`；
- 贴图资源引用和导入设置；
- 灯光、环境贴图、相机、后处理等非材质因素。

因此工具需要同时支持“离线改 `.lmat`”和“运行时改 Material 对象”两种方式。

### 2.2 离线方式：改写 `.lmat`

这是当前工具已经开始支持的路径：

```text
tools/material_fit/laya/lmat_io.py
```

流程：

1. 读取目标 `.lmat`；
2. 从 `props` 中提取当前真实参数；
3. 生成候选参数；
4. 写出临时 `.lmat`；
5. Laya 对标场景加载该临时材质；
6. 截图评分；
7. 最终输出 `best_material.lmat`。

优点：

- 可记录、可回滚；
- 适合批量自动化；
- 不依赖 Inspector UI；
- 输出结果可以直接进资源流程。

风险：

- 如果 Laya 编辑器或运行时已有资源缓存，改文件后需要确保重新加载；
- 如果模型引用的是原材质，需要对标场景显式加载候选材质替换到 Renderer 上；
- 若材质参数类型写错，可能不会生效或渲染异常。

### 2.3 运行时方式：调试场景实时设置 Material 参数

为了让工具真实改写 Laya 渲染效果，推荐后续新增一个专用调试场景：

```text
src/Debug/MaterialFit/MaterialFitScene.ts
src/Debug/MaterialFit/MaterialFitController.ts
```

职责：

1. 加载目标模型；
2. 加载初始材质或候选材质；
3. 暴露一个调试接口，例如读取 `params.json`；
4. 把参数设置到模型当前材质实例上；
5. 等待若干帧让贴图、Shader、光照稳定；
6. 截图并保存或返回截图。

运行时改参有两种实现方式：

- **文件轮询模式**：Python 工具写 `candidate_params.json`，Laya 调试场景轮询或收到刷新信号后读取并应用；
- **HTTP/WebSocket 模式**：Laya 页面启动后暴露本地调试接口，Python 工具请求 `applyParams` 和 `capture`。

第一版建议用文件轮询或页面 URL 参数，减少通信复杂度。等闭环稳定后再升级为 HTTP/WebSocket。

### 2.4 如何确认 Laya 参数真的生效

需要做一个最小验证用例：

1. 选择一个视觉变化明显的参数，例如 `u_BaseColor`、`u_EmissionScale`、`u_MatcapStrength`；
2. 工具写入极端值；
3. Laya 对标场景加载并截图；
4. 图像评分或肉眼确认画面明显变化；
5. 再写回原值确认能恢复。

只有这个验证通过，后续自动搜索才有意义。否则工具可能一直在改文件，但 Laya 渲染用的不是同一个材质实例。

### 2.5 与项目约束的关系

如果后续新增 Laya 调试场景，涉及屏幕、输入、场景加载时必须遵守项目约束：

- 屏幕尺寸、鼠标或触摸坐标走 `Screen` 门面；
- 场景切换走 `SceneLoading.loadScene`；
- 新场景需要在 `src/Scenes/SceneConfig.ts` 登记方向；
- 不在业务里直接读 `Laya.stage.mouseX/Y` 或 `stage.width/height`；
- 不直接使用 `Laya.Scene.open` 作为业务场景加载入口。

## 3. Unity 与 Laya 截图和实时对比

### 3.1 问题本质

自动拟合不是只比较参数，而是比较最终画面。截图对比要尽量保证两边只有“材质差异”，不要把相机、灯光、姿势、背景、后处理差异混进评分。

你可以人工把 Unity 和 Laya 的模型镜头挪到同一方位，这可以显著降低自动化难度。工具第一版只需要负责：

- 获取 Unity 参考截图；
- 获取 Laya 候选截图；
- 对齐尺寸；
- 按遮罩或模型区域评分；
- 输出差异报告。

### 3.2 Unity 截图方案

可选方案：

1. **人工截图**：你在 Unity 里摆好镜头，手动截图，放到工具输入目录；
2. **unity-mcp 截图**：如果当前 `unity-mcp` 的 `manage_camera`、编辑器视图或自定义工具能截图，就由 AI 调用；
3. **Unity Editor 脚本截图**：最稳定，写一个 Editor 工具，把指定 Camera 渲染到 `RenderTexture`，再保存 PNG。

推荐先用人工截图或 Editor 脚本。原因是自动优化需要截图路径稳定、命名稳定、分辨率稳定，而不是依赖编辑器窗口当前大小。

推荐目录：

```text
tools/material_fit/cases/fish_1205/unity/reference_front.png
tools/material_fit/cases/fish_1205/unity/reference_side.png
tools/material_fit/cases/fish_1205/unity/reference_45.png
```

### 3.3 Laya 截图方案

Laya 端应由对标场景负责截图。第一版建议：

1. 启动 Laya debug 页面；
2. Python 工具写候选参数；
3. Laya 页面加载候选参数；
4. 固定相机和灯光；
5. 渲染稳定后截图；
6. 保存为：

   ```text
   tools/material_fit/output/fish_1205/iterations/iter_0001/front.png
   ```

如果浏览器环境无法直接写本地文件，可以让 Puppeteer/浏览器自动化负责截图页面区域。这样 Python 工具或 MCP 浏览器工具只要打开 Laya 页面，等待渲染完成，然后截图保存即可。

### 3.4 对齐要求

截图评分前至少保证：

- Unity 与 Laya 截图分辨率一致，或由工具统一缩放；
- 模型在画面中的位置和大小尽量一致；
- 背景颜色尽量一致，推荐纯色；
- 光照方向尽量一致；
- 关闭或记录 Unity 后处理，例如 Bloom、Tonemapping、Color Grading、AA；
- 多角度截图使用固定命名：`front`、`side`、`angle45`。

### 3.5 遮罩与差异图

第一版评分可以不做复杂分割，但建议尽快加入遮罩。遮罩用于只比较模型区域，避免背景影响评分。

可选方式：

1. 人工提供 mask；
2. Unity 和 Laya 均用纯背景色，工具自动阈值抠出模型；
3. Laya 对标场景额外渲染一张纯白模型黑背景 mask。

评分输出建议包括：

- Unity 参考图；
- Laya 当前图；
- Difference 差异图；
- Mask 图；
- 每个角度的评分；
- 总评分曲线。

## 4. 分析方法与自动调整方法

### 4.1 总体思路

不要一开始就把 70 多个参数全部交给优化器。这样搜索空间太大，容易震荡，而且评分可能把高光、亮度、饱和度问题混在一起。

推荐方法是：

```text
真实 Unity 参数 + Laya 当前参数
→ 建立参数映射和初始猜测
→ 分阶段开放少量 Laya 参数
→ 每阶段粗搜
→ 每阶段局部细化
→ 保存最优候选
→ 下一阶段继续
→ 最后全局小范围微调
```

### 4.2 参数映射只做初始猜测，不做最终判断

Unity 参数和 Laya 参数名称可能不同，渲染公式也可能不同。因此映射表只用于：

- 生成初始值；
- 推测哪些 Laya 参数可能相关；
- 决定搜索范围。

最终是否更接近，必须看真实截图评分。

例如：

```text
Unity _BaseColor     → Laya u_BaseColor
Unity _Metallic      → Laya u_Metallic
Unity _Smoothness    → Laya u_Smoothness
Unity _EmissionColor → Laya u_EmissionColor
Unity _RimColor      → Laya u_FresnelColor
Unity _RimPower      → Laya u_FresnelPow
```

如果 Unity 使用复杂 ShaderGraph，映射可能只能给出大方向，不能保证一一对应。

### 4.3 分阶段优化顺序

当前工具已经有一个初始阶段计划，后续应继续沿用并细化：

1. **基础色阶段**：
   - 目标：整体颜色、亮度、饱和度接近；
   - 参数：`u_BaseColor`、`u_Gamma_Power`、`u_AdjustHue`、`u_AdjustSaturation`、`u_AdjustLightness`、`u_ContrastScale`。

2. **明暗层次阶段**：
   - 目标：受光面、暗面、明暗边界接近；
   - 参数：`u_DiffuseThreshold`、`u_DiffuseSmoothness`、`u_ShadowColor`；
   - 同时要固定或记录灯光方向、颜色、强度。

3. **主高光阶段**：
   - 目标：高光面积、强度、锐度接近；
   - 参数：`u_SpecularColor`、`u_SpecularIntensity`、`u_SpecularThreshold`、`u_SpecularSmooth`、`u_GGXSpecular`、`u_Smoothness`。

4. **环境反射阶段**：
   - 目标：反射强度、湿润感、环境色接近；
   - 参数：`u_IBLMapIntensity`、`u_IBLMapPower`、`u_IBLMapColor`、`u_EnvironmentReflections`、`u_Metallic`。

5. **Matcap / 假反射阶段**：
   - 目标：补足 Unity 复杂反射或鱼鳞闪光；
   - 参数：`u_MatcapStrength`、`u_MatcapPow`、`u_MatcapAngle`、`u_MatcapColor`、`u_MatcapAddStrength`、`u_MatcapAddPow`、`u_MatcapAddAngle`、`u_MatcapAddColor`。

6. **菲涅尔与自发光阶段**：
   - 目标：边缘光、发光纹路、通透感接近；
   - 参数：`u_FresnelColor`、`u_FresnelThreshold`、`u_FresnelSmooth`、`u_FresnelIntensity`、`u_FresnelPow`、`u_EmissionColor`、`u_EmissionScale`。

7. **全局微调阶段**：
   - 在当前最优值附近小范围联合搜索；
   - 避免大范围重新扰动前面阶段结果。

### 4.4 图像评分建议

第一版评分不需要非常复杂，但要能区分主要问题。建议拆成多个评分项：

- `rgb_mae`：RGB 平均绝对误差，衡量整体颜色；
- `luma_mae`：亮度误差，衡量明暗；
- `saturation_mae`：饱和度误差；
- `highlight_score`：只比较高亮区域，衡量高光；
- `shadow_score`：只比较暗部区域；
- `edge_or_mask_score`：轮廓或 mask 对齐问题；
- `ssim`：结构相似度，可作为后续增强。

每个阶段使用不同权重。例如基础色阶段弱化高光权重，主高光阶段提高高亮区域权重。

### 4.5 搜索算法建议

MVP 推荐不要上来就用复杂全局优化。可以按以下顺序实现：

#### 第一步：人工范围 + 网格粗搜

对每个阶段的少数参数做粗粒度采样，例如：

```text
当前值 * 0.5
当前值
当前值 * 1.5
```

或按 Shader 声明范围采样低、中、高三点。

#### 第二步：坐标下降

每次只调一个参数，接受让评分变好的改动，然后缩小步长继续。

优点：

- 易实现；
- 易解释；
- 适合参数数量较多但每阶段只开放少量参数的情况。

#### 第三步：局部联合微调

对阶段内最敏感的 2 到 4 个参数做小范围联合搜索，避免单参数调优卡在局部问题上。

#### 第四步：可选高级优化

如果后续需要更自动，可以再考虑：

- 贝叶斯优化；
- CMA-ES；
- 遗传算法；
- 粒子群；
- 模拟退火。

但这些方法都依赖稳定截图和稳定评分。在截图闭环没稳定前，不建议优先做。

### 4.6 什么时候判定“调参无法解决”

自动调参不是万能的。如果出现以下情况，应在报告里提示需要改 Shader 或资源，而不是继续盲目搜索：

- Unity 有明显的多层高光，Laya Shader 只有单层高光；
- Unity 有各向异性、清漆层、屏幕空间反射，Laya 没有对应近似；
- Unity 后处理影响很强，比如 Bloom 或 Color Grading；
- 两边法线贴图、切线、颜色空间、贴图压缩明显不同；
- 调整相关参数后截图几乎不变化，说明参数没有真正生效或宏开关未打开。

这类情况应输出“能力缺口报告”，例如：

```text
当前 Laya Shader 缺少第二层高光，Matcap 参数已调到上限但 Unity 参考图仍有局部强反射，建议增加低成本二层高光或专用 mask 控制。
```

## 5. 推荐下一步落地顺序

推荐按下面顺序推进，避免同时解决所有难点导致不可控：

1. **接通 unity-mcp 并验证单个材质参数读取**
   - 目标：AI IDE 能看到 Unity 当前选中 Material 的真实参数；
   - 如果 MCP 返回不完整，就改用 Unity Editor 导出 JSON。

2. **完善 Unity 材质导出脚本**
   - 支持选中 Material；
   - 支持当前场景所有 Renderer 的 sharedMaterials；
   - 导出 keywords、renderQueue、贴图路径。

3. **做 Laya 参数生效验证**
   - 用 `u_BaseColor` 或 `u_EmissionScale` 做极端值测试；
   - 确认工具改参数后真实截图变化。

4. **建立最小截图闭环**
   - Unity 先人工截图；
   - Laya 用固定页面和 Puppeteer 截图；
   - 工具生成差异图和基础评分。

5. **实现基础色阶段自动搜索**
   - 只开放 3 到 6 个参数；
   - 先跑通一条鱼的一个角度，再扩展多个角度。

6. **扩展到高光、反射、菲涅尔阶段**
   - 每个阶段都保留报告，便于人工判断是否真的在接近 Unity。

## 6. 本工具需要补齐的模块

当前 `tools/material_fit/` 已按 `unity/`、`laya/`、`vision/`、`optimizer/` 与 `shared/` 拆分框架，但距离完整闭环还需要补齐：

```text
UnityMaterialSource
  从 unity-mcp 或 Unity 导出 JSON 读取真实 Material 参数。

LayaRuntimeBridge
  把候选参数应用到 Laya 调试场景，并触发截图。

CaptureManager
  管理 Unity 参考截图、Laya 候选截图、mask、差异图。

ScoringPipeline
  多评分项、多角度加权汇总。

SearchOptimizer
  从当前探针候选升级为分阶段坐标下降和局部细化。

FitReport
  输出参数变化、评分曲线、对比图、能力缺口。
```

## 7. 结论

这四个难点可以拆成两个闭环：

1. **数据闭环**：Unity 真实材质参数 → Laya 当前材质参数 → 参数映射和候选生成；
2. **渲染闭环**：写入 Laya 参数 → 真实 Laya 截图 → 与 Unity 截图评分 → 继续调参。

其中最关键的不是优化算法，而是先验证：

- Unity 端读到的是 Material 实例真实参数；
- Laya 端改的是当前渲染正在使用的材质；
- 截图稳定且可重复；
- 评分能反映肉眼看到的主要差异。

这四点稳定后，自动搜索算法才有实际价值。