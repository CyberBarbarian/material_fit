# 材质自动优化核心算法与评价指标说明

本文档总结当前工具中已经接入的优化算法、评分模式和实际参与优化的评价指标。它面向实验记录、论文说明和后续算法对比使用，描述的是当前代码实现，而不是理想化设计。

## 1. 问题定义

当前任务不是普通的单参数调节，而是一个昂贵、不可导、多指标、高耦合、带门控的黑盒优化问题：

- 输入：Laya 材质参数、shader 参数定义、参考渲染图、当前 Laya 截图。
- 输出：一组新的 Laya 材质参数，使当前截图尽可能接近参考图。
- 每一次评价都需要写入 `.lmat`、等待 Laya 刷新、截图、图像分析和打分，因此一次迭代的代价较高。
- 优化器只能看到“参数变化之后分数如何变化”，不能直接获得可微梯度。

整体循环为：

1. 读取当前参数和参考图。
2. 优化器提出候选参数。
3. 写入材质并重新截图。
4. 计算图像差异、research metrics、fit score。
5. 将本轮结果反馈给优化器。
6. 重复直到达到迭代上限、手动取消或策略停止。

## 2. 当前可用优化算法

当前 CLI/UI 可选优化器如下：

| optimizer 名称 | 类型 | 当前定位 |
| --- | --- | --- |
| `pattern16` | 16 维坐标 pattern search | 当前鱼 finetune 默认主算法，复现早期高分白底 8 向实验 |
| `adaptive_response_search` | 全局最优中心的响应证据搜索 | 实验性对照路线 |
| `semantic_group` | 响应图驱动的语义调度器 | 保留为对照和继续研究版本 |
| `semantic_group_legacy_081` | 旧版语义分组模式搜索 | 用于复现早期 0.8 附近结果的基线 |
| `subspace_cma_es` | 语义子空间 CMA-ES | 更昂贵的黑盒对照算法 |
| `cma_cold` | 冷启动 CMA-ES | 标准黑盒基线 |
| `cma_warm` | warm-start CMA-ES | 使用历史样本初始化的 CMA-ES |
| `heuristic` | 启发式分阶段调参 | 早期生产路径和兼容基线 |

### 2.1 `pattern16`

这是当前鱼 finetune 默认主算法。核心思想是：只搜索已经通过远程复现实验证明有效的 16 个外观参数，按固定顺序对每个参数做 `-step/+step` 真实渲染探测，只接受 fit score 提升的候选；如果一整轮没有提升，就把 step 减半。

主要机制：

- 搜索白名单固定为 `u_GammaPower`、`u_Saturation`、`u_TexPower`、`u_AoPower`、`u_EmissionPow`、`u_IndirectStrength`、`u_NormalScale`、`u_ShadowSmoothness`、`u_ShadowThreshold1`、`u_ShadowThreshold2`、`u_SpecularIntensity`、`u_SpecularPower`、`u_SpecularThreshold`、`u_SpecularSmoothness`、`u_RimIntensity`、`u_RimWidth`。
- zero-start 是这个 16 维搜索子空间上的困难初始化调试分支：上述 16 个参数置为 `0.0`，其它不在搜索空间内的数值参数和材质合法性参数继承 baseline `.lmat`。这样测试的是算法从弱外观参数出发的恢复能力，而不是测试贴图、UV、alpha、灯光/天空状态被破坏后的不可恢复场景。该路线仍在调试中，不作为当前稳定发布门槛。
- zero-start 使用 Python 端 `reference_foreground_mae` 作为优化目标：用 Unity reference 的 alpha 前景作为鱼体 mask，只在前景区域计算 RGB MAE。原因是极端 zero 起点可能渲染成白底空图，旧的全画布 browser MAE 会被大面积背景稀释，错误地把空白图评为高分。
- 每个候选都从当前 best 参数出发生成，坏候选不会污染后续搜索中心。
- deliberate probe 会产生无提升甚至变差的样本，所以它不使用 heuristic 的全局 4-step no-improve abort。
- 默认鱼实验使用 8 向 Unity reference、固定 `idle1` 动画、`900x700` 渲染和 `browser_fast_rgba_mae_v1`。

### 2.2 `adaptive_response_search`

这是保留的实验性对照路线。核心思想是：所有候选都围绕当前全局最好参数生成，优化器根据真实试验响应来决定下一轮把预算给哪个参数或参数组合。

主要机制：

- 第 0 轮只做 baseline evaluation，不主动改变参数。
- 维护全局最好参数 `best_params` 和最好分数 `best_fit_score`。
- 每次候选都从 `best_params` 出发生成，而不是从上一轮可能跑偏的参数继续。
- 对每个参数维护响应证据，包括尝试次数、正收益次数、无效次数、最好收益、平均收益、方向稳定性和指标变化。
- 对 Color/Vector 参数支持 axis-aware probing，不只测试第一个通道。
- 对被 gate 影响的参数，保留 activation parameter 的探索机会，避免永远无法打开某些有效分支。
- 低频执行 pair/interaction probe，用于发现单参数搜索不容易看到的交互关系。

一次试验的收益计算为：

```text
delta = candidate_fit_score - center_fit_score
```

其中 `center_fit_score` 是提出候选时的全局最好分数，而不是上一轮分数。这样做的目的是避免把“从跑偏状态恢复”误判为某个参数带来的真实收益。

适用场景：

- 当前推荐默认使用。
- 适合评估预算昂贵、参数较多、需要稳定利用历史最好样本的情况。
- 适合继续积累“参数影响哪些指标”的响应证据。

主要风险：

- 如果评分系统本身和真实参考不一致，算法会稳定优化到错误目标。
- 如果某些参数必须联合变化才有收益，单参数证据可能低估它们。
- 低频 interaction probe 可以缓解该问题，但不能保证完全解决强耦合参数空间。

### 2.2 `semantic_group`

这是重构后的响应图语义调度器。它不再只是固定按组轮转，而是通过 `ResponseMap`、`ExperimentPlanner` 和 `CandidateBuilder` 组成一个 response-driven scheduler。

核心模块：

- `ResponseMap`：记录参数变化对 fit score 和各指标组件的影响。
- `ExperimentPlanner`：根据响应图、瓶颈指标、参数排序和预算限制选择下一种试验。
- `CandidateBuilder`：只负责把“试验意图”转换成具体参数候选。
- `TopKArchive`：保存高分候选样本。
- `AcceptancePolicy`：判断候选是否有足够收益。
- `BranchDriftGuard`：允许有限探索偏离，并保留 checkpoint。

常见试验类型包括：

- `single_param`：单参数响应测试。
- `subspace_batch`：小子空间联合扰动。
- `pair_probe`：参数对试探。
- `archive_restart`：从历史高分样本附近重新搜索。

适用场景：

- 用于研究响应图和参数-指标映射。
- 可作为和 `adaptive_response_search` 的对照。

主要风险：

- 调度逻辑较复杂，容易出现预算被低效试验消耗的问题。
- 如果 response evidence 早期质量不高，planner 可能反复选择无效方向。

### 2.3 `semantic_group_legacy_081`

这是从历史版本恢复的旧版语义分组模式搜索，用于保留一个早期高分阶段的对照算法。

核心思想：

- 以语义组为主调度单位。
- 每个组内对参数做 pattern-search 式正负方向尝试。
- 组内探索完成后切换到下一个语义组。
- 当前版本增加了更多 group cycle 和诊断输出，避免过早停止。

适用场景：

- 复现实验历史结果。
- 作为“复杂 response scheduler 之前”的稳定基线。

主要风险：

- 依赖语义分组质量。
- 对跨组耦合、门控参数和高维联合变化的处理能力有限。
- 历史分数不能只由算法决定，还依赖当时的评分、初始材质、参考图和渲染环境。

### 2.4 `subspace_cma_es`

这是昂贵黑盒优化对照算法。它使用 CMA-ES，但不是一次性搜索全部参数，而是先构造低维语义子空间，再在当前子空间内运行 CMA-ES。

CMA-ES 的基本含义：

- 在归一化参数空间中维护一个多元高斯分布。
- 每一代从该分布采样一批候选。
- 根据候选分数更新均值、协方差和步长。
- 不需要梯度，适合不可导黑盒问题。

当前实现的额外机制：

- 根据语义组和指标瓶颈构造多个子空间。
- 每个子空间保留独立 optimizer state、archive、best history。
- 检测 plateau 后切换子空间或重启。
- 维护 global archive 和 global best。
- 切换或重启时优先围绕全局最好参数/elite 参数生成候选。

适用场景：

- 当主算法被局部模式卡住时，用作更强的黑盒搜索对照。
- 适合参数子空间已经比较明确、愿意支付更多评估成本的实验。

主要风险：

- 每一代需要多个样本，评价预算容易被消耗。
- 如果子空间选择不准，CMA-ES 会在错误空间内充分搜索。
- 多子空间切换会造成预算碎片化。

### 2.5 `cma_cold` 与 `cma_warm`

这两者都是标准 CMA-ES 基线。

`cma_cold`：

- 从当前初始参数开始。
- 不使用历史自动调参样本。
- 适合作为纯黑盒基线。

`cma_warm`：

- 使用已有 auto-adjust 历史样本做 warm start。
- 目标是让 CMA-ES 初始分布更靠近已知有效区域。

共同特点：

- 使用 `ParameterEncoder` 将 shader 参数编码到归一化向量空间。
- 优化目标是最大化当前 `fit_score`，在 CMA-ES 内部转成最小化 loss。
- 可配置 population size、sigma、seed。

主要风险：

- 全量参数维度较高时，所需样本数会快速增加。
- 对单次评价昂贵的问题不一定划算。

### 2.6 `heuristic`

这是早期启发式分阶段策略。它基于图像分析中的通道误差和 adjustment hints，按 stage policy 对参数做规则化调整。

适用场景：

- 兼容旧流程。
- 可作为低成本、可解释的 baseline。

主要风险：

- 不是真正的黑盒优化。
- 对复杂 shader、高耦合参数和非线性响应的适应能力有限。

## 3. 评分模式总览

优化器最终接收的是 `fit_score`，范围通常为 `[0, 1]`，越高越好。当前支持四种评分模式：

| fit_score_mode | 含义 | 是否当前默认 |
| --- | --- | --- |
| `research` | 使用 research metrics 的科学化综合分 | 是 |
| `human_accept` | 使用偏人工容忍度的材质相似度 | 否 |
| `perceptual` | 使用通道加权 MAE + SSIM 的严格感知分 | 否 |
| `linear` | 旧版全局 MAE 线性分 | 否 |

默认情况下，自动调参使用：

```text
fit_score = research_metrics.score / 100
```

如果 research score 不可用，则按代码中的 fallback 逻辑退回到 loss 或其他模式。

## 4. 当前默认参与优化的 Research Metrics

`research` 模式是当前主优化目标。它先计算每张图的 scientific metrics，再把部分指标转换成 optimizer guidance loss。

### 4.1 掩码与有效性检查

指标只应主要比较前景材质区域。掩码来源优先级为：

1. RGBA alpha。
2. 显式 mask。
3. fallback mask。
4. full image。

有效性检查包括：

- foreground 是否为空。
- reference/candidate mask IoU 是否至少为 `0.990`。
- 前景 bbox 中心偏移是否不超过图像尺寸的 `2%`。
- bbox 尺寸误差是否不超过 `5%`。

如果有效性失败，原始科学指标仍会报告，但优化 guidance 会施加硬惩罚：该视角 loss 至少被抬到 `0.85`。这样可以避免候选通过前景错位、mask 退化或裁剪异常获得伪高分。

### 4.2 颜色准确性：CIEDE2000 ΔE00

颜色指标在 Lab 空间计算 CIEDE2000 色差：

```text
deltaE00 = CIEDE2000(Lab_reference, Lab_candidate)
```

当前报告：

- `mean_deltaE00`：前景区域平均色差。
- `p95_deltaE00`：前景区域 95 分位色差，用于反映高光、边缘、局部异常。
- `median_deltaE00`：中位色差。
- `max_deltaE00`：最大色差。
- `rgb_bias_candidate_minus_reference`：RGB 均值偏差。
- `lab_bias_candidate_minus_reference`：Lab 均值偏差。

参与默认优化的颜色项：

```text
color_mean = g(mean_deltaE00; 10.0)
color_p95  = g(p95_deltaE00; 20.0)
```

其中：

```text
g(x; s) = x / (x + s)
```

`s` 是 half-saturation scale。当 `x = s` 时，该项 loss 为 `0.5`。

### 4.3 亮度结构

亮度使用线性 luminance：

```text
Y = 0.2126 * R + 0.7152 * G + 0.0722 * B
```

当前报告：

- `luminance_mae`：`abs(Y_candidate - Y_reference)` 的平均值。
- `luminance_bias`：`Y_candidate - Y_reference` 的有符号均值。
- `p95_luminance_abs_error`：亮度绝对误差 95 分位。
- `ssim_l`：基于 luminance 的结构相似度。

参与默认优化的亮度/结构项：

```text
luminance_mae  = g(luminance_mae; 0.20)
luminance_bias = g(abs(luminance_bias); 0.15)
structure_ssim_l = g(max(1 - ssim_l, 0); 0.15)
```

如果 SSIM-L 不可用，则该项跳过，其余权重重新归一化。

### 4.4 高光与反射

高光指标是条件指标，只在参考图确实存在可用高光区域时启用。

启用条件：

- 参考亮度 `p99 - p80 > 0.08`。
- 高光区域面积比例在 `0.002` 到 `0.35` 之间。
- 高光像素数量至少为 `16`。

报告项：

- `highlight_deltaE00`：高光区域平均 ΔE00。
- `highlight_luminance_mae`：高光区域亮度 MAE。
- `highlight_area_error`：候选高光区域面积相对误差。
- `peak_luminance_error`：峰值亮度误差。

参与默认优化的高光项：

```text
highlight =
  0.45 * g(highlight_deltaE00; 20.0)
+ 0.35 * g(highlight_area_error; 0.50)
+ 0.20 * g(peak_luminance_error; 0.25)
```

如果高光不适用，则跳过该项并重新归一化权重。

### 4.5 细节与纹理

细节指标基于 luminance 的梯度和拉普拉斯响应：

- `gradient_loss`：参考图和候选图梯度幅值差异。
- `laplacian_loss`：参考图和候选图拉普拉斯响应差异。

参与默认优化的细节项：

```text
detail_texture =
  0.60 * g(gradient_loss; 0.25)
+ 0.40 * g(laplacian_loss; 0.50)
```

该项权重较低，主要用于避免纹理和边缘细节明显偏离。

### 4.6 单视角 Research Loss 与 Score

单视角 loss 由各组件加权平均得到：

```text
loss = sum(component_i * weight_i) / sum(weight_i)
if validity_failed:
    loss = max(loss, 0.85)
score = 100 * (1 - clamp01(loss))
fit_score = score / 100
```

默认组件初始权重：

| 组件 | 原始权重 | 说明 |
| --- | ---: | --- |
| `color_mean` | 0.35 | 整体颜色准确性 |
| `color_p95` | 0.15 | 局部/尾部颜色误差 |
| `luminance_mae` | 0.20 | 整体明暗误差 |
| `luminance_bias` | 0.10 | 系统性偏亮/偏暗 |
| `structure_ssim_l` | 0.20 | 亮度结构相似度 |
| `highlight` | 0.12 | 条件高光/反射项 |
| `detail_texture` | 0.06 | 条件细节/纹理项 |

注意：当某些条件项不可用时，实际输出的 `weights` 会在可用组件之间重新归一化。

## 5. 多视角聚合

如果一个项目存在多个视角，系统会先对每个视角独立计算 research metrics，再做聚合。

research metrics 的聚合公式为：

```text
final_loss = clamp01(0.65 * mean_loss + 0.20 * p90_loss + 0.15 * max_loss)
score = 100 * (1 - final_loss)
optimization_fit_score = score / 100
```

该设计的含义：

- `mean_loss` 保证整体平均效果。
- `p90_loss` 关注较差视角。
- `max_loss` 防止某一个视角完全失败。

自动调参时，`research` 模式下最终传给优化器的分数是多视角聚合后的 `optimization_fit_score`，来源为 `aggregate_research_score`。`mean_fit_score` 仍会保留在 summary 中作为诊断字段，但不再作为 research 多视角优化目标。

validity failed 的视角不会被静默丢弃；它们会带着惩罚后的 loss 进入 `mean_loss`、`p90_loss` 和 `max_loss`。因此任一视角的前景错位或 mask 失败都会真实压低最终优化分数。

## 6. 其他可选评分模式

### 6.1 `perceptual`

`perceptual` 模式主要由通道加权 MAE 和 SSIM 组成。

通道加权 MAE：

```text
weighted_mae = sum(rgb_mae_channel * normalized_channel_weight)
```

默认通道权重：

| 通道 | 权重 |
| --- | ---: |
| `base_color_main_texture` | 0.30 |
| `metallic_smoothness_specular` | 0.18 |
| `emission` | 0.12 |
| `fresnel_rim` | 0.12 |
| `shadow_occlusion` | 0.10 |
| `color_grading_hsv_contrast` | 0.18 |

如果某个通道无效，则跳过该通道，并对剩余通道重新归一化。

MAE 分支使用指数映射：

```text
mae_branch = exp(-4.0 * weighted_mae)
```

SSIM 分支：

```text
ssim_branch = clamp01(ssim)
```

综合分：

```text
perceptual_fit_score = 0.7 * mae_branch + 0.3 * ssim_branch
```

如果 SSIM 不可用，则退化为 MAE-only。

### 6.2 `human_accept`

`human_accept` 是偏人工容忍度的材质相似度，不是当前默认 research 目标。它由多个较宽松组件组合：

| 组件 | 权重 | 含义 |
| --- | ---: | --- |
| `foreground_color_distribution` | 0.32 | 前景 RGB/亮度/饱和度分布 |
| `material_channel_statistics` | 0.24 | 材质语义通道统计 |
| `relaxed_structure` | 0.14 | 放宽后的结构相似度 |
| `material_feature_statistics` | 0.15 | 材质特征区域误差 |
| `foreground_bbox_alignment` | 0.05 | 前景 bbox 对齐 |
| `strict_pixel_guardrail` | 0.10 | 严格像素分的低权重约束 |

多个误差项通常通过指数函数转为分数：

```text
score_component = exp(-decay * error)
```

它的作用是更接近“人眼觉得是否可以接受”，但作为论文/实验主优化目标时不如 research metrics 透明。

### 6.3 `linear`

`linear` 是旧版全局 MAE 分数：

```text
fit_score = clamp01(1 - rgb_mae)
```

它简单直观，但容易被背景、大面积低价值区域或非材质因素主导，因此当前不推荐作为主实验指标。

## 7. 优化器与指标的关系

所有优化器最终都只消费一个主分数 `fit_score`，但部分优化器会额外读取指标组件用于调度。

| optimizer | 使用主分数 | 是否读取指标组件 | 主要使用方式 |
| --- | --- | --- | --- |
| `adaptive_response_search` | 是 | 是 | 记录每个参数对各 research component 的响应 |
| `semantic_group` | 是 | 是 | ResponseMap、瓶颈指标、参数排序、planner 调度 |
| `semantic_group_legacy_081` | 是 | 部分 | 主要按语义组和分数变化搜索 |
| `subspace_cma_es` | 是 | 是 | 用指标/语义选择子空间，CMA-ES 内部主要看 loss |
| `cma_cold` | 是 | 少量 | 黑盒采样，主要只看最终 loss |
| `cma_warm` | 是 | 少量 | 黑盒采样，使用历史样本 warm start |
| `heuristic` | 是 | 是 | 使用 adjustment hints 和通道误差做规则调参 |

因此，评价指标有两层作用：

1. 作为最终目标：通过 `fit_score` 决定候选好坏。
2. 作为诊断与调度证据：告诉调度器当前是颜色、亮度、结构、高光还是纹理在拖后腿。

## 8. 当前需要特别注意的问题

### 8.1 评分一致性优先于优化器复杂度

如果标准答案材质在当前渲染/截图/评分链路下不能得到接近满分，那么优化器再强也只能优化到一个错误目标。因此正式实验前必须做 identity check：

1. 使用参考图对应的标准 `.lmat`。
2. 不改变参数，只重新截图。
3. 计算 research score。
4. 检查是否接近理论满分。

如果 identity check 不通过，应优先排查参考图、Laya 捕获、色彩空间、相机、光照、后处理、截图裁剪和 mask，而不是继续叠加优化策略。

### 8.2 Best 不是理论解，只是当前评分系统下的最好样本

当前主算法把 best 作为搜索中心，是为了防止探索跑飞；但这并不意味着 best 一定是全局最优。对于强耦合参数，仍然需要：

- 低频多参数 interaction probe。
- 子空间黑盒搜索对照。
- 真实响应证据积累。
- 必要时进行更昂贵的全局/分层黑盒优化实验。

### 8.3 指标解释应区分“优化目标”和“验收证据”

软饱和归一化 loss 是给优化器使用的连续目标；原始 scientific metrics 仍然是论文、验收和人工分析时更有物理意义的证据。例如：

- 论文中应报告 `mean_deltaE00`、`p95_deltaE00`、`luminance_mae`、`ssim_l` 等原始值。
- 优化过程可使用归一化 guidance loss 来获得更稳定的搜索方向。

## 9. 建议的实验报告字段

为了让不同算法可比较，建议每次实验至少记录：

- optimizer 名称和参数配置。
- fit_score_mode。
- 初始 fit score、best fit score、最终 fit score。
- best iteration。
- research score/loss。
- research components 和 weights。
- 原始 scientific metrics。
- 多视角 `mean_loss`、`p90_loss`、`max_loss`。
- 优化器 research_summary。
- identity check 结果。

这样才能区分三类问题：

- 优化器没有找到好方向。
- 评分系统没有正确表达视觉目标。
- 渲染/截图环境导致标准答案也无法复现。
