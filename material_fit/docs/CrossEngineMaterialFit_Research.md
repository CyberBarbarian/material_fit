# 跨引擎材质自动拟合：科学问题形式化与研究路线

> 本文档把 `tools/material_fit` 工具背后的工程问题抽象成一个可被学术界审视的研究问题，
> 系统梳理已知方法、当前实现的位置、潜在的创新贡献，以及把它推进到论文级别工作的路线图。
> 它是技术文档 `MaterialAutoFitTool.md` 的姊妹篇——前者讲"工具怎么用"，本文讲"问题是什么、
> 学术上怎么定位、怎么发表"。

---

## 摘要

我们考察这样一个工程问题：把一个在 Unity 引擎中渲染良好的 3D 模型迁移到 Laya 引擎下渲染时，
由于两端 shader 程序不同、可调材质参数集合不同、光照管线实现不同，迁移后的画面通常与原画
有显著差异。**目标是自动调整 Laya 材质实例上暴露的 uniform 参数，使 Laya 渲染结果在
视觉上尽量逼近 Unity 参考画面**。

本文把它形式化为一类**约束盒形参数空间下的、不可导黑盒成像逆问题**：

$$\theta^* = \arg\min_{\theta \in \Theta}\; \mathcal{L}\big(R_{\text{laya}}(\theta),\; I^{\text{unity}}_{\text{ref}}\big)$$

其中 $R_{\text{laya}}$ 是真实的 Laya 渲染管线（黑盒、不可导、调用代价 $\sim 1\text{-}3$ s/次），
$\Theta = \prod_i [\ell_i, u_i] \subset \mathbb{R}^n$ 是 Laya 目标 shader 暴露 uniform 形成的参数空间
（依 shader 而异，$n \in [10, 100]$），$\mathcal{L}$ 是结合像素层、感知层、材质语义层的多分量损失。

它跟既有的 inverse rendering / SVBRDF capture 文献在数学上同源，但在**真实生产引擎在环、
跨引擎 shader 语义映射、艺术家可解释多通道损失**这三点上具有**该领域目前未公开发表的独特配置**，
我们认为有作为论文贡献的潜力。

文末给出一条从"换掉当前启发式调度"出发、最终通向"可微代理 renderer + 多目标优化 + 跨引擎
基准数据集"的五阶段研究路线，每阶段都给出可发表性评估、所需工作量与所需算力。

---

## 1. 问题背景

### 1.1 工业动机

H5 / 微信 / 抖音小游戏对包体大小、运行时性能有严格预算（包体 < 5 MB、首屏 < 30 MB、
中端机 60 fps）。许多游戏的"主战场"是 Unity 高保真版本，但需要派生一个 Laya 引擎下的
小游戏版本作为引流入口。

主战场 Unity 版本里的角色、场景、特效，普遍使用了：

- 自定义 ShaderGraph 或复杂 ShaderLab（多 pass、多 texture、复杂 BRDF）；
- HDRP / URP 的体积光、屏幕空间反射、后处理；
- 反射探针、光照贴图、烘焙间接光。

这些能力在 Laya 端要么不存在、要么必须以**简化版 shader** 替代以满足性能预算。结果是：
**模型一致、贴图一致，但渲染不一致**——常见现象包括"颜色变浅"、"高光丢失"、"阴影变暗"、
"边缘光过强"、"金属感不足"等，且每个项目、每个角色的偏差模式不同。

把这件事交给技术美术（TA）人手调参，单个角色平均耗时 0.5-2 个工作日；一个中型项目几百个
角色，工作量数百人日。**这是一个非常典型的"重复性、规则化、人眼可评判但机制可形式化"的任务**——
理论上应当可以自动化。

### 1.2 为什么不能简单解决

我们已经验证了三条直接的路都走不通：

| 直接路径 | 不可行的原因 |
|---|---|
| 把 Unity shader 整段移植到 Laya | 性能预算严重不够、Laya 渲管线缺反射探针等基础能力 |
| 用美术手调 + 让 LLM 一次性给出参数 | LLM 给的参数没有视觉反馈循环、且改 `.lmat` 时不可重现地破坏文件结构 |
| 直接对位拷参数 (`_Color → u_BaseColor` 等) | 两边 shader 参数语义不一一对应、即便对应也未必视觉等价 |

剩下唯一可行的范式是：**让 Laya 引擎本身成为评分器，迭代地修改材质参数 → 真实重渲 → 看图打分 → 反馈下一步**。
这就是 `tools/material_fit` 当前在做的事。

---

## 2. 工具现状

### 2.1 已实现的能力

详细说明见 `MaterialAutoFitTool.md`。这里只列与本文档相关的关键点：

- **Unity 侧解析**：`tools/material_fit/unity/shader_parser.py` 解析 ShaderLab `Properties` 块
  得到参数定义；Unity Editor 脚本导出材质实例的真实数值得到 `material_params.json`。
- **Laya 侧解析**：`tools/material_fit/laya/shader_parser.py` 解析 Laya Shader3D 的
  `uniformMap` 块；`lmat_io.py` 读写 `.lmat` 文件（带写入护栏，详见 `tests/test_lmat_io.py`）。
- **图像差异分析**：`tools/material_fit/vision/diff_analysis.py` 把候选图与参考图按"暗部
  / 中间调 / 高光 / 极亮 / 边缘"分区，分别算 RGB MAE、亮度偏差、饱和度偏差、对比度偏差，
  汇总进 `material_channels` 字典。这一层提供了**通道级**的视觉评分。
- **优化器主循环**：`tools/material_fit/optimizer/adjustment_algorithm.py` 实现了
  "stage-aware coordinate descent"——把参数分到 6 个 stage（base color / shadow / specular /
  reflection-matcap / fresnel-emission / global color grade），每轮依据 channel bias 推导
  局部更新方向。配套有 `update_stage_progress / choose_stage / should_abort_global` 等状态机。
- **写入与重渲闭环**：`fit_material.py` 调用 `lmat_io.write_candidate_lmat` 把候选参数
  落盘到 `.lmat`，然后通过 `screen_capture` 的桌面区域抓屏拿到 Laya 重渲后的实图，作为
  下一轮迭代的输入。
- **前后端可视化**：`tools/material_fit_ui/` 提供 Vue 3 前端 + FastAPI 后端，能新建项目、
  选输入文件、配置算法、启动 / 取消任务、实时观察迭代结果。
- **测试覆盖**：`tools/material_fit/tests/` 含 25 个 pytest 单元测试，覆盖 lmat 写入护栏、
  stage 推进、真实跑用例的 stage 轨迹回归等。

### 2.2 在真实跑动中暴露的局限

在用户的 `fish_1580` 真实用例上，跑 12 轮迭代得到的结果（详见
`output/fish_1580/auto_adjust/`）：

- 12 轮迭代**全部**在 base_color stage（已通过加 `max_iterations` 与 `stuck` 机制修复）；
- 即使在已修复的并行版本下，单轮启发式更新带来的图像分数改善仍然 < 0.5%；
- 调整 `u_BaseColor` 从 `[1,1,1,1]` 到 `[0.36, 0.28, 0.08, 1]` 后，渲染图**几乎没有改变**——
  说明这个材质的渲染颜色被其它参数（推测是 Matcap / IBL / Fresnel）主导，base color 杠杆很弱；
- 启发式更新公式 `new = old + bias × coeff × gain` 在多模态非凸 loss landscape 上很容易陷入
  局部最小，且不具备越过局部峰的能力。

这些都不是工程 bug，而是**方法学层面的局限**——这正是把它推进为研究问题的入口。

---

## 3. 难点：为什么这个问题不平凡

### 3.1 黑盒不可导的渲染器

$R_{\text{laya}}$ 是 Laya 引擎本身——不开放梯度接口，每次评估涉及：

- 写 `.lmat` 文件 → Laya 资源系统重新加载材质（毫秒）；
- 浏览器/桌面客户端重渲一帧（10-50 ms）；
- 桌面截屏 + I/O（100-500 ms）；
- diff 分析（<100 ms）。

整体 **每次 $R(\theta)$ 调用 1-3 秒**。在 100 维参数空间下，纯随机搜索需要的评估次数可达
$10^4$ 量级，按这个评估代价就是 3-8 小时单材质——已经接近"美术手调"的下限，**算法必须达到
比随机搜索快至少一个数量级才有工程价值**。

### 3.2 跨引擎语义鸿沟

Unity 端 ShaderLab 的 `_Color`、`_Smoothness`、`_FresnelPower` 这些参数名是 Unity 的命名传统，
Laya 端 `u_BaseColor`、`u_GGXSpecular`、`u_FresnelPow` 是另一套命名传统。即便参数语义大致
对应，**值域和数学含义未必对应**：

- Unity HDRP 的 `_Smoothness` 是 perceptual roughness 的反值（$\sigma = 1 - r$），Laya 的
  `u_Smoothness` 可能是 roughness 直接或者 power 的对数；
- Unity 的 `_BaseColor` 在 sRGB 下 `(1,1,1)`，Laya 端可能在 linear 下 `(1,1,1)`，gamma 走廊不同；
- Unity 的反射探针对 BRDF 的贡献，在 Laya 里通过 IBL + Matcap 两个通道近似，**没有
  one-to-one 映射**。

这导致**纯算法搜索找到的最优解 $\theta^*$，跟 Unity 端材质实例上的语义"最近"参数 $\theta^{\text{unity}}$
不一定相等**。当前工具的 preanalysis 阶段试图解决这件事，但它本身又是一个 NLP / semantic
matching 子问题，引入了新的不确定性。

### 3.3 参数耦合（非可分性）

许多 uniform 参数在视觉效果上是**耦合**的——比如：

- $\{u_{\text{Metallic}},\, u_{\text{Smoothness}},\, u_{\text{SpecularIntensity}},\, u_{\text{IBLMapIntensity}}\}$ 共同决定
  "这块材质看起来有多金属"；
- $\{u_{\text{FresnelIntensity}},\, u_{\text{FresnelPow}},\, u_{\text{FresnelColor}},\, u_{\text{FresnelThreshold}},\, u_{\text{FresnelSmooth}}\}$ 共同决定边缘光的形状与亮度；
- $\{u_{\text{BaseColor}},\, u_{\text{Gamma\_Power}},\, u_{\text{AdjustLightness}}\}$ 共同决定整体明暗调。

也就是说损失函数 $\mathcal{L}(\theta)$ **不可分**：

$$\mathcal{L}(\theta) \neq \sum_i \mathcal{L}_i(\theta_i)$$

这意味着 coordinate descent 类算法（每次只动一个参数或一个块）**有理论上的结构性劣势**——
当真实最优解需要多个耦合参数同时移动到特定组合时，coordinate descent 容易陷入"每个轴看
都不能再降，但联合调整能下降很多"的鞍点附近。

### 3.4 多模态非凸 loss landscape

直觉上，"$u_\text{BaseColor}$ 偏红多少 → 输出像素偏红多少"是单调的；但放到 $n$ 维空间里，
存在大量的"等价视觉"组合：

- 高 $u_\text{Metallic}$ + 低 $u_\text{IBLMapIntensity}$ ≈ 低 $u_\text{Metallic}$ + 高 $u_\text{SpecularIntensity}$
- 高 $u_\text{BaseColor}$ + 低 $u_\text{Gamma\_Power}$ ≈ 低 $u_\text{BaseColor}$ + 高 $u_\text{Gamma\_Power}$（在某些区域）

这种**多解性**意味着 $\mathcal{L}$ 有多个等高的局部最优解，单点起步的局部搜索很容易卡在
其中一个局部最优而无法看到另一个可能更好的远处最优。

### 3.5 评估代价高 vs 维度高

这是黑盒优化经典的"高维 + 高评估代价"双难题（high-dimensional expensive black-box）。
Vanilla Bayesian Optimization 在 $n > 15$ 时 GP 就难以拟合，纯 random search 在 $n = 30$
时需要 $\sim 10^4$ 次评估，CMA-ES 在 $n = 30$ 时需要 $\sim 10^3$ 代评估（每代约 14 个候选，
即 $\sim 1.4 \times 10^4$ 次评估），**全部都超过我们 $\sim 100\text{-}300$ 评估的预算**。
所以**单纯把现成黑盒优化器套上来不够**——必须利用问题的特殊结构（先验、可分块、半线性
段、可微代理等）来收缩搜索代价。

### 3.6 多维评判标准（多目标）

人眼对"两张图像不像"有多种维度的判断：

- 整体色调（warm/cool）
- 亮度对比（明暗层次）
- 高光强度与位置
- 阴影颜色与深浅
- 边缘光（rim light）的存在与色彩
- 金属感（metallic look）
- 自发光区强度
- 整体饱和度与对比度

把这些都压缩成一个标量（比如 RGB MAE）会**丢失方向性**——譬如"颜色对了但高光全无"和
"颜色完全错但高光位置对了"可能 MAE 接近，但艺术评判完全不同。这天然是一个**多目标优化
问题**，单标量化必然引入信息损失。

---

## 4. 形式化的科学问题

### 4.1 决策变量与参数空间

定义 Laya 目标 shader 的 uniform 集合

$$\mathcal{U} = \{u_1, u_2, \ldots, u_n\}$$

其中 $u_i$ 是单个 scalar、bool 或者 vec2/3/4 等。把每个 uniform 展平为 scalar 维度后：

$$\theta = (\theta_1, \theta_2, \ldots, \theta_d) \in \mathbb{R}^d, \quad d = \sum_i \dim(u_i)$$

每个分量受 shader uniformMap `range` 字段或语义启发式给出的盒约束：

$$\Theta = \prod_{j=1}^{d} [\ell_j, u_j] \subset \mathbb{R}^d$$

**关键认识**：$\mathcal{U}$ 和 $\Theta$ **依目标 shader 而异**，不是固定的——这是这个问题区别于
经典 SVBRDF capture 的一大特征（后者通常假定固定的 BRDF 模型如 Disney BRDF + 一组固定
通道 albedo/roughness/metallic/normal）。

### 4.2 前向模型

$$R_{\text{laya}}: \Theta \times \mathcal{S} \rightarrow \mathbb{R}^{H \times W \times 3}, \quad I_\theta = R_{\text{laya}}(\theta;\, \mathcal{S})$$

其中 $\mathcal{S}$ 包含场景的所有非材质要素（模型几何、相机、灯光、贴图）。在我们的场景里
$\mathcal{S}$ 是固定的——同一个 Laya 工程、同一个相机视角、同一组贴图——所以可以视
$R_{\text{laya}}$ 为关于 $\theta$ 的单变量函数。

性质：
- **不可导**：无法计算 $\partial R / \partial \theta$。
- **不可批量**：一次只能渲一个 $\theta$，并行需要起多个 Laya 实例（重资源）。
- **确定性**：固定 $\theta$ 总是产生相同 $I_\theta$（无随机性）。
- **有界**：$I_\theta \in [0, 1]^{H \times W \times 3}$。

### 4.3 损失函数

定义参考图

$$I^* = R_{\text{unity}}(\theta^{\text{unity}};\, \mathcal{S}^{\text{unity}}) \in \mathbb{R}^{H \times W \times 3}$$

注意 $R_{\text{unity}}$ 与 $R_{\text{laya}}$ 是**不同的渲染函数**，$\mathcal{S}^{\text{unity}}$ 与
$\mathcal{S}$ 也通常不完全相同（Unity 的反射探针在 Laya 里没有等价物）。所以**$I^*$ 不是
$R_{\text{laya}}$ 函数族的可达点**，也就是说**最优损失不会是 0**——存在不可消除的**领域差
$\Delta_{\text{domain}}$**：

$$\inf_{\theta \in \Theta} \mathcal{L}\big(R_{\text{laya}}(\theta), I^*\big) \geq \Delta_{\text{domain}} > 0$$

任何算法都不能突破这个下界。因此把目标定成"达到某个 perfect score"是不切实际的；**正确的
评判应当是"达到接近 $\Delta_{\text{domain}}$ 的水平"**——这又涉及如何估计 $\Delta_{\text{domain}}$
本身（见第 8 节）。

#### 4.3.1 像素层损失

$$\mathcal{L}_{\text{pixel}}(I_\theta, I^*) = \frac{1}{H W} \sum_{p} \|I_\theta(p) - I^*(p)\|_1$$

简单、可解释、便宜，但跟人眼一致性差。

#### 4.3.2 多通道材质语义损失（本工具当前用的）

把图像按亮度/饱和度自动分成 $K$ 个语义区域 $\{\Omega_k\}$（暗部/中间调/高光/极亮/边缘），每区域
计算多个统计量，再加权汇总：

$$\mathcal{L}_{\text{material}}(\theta) = \sum_k w_k \Big[ \alpha_k \cdot \text{MAE}_{\text{rgb}}(\Omega_k) + \beta_k \cdot |\text{bias}_{\text{luma}}(\Omega_k)| + \gamma_k \cdot |\text{bias}_{\text{sat}}(\Omega_k)| + \delta_k \cdot |\text{bias}_{\text{contrast}}(\Omega_k)| \Big]$$

这一层是当前工具实现的核心，且与艺术家直觉对应：$w_k$ 让美术按"我更在乎金属感"调整高光区
权重。

#### 4.3.3 感知损失

$$\mathcal{L}_{\text{percep}}(I_\theta, I^*) = \big\|\phi(I_\theta) - \phi(I^*)\big\|_2^2$$

其中 $\phi$ 是预训练 VGG / LPIPS 网络的特征提取，能捕获结构、纹理、形状一致性。代价是
计算稍贵且需要维护预训练权重。

#### 4.3.4 综合损失

$$\mathcal{L}(\theta) = \lambda_1 \mathcal{L}_{\text{pixel}} + \lambda_2 \mathcal{L}_{\text{material}} + \lambda_3 \mathcal{L}_{\text{percep}}$$

UI 暴露 $\{\lambda_i\}$ 与 $\{w_k\}$ 给美术调，相当于把"风格意图"参数化。

#### 4.3.5 多目标版本

$$\mathbf{L}(\theta) = (\mathcal{L}_{\text{base}}, \mathcal{L}_{\text{shadow}}, \mathcal{L}_{\text{specular}}, \mathcal{L}_{\text{matcap}}, \mathcal{L}_{\text{fresnel}}, \mathcal{L}_{\text{emission}})$$

求 Pareto 最优集

$$\mathcal{P} = \{\theta \in \Theta : \nexists \theta' \in \Theta,\, \mathbf{L}(\theta') \leq \mathbf{L}(\theta) \text{ and } \mathbf{L}(\theta') \neq \mathbf{L}(\theta)\}$$

让美术从 $\mathcal{P}$ 中按偏好挑选。

### 4.4 约束

- **盒约束**：$\theta_j \in [\ell_j, u_j]$。
- **类型约束**：bool 参数 $\theta_j \in \{0, 1\}$，颜色 sRGB 通道 $\in [0, 1]$ 等。
- **结构约束**：例如 vec4 颜色的 alpha 通常应保持原值，只调 RGB；vec2 ST 的 tiling/offset
  通常不应被算法乱动；这些被工具的写入护栏防御性地保护。
- **语义约束（先验）**：preanalysis 阶段从 Unity 材质实例派生出"此参数大概在 $[a, b]$ 之内"
  的概率先验，用以收窄 $\Theta$。

### 4.5 复杂度分析

$d \approx 30$（FishStandard），评估代价 $T_{\text{eval}} \approx 2$ s。预算 $B = 200$ 评估，则
**总搜索时间 $\approx 6.7$ 分钟**——这是工程上可以接受的上限。

随机搜索期望误差按 $O(B^{-1/d})$ 衰减，$d = 30, B = 200$ 时几乎不收敛。CMA-ES 在 $d = 30$ 时
需要 $\sim 10^3$ 代才达到 $10^{-3}$ 精度，按 $\lambda \approx 14$ 算约 $1.4 \times 10^4$ 次评估，**远超
预算 70 倍**。所以**不利用问题结构、纯黑盒方法走不通**——必须靠先验、降维、代理三种手段中的至
少一种来压缩有效搜索维度。

---

## 5. 相关研究综述

我们把跟本问题相关的领域分四块梳理。每块给出代表性论文与跟我们问题的差距。

### 5.1 Inverse Rendering / SVBRDF Capture

这是最直接相关的领域。给定一张/多张图像，反推材质属性（albedo、normal、roughness、metallic）。

**代表工作**：

- Aittala et al., "Two-shot SVBRDF capture for stationary materials" (TOG 2015) [^aittala2015]
- Deschaintre et al., "Single-Image SVBRDF Capture with a Rendering-Aware Deep Network" (TOG 2018) [^deschaintre2018]
- Gao et al., "Deep Inverse Rendering for High-resolution SVBRDF Estimation from an Arbitrary Number of Images" (TOG 2019) [^gao2019]
- Henzler et al., "Generative Modelling of BRDF Textures from Flash Images" (SIGGRAPH Asia 2021) [^henzler2021]
- Boss et al., "Two-Shot Spatially-Varying BRDF and Shape Estimation" (CVPR 2020) [^boss2020]

**与我们问题的差距**：

- 他们假定**固定的 BRDF 模型**（通常是 Disney BRDF 的子集），输出一组固定的纹理。我们的
  shader 是**任意的、跨引擎的**，参数空间随 shader 变化。
- 他们用**自训练的可微 renderer**评估候选材质。我们用**生产引擎**（Laya）评估，没有梯度。
- 他们的输入通常是**单张/几张照片**，含光照线索；我们的输入是**已经渲染好的引用图**，
  且光照已经被 baked 在图里。

### 5.2 黑盒/无导数优化

针对评估贵、不可导的连续优化问题。

**代表方法**：

- **CMA-ES**（Hansen 2003）[^hansen2003]：进化策略，自适应协方差矩阵，连续黑盒优化的金标准。
- **Bayesian Optimization with GP**（Mockus 1975 [^mockus1975]，Snoek et al. 2012 [^snoek2012]）：
  适合 $d < 15$、评估极贵的场景。
- **TuRBO**（Eriksson et al. 2019 [^eriksson2019]）：高维 BO 的 trust region 变体，能扩展到 $d = 100+$。
- **Differential Evolution**（Storn & Price 1997 [^storn1997]）：种群进化算法，鲁棒但评估贵。
- **Random Embedding BO**（Wang et al. 2016 [^wang2016]）：在低维子空间做 BO，高维方法。

**与我们问题的差距**：

- 这些方法都不利用问题的**渲染结构**——例如 shader 的可分块（base color 块和 specular 块在
  视觉上影响不同图像区域），先验（Unity 材质实例已经给出一组接近正确的初值）。
- 都是单目标方法（虽有多目标变体如 MO-CMA-ES、ParEGO）。

### 5.3 可微渲染（Differentiable Rendering）

另一条直接相关线。重新实现一个**可导的 renderer**，让梯度反传通过 shading equations。

**代表工作**：

- **Mitsuba 3**（Jakob et al. 2022 [^jakob2022]）：完整可微 path tracer，支持 PyTorch interop。
- **nvdiffrast**（Laine et al. 2020 [^laine2020]）：高效的 GPU 可微 rasterizer。
- **PyTorch3D**（Ravi et al. 2020 [^ravi2020]）：面向研究的可微 3D 库。
- **Soft Rasterizer**（Liu et al. 2019 [^liu2019]）：可微 rasterization 的早期方案。
- **Inverse rendering 综述**：Tewari et al., "State of the Art on Neural Rendering" (CGF 2020) [^tewari2020]。

**与我们问题的差距**：

- 这些 renderer 实现的是**论文作者自己的 BRDF 模型**——不是 Laya 的 FishStandard。
- 即便我们重新实现一份 FishStandard 的可微版本（这是可行的，因为 GLSL 都是闭式表达式），
  跟真实 Laya 的输出之间**仍然有 domain gap**（精度、过滤、压缩、后处理），梯度优化得到
  的解需要在真实 Laya 上验证 + 再微调。
- 但这条路**长期 ROI 极高**——一次写好可微 FishStandard，后续每个新材质几乎免费。

### 5.4 感知损失与图像质量度量

把 RGB MAE 替换为更接近人眼感知的距离。

**代表工作**：

- **SSIM** (Wang et al. 2004) [^wang2004]：结构相似性指标。
- **LPIPS** (Zhang et al. 2018) [^zhang2018]：基于 VGG/AlexNet 特征的可学习感知距离。
- **DISTS** (Ding et al. 2020) [^ding2020]：兼顾结构与纹理的感知距离。
- **FID / KID**：分布级感知距离，常用于生成模型评估。

**与我们问题的契合度**：直接可用作 $\mathcal{L}_{\text{percep}}$。本工具计划在 Phase 2 引入 LPIPS 作
为损失项之一。

### 5.5 多目标进化算法

**代表工作**：

- **NSGA-II** (Deb et al. 2002) [^deb2002]：经典多目标遗传算法。
- **MOEA/D** (Zhang & Li 2007) [^zhang2007]：分解式多目标进化。
- **MO-CMA-ES** (Igel et al. 2007) [^igel2007]：多目标 CMA-ES 变体。

**与我们问题的契合度**：当艺术家明确需要 Pareto 候选浏览时启用，是天然的 fit。

### 5.6 跨引擎/跨域材质迁移

这一类工作非常少——这本身就是一个**机会窗口**。我们能找到的间接相关：

- "Automatic shader simplification using surface signal approximation"（Sitthi-Amorn et al. 2011 [^sitthi2011]）：
  shader 自动简化，但目标是性能优化、不是跨引擎一致性。
- "Style transfer for shaders"（Sloan & Li, GPU Gems）：偏工程经验，非系统方法。
- 现代游戏 ToC（如 Unreal → Unity 迁移）的工业实践通常不公开发表。

**这是潜在的论文创新点**——跨引擎材质迁移作为一个**正式的研究问题**目前学术界尚未充分定义
和评估。

---

## 6. 提议的研究路线

按"工作量↑、收益↑、可发表性↑"递增顺序排列。

### Phase 1：黑盒优化器替换启发式（1-2 周）

**目标**：把 `propose_next_params` 的启发式替换为标准 CMA-ES，用**当前启发式**作为 warm-start。

**做法**：

1. 在 `tools/material_fit/optimizer/` 下加 `cma_es_optimizer.py`，封装 PyPI `cma` 包。
2. 用启发式跑 5 轮得到 $\theta^{(5)}$ 作为 CMA-ES 的初始均值 $m_0$。
3. 用 stage 划分初始化协方差矩阵 $C_0$：同 stage 内参数 $C_{ij}$ 大、跨 stage 小，等价于
   告诉 CMA-ES "我猜这些参数耦合"。
4. 标量化损失 $\mathcal{L} = \mathcal{L}_{\text{material}}$（沿用当前实现），先不引入 LPIPS。
5. 跑 200 评估预算，对比启发式 vs CMA-ES vs 启发式+CMA-ES warm-start 三种方案。

**预期成果**：单材质收敛到接近 $\Delta_{\text{domain}}$ 的水平，迭代次数从当前 12 轮的"几乎无效"
变成 50 轮的"明显改善"。

**可发表性**：低——CMA-ES 套用本身没有学术新意。但为后续阶段提供 baseline。

### Phase 2：多通道感知损失 + 艺术家可控权重（1 周）

**目标**：引入 LPIPS、给 $\mathcal{L}_{\text{material}}$ 的权重 $w_k$ 暴露 UI，让艺术家"用滑块表达美学偏好"。

**做法**：

1. `pip install lpips`，加 `tools/material_fit/vision/perceptual_loss.py`。
2. AlgoConfigView 加 6 个权重滑块（base / shadow / specular / matcap / fresnel / emission）+ 一
   个 LPIPS 系数 $\lambda_3$。
3. 每次保存权重，重新跑 CMA-ES——观察艺术家偏好如何改变最优解。

**预期成果**：可视化"权重 → 最优材质"的可解释映射。

**可发表性**：中——多通道材质语义损失 + 艺术家偏好建模在 graphics tools 领域可作为系统贡献。

### Phase 3：可微代理 renderer（3-6 周）

**目标**：用 PyTorch 重新实现 FishStandard 的所有 shading 数学，让梯度可以反传到 $\theta$。

**做法**：

1. 把 `assets/resources/shader/FishStandard.shader` 的 fragment 部分逐行翻译成 PyTorch 算子
   （Schlick Fresnel、GGX specular、Lambert diffuse、IBL 球谐近似、Matcap 投影等）。
2. 在固定 $\mathcal{S}$（同一个相机、同一组贴图、同一个模型）下，校准代理 renderer 的输出
   与真实 Laya 输出，记录 calibration error $\epsilon_{\text{calib}}$。
3. 优化跑在代理 renderer 上：Adam 优化器，10K 迭代几乎免费。
4. 拿到优化结果后，用真实 Laya 验证；如果偏差超过 $\epsilon_{\text{calib}}$ 阈值，用 CMA-ES
   做 50 评估的 fine-tuning。

**预期成果**：单材质收敛时间从 6 分钟降到 30 秒。批量处理 100 个材质从 10 小时降到 1 小时。

**可发表性**：**高**——这是潜在的论文核心贡献，叫做"**production-engine-aligned differentiable surrogate
for cross-engine material fitting**"。学术上没有完全相同的工作。

### Phase 4：多目标扩展（2 周）

**目标**：把 Phase 1-3 的优化器改成 MO-CMA-ES 或 NSGA-II，输出 Pareto 候选集。

**做法**：

1. 沿用代理 renderer 做评估。
2. 把 6 个 $\mathcal{L}_k$ 当独立目标。
3. 跑 NSGA-II 30 代，输出 Pareto 前沿上 5-10 个候选。
4. UI 加 "Pareto 浏览" 视图，让美术拖动 → 实时切换候选材质 → 实时看效果。

**预期成果**：艺术家从 "yes/no 接受算法结果" 升级到 "在多个权衡方案中挑选"。

**可发表性**：中-高——多目标交互式材质设计在 graphics tools 领域有一定新意。

### Phase 5：跨引擎材质迁移基准（2-3 个月）

**目标**：建立**第一个公开的跨引擎材质迁移基准数据集**，含若干 Unity-Laya 配对模型 + 对应 Unity 材质实例
+ Unity 渲染图 + Laya shader + 期望的"美术认可"参数解。

**做法**：

1. 与游戏团队合作，收集 50-100 个真实 Unity-Laya 迁移案例。
2. 每个案例：Unity 模型 + Unity 材质 + Unity 渲染图（参考） + Laya 模型（同形状） + Laya shader
   + 美术手调达到的 "ground-truth" Laya 材质参数。
3. 提供标准评估脚本：给一个算法 → 输出每个案例的最终 Laya 参数 → 算法 vs ground-truth 的
   $\mathcal{L}$、$\mathcal{L}_{\text{percep}}$、艺术家盲评得分。
4. 把 Phase 1-4 的所有算法在该基准上跑一遍，发表 + 开放数据。

**可发表性**：**最高**——基准数据集 + 系统综述论文，CGF / TVCG / SIGGRAPH ASIA Tech Briefs 级别。

---

## 7. 创新点提炼

按"潜在论文价值"从高到低：

### 7.1 Production-Engine-in-the-Loop Optimization（生产引擎在环优化）

**新意**：现有 inverse rendering 文献（Mitsuba 3 等）几乎全部在**研究用**可微渲染器上做优化，
然后假设结果能迁移到生产引擎；我们直接把**Laya 这个生产引擎**作为评估器，**没有 domain gap**——
但代价是失去梯度。

这种 setting 在学术上叫 **simulator-in-the-loop optimization**，跟机器人学里的 sim2real 问题
有相似性，但应用到图形学 shader fitting 上**没有公开论文**。我们的工具是这个 setting 的
一个**完整的工程实例**。

**论文角度可写成**："Real-Engine-In-the-Loop Black-Box Optimization for Cross-Engine Material Fitting"

### 7.2 Cross-Engine Semantic Parameter Mapping（跨引擎语义参数映射）

**新意**：经典 SVBRDF capture 假定**固定 BRDF 模型**，输入是图像、输出是固定 channel 的纹理。
我们的输入是**Unity shader + Unity 材质实例 + Laya shader**，需要：

1. 解析两端 shader 的可调参数集合 $\mathcal{U}^{\text{unity}}, \mathcal{U}^{\text{laya}}$；
2. 在它们之间建立**语义映射** $\mu: \mathcal{U}^{\text{unity}} \rightharpoonup \mathcal{U}^{\text{laya}}$
   （部分函数，允许多对一、一对多、未匹配）；
3. 用 $\mu$ 把 Unity 材质实例的参数值**翻译**为 Laya 端的初始猜想，作为优化的 warm-start。

这是一个**跨引擎、跨 shader 程序的小规模 NLP/数据库 schema matching 问题**——目前我们用
"manual / curated dictionary / exact normalized / fuzzy" 四级 priority 解决，但更系统的方案
（用 LLM 看 shader 代码做语义对齐、用对比学习训练 shader-embedding）值得探索。

**论文角度可写成**："Semantic Parameter Alignment Across Heterogeneous Shader Programs"

### 7.3 Material-Oriented Multi-Channel Loss（材质语义多通道损失）

**新意**：跟 LPIPS 相比，我们的 $\mathcal{L}_{\text{material}}$ **可解释、可分解、可由艺术家加权**。
具体把图像分为 6 个语义区（暗部 / 中间调 / 高光 / 极亮 / 边缘 / 全图），每区算 4 个统计量
（RGB MAE / luma bias / sat bias / contrast bias），共 24 个分量。这个分解直接对应技术
美术日常用的"调色思路"——`暗部偏亮 → 减 GI 强度`、`高光过亮 → 减 specular intensity`，
而 LPIPS 是个 black-box 标量，不可分解。

**论文角度可写成**："Artist-Interpretable Multi-Channel Image Distance for Material Optimization"

### 7.4 Heuristic-Prior-Informed Black-Box Hybrid

**新意**：把 shader-aware 启发式（stage-aware coordinate descent）作为 CMA-ES 的 **warm-start**
+ **协方差初始化**，相当于把 graphics 领域知识注入纯黑盒优化器。在工业上这是个常识做法，
但**针对 cross-engine material fitting 的具体 prior 选择 + 参数耦合协方差结构**，目前没有
公开报告。

**论文角度可写成**："Shader-Semantic Priors for Sample-Efficient Black-Box Material Optimization"

### 7.5 Cross-Engine Material Migration Benchmark（潜在的基准数据集）

**新意**：截止目前，还没有公开发表的"Unity → Laya / Unity → 移动版 / Unreal → 移动版"材质迁移
基准数据集。如果我们能整理 50-100 个真实工业用例 + ground-truth 美术解，**这本身就是一篇 dataset paper**，
能进 graphics 数据集类期刊。

**论文角度可写成**："CrossEngineMat: A Benchmark for Cross-Engine Material Parameter Transfer"

---

## 8. 评估方法

要让上述创新点真正构成可发表工作，必须有**可重复的评估协议**。

### 8.1 评估指标

- **像素层**：RGB MAE、PSNR
- **感知层**：LPIPS、DISTS、SSIM
- **语义层**：$\mathcal{L}_{\text{material}}$ 各分量
- **领域差校正**：每个数据集 case 估计 $\Delta_{\text{domain}}$（用美术 ground-truth 参数渲出来的
  Laya 图与 Unity 参考图的最小可达距离），上报 **算法收敛距离 / $\Delta_{\text{domain}}$ 的比值**
- **艺术家盲评**：每个 case 找 3 位 TA，让他们在不知道哪个是哪个的情况下，从 N 个候选材质
  里挑"最像"的，报告 ranking score
- **效率**：单 case 收敛时间、CPU/GPU 资源、算法评估次数

### 8.2 实验对照组

| 方法 | 实现状态 |
|---|---|
| Baseline 0：Unity 参数原样照搬 (`identity`) | 已有 |
| Baseline 1：当前启发式 (stage-aware coordinate descent) | 已有 |
| Baseline 2：纯随机搜索 | 待加 |
| Baseline 3：CMA-ES（无 warm-start） | Phase 1 |
| 我们的 Phase 1：CMA-ES + 启发式 warm-start | Phase 1 |
| 我们的 Phase 2：上面 + 多通道感知损失 | Phase 2 |
| 我们的 Phase 3：可微代理 renderer + Adam | Phase 3 |
| 我们的 Phase 4：MO-CMA-ES + Pareto | Phase 4 |

### 8.3 测试用例

短期（评估 Phase 1-3）：fish_1580 + 5-10 个补充用例（不同 Unity shader、不同复杂度）。

长期（评估 Phase 5）：CrossEngineMat 基准（50-100 case）。

### 8.4 可重现性要求

- 全部代码开源在 `tools/material_fit/`；
- 评估脚本一键复现；
- 数据集随论文公开（取得团队脱敏许可后）；
- 关键 hyperparameter 默认值写在 `optimizer/` 各模块的 docstring 里。

---

## 9. 风险与限制

诚实列出：

### 9.1 引擎 API 漂移

Laya 升级 / `.lmat` 格式变化 / shader 编译器更新都会影响工具。要靠 `tests/test_lmat_io.py` 等
回归测试 + 引擎版本钉住。

### 9.2 Shader 通用性

当前所有启发式（stage 划分、channel 映射）都是基于 FishStandard 类型 shader 的经验设计。
换一类 shader（譬如卡通 / 描边 / 头发）需要重新设计 stage。**Phase 3 的可微代理 renderer**
某种程度上能缓解这个——只要新 shader 的数学闭式可写，就能自动派生代理。

### 9.3 跨引擎语义未必能完全对齐

某些 Unity 效果（如反射探针的方向性、多 pass 后处理）在 Laya 里**根本没有等价物**——这些
case 上算法的最优损失就是 $\Delta_{\text{domain}}$，**永远不会接近 0**。需要在 UI 上
区分"算法已收敛"和"领域差不可消除"。

### 9.4 美术 ground-truth 的主观性

不同 TA 给同一个 case 调出来的"最优"参数会不同。基准数据集需要每 case 收集 $\geq 3$ 个 TA 解 +
收集 N=10 个 TA 的偏好评分，统计上才靠谱。

### 9.5 计算资源

Phase 3 的可微代理 renderer 训练 + 校准需要 GPU。Phase 5 的基准建立需要每 case 跑全部
baseline，按 200 评估 × 8 baseline × 100 case × 2 s = 88 小时。需要并行化。

---

## 10. 结论与下一步具体动作

### 10.1 结论

Cross-engine material fitting 是一个**学术上有定义、文献部分覆盖、但完整 setting 没有
公开发表过**的研究问题。它的几个独特之处——**真实生产引擎在环、跨 shader 程序语义对齐、
艺术家可控的多通道损失**——构成了真实的论文贡献空间。

我们的工具 `tools/material_fit` 已经覆盖了这个问题的一个完整工程闭环（Unity 解析 → Laya 写入 →
渲染评估 → 启发式优化 → UI 可视化），是**罕见的"既有完整 baseline 系统又有清晰研究问题"
的研究起点**。

### 10.2 下一步建议（按时间顺序）

| 时间 | 动作 | 产出 |
|---|---|---|
| Week 1-2 | Phase 1：CMA-ES 接入 + 对比 baseline | 工程代码 + 单 case 上的对比图 |
| Week 3 | Phase 2：LPIPS + 艺术家权重 UI | 工程代码 + 截图演示 |
| Week 4-9 | Phase 3：可微代理 FishStandard | 论文实验数据 |
| Week 10-11 | Phase 4：MO-CMA-ES + Pareto UI | 工程代码 |
| Week 12+ | 论文撰写 + Phase 5 基准建设 | TVCG / CGF 投稿 |

### 10.3 论文骨架（备忘）

如果决定要写论文，建议骨架：

- **Title**: "Real-Engine-In-the-Loop Cross-Engine Material Fitting with Shader-Semantic Priors"
- **Sections**:
  1. Introduction（工业动机 + 问题定义）
  2. Related Work（Section 5 内容压缩）
  3. Problem Formulation（Section 4 内容）
  4. Method:
     - 4.1 Shader-Semantic Stage Decomposition
     - 4.2 Multi-Channel Material-Oriented Loss
     - 4.3 Heuristic-Warm-Started CMA-ES
     - 4.4 Differentiable Surrogate Renderer (Phase 3)
  5. Experiments:
     - 5.1 Cross-Engine Material Benchmark (Phase 5 数据)
     - 5.2 Quantitative Comparison
     - 5.3 Ablation Study
     - 5.4 Artist Blind Evaluation
  6. Limitations and Future Work
- **Target**: TVCG / Computer Graphics Forum / SIGGRAPH Asia Technical Briefs

---

## 参考文献

[^aittala2015]: Aittala, M., Weyrich, T., & Lehtinen, J. (2015). "Two-shot SVBRDF capture for stationary materials." *ACM Transactions on Graphics (TOG), 34(4)*, 1-13.

[^deschaintre2018]: Deschaintre, V., Aittala, M., Durand, F., Drettakis, G., & Bousseau, A. (2018). "Single-image SVBRDF capture with a rendering-aware deep network." *ACM Transactions on Graphics (TOG), 37(4)*, 1-15.

[^gao2019]: Gao, D., Li, X., Dong, Y., Peers, P., Xu, K., & Tong, X. (2019). "Deep inverse rendering for high-resolution SVBRDF estimation from an arbitrary number of images." *ACM Transactions on Graphics (TOG), 38(4)*, 1-15.

[^henzler2021]: Henzler, P., Deschaintre, V., Mitra, N. J., & Ritschel, T. (2021). "Generative modelling of BRDF textures from flash images." *ACM Transactions on Graphics (TOG), 40(6)*, 1-13.

[^boss2020]: Boss, M., Jampani, V., Kim, K., Lensch, H. P., & Kautz, J. (2020). "Two-shot spatially-varying BRDF and shape estimation." *Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition (CVPR)*, 3982-3991.

[^hansen2003]: Hansen, N., Müller, S. D., & Koumoutsakos, P. (2003). "Reducing the time complexity of the derandomized evolution strategy with covariance matrix adaptation (CMA-ES)." *Evolutionary Computation, 11(1)*, 1-18.

[^mockus1975]: Mockus, J. (1975). "On Bayesian methods for seeking the extremum." *Optimization Techniques IFIP Technical Conference*, 400-404.

[^snoek2012]: Snoek, J., Larochelle, H., & Adams, R. P. (2012). "Practical Bayesian optimization of machine learning algorithms." *Advances in Neural Information Processing Systems (NeurIPS)*, 25.

[^eriksson2019]: Eriksson, D., Pearce, M., Gardner, J., Turner, R. D., & Poloczek, M. (2019). "Scalable global optimization via local Bayesian optimization." *Advances in Neural Information Processing Systems (NeurIPS)*, 32.

[^storn1997]: Storn, R., & Price, K. (1997). "Differential evolution—a simple and efficient heuristic for global optimization over continuous spaces." *Journal of Global Optimization, 11(4)*, 341-359.

[^wang2016]: Wang, Z., Hutter, F., Zoghi, M., Matheson, D., & De Freitas, N. (2016). "Bayesian optimization in a billion dimensions via random embeddings." *Journal of Artificial Intelligence Research, 55*, 361-387.

[^jakob2022]: Jakob, W., Speierer, S., Roussel, N., Nimier-David, M., Vicini, D., Zeltner, T., Nicolet, B., Crespo, M., Leroy, V., & Zhang, Z. (2022). "Mitsuba 3 renderer." *https://www.mitsuba-renderer.org*.

[^laine2020]: Laine, S., Hellsten, J., Karras, T., Seol, Y., Lehtinen, J., & Aila, T. (2020). "Modular primitives for high-performance differentiable rendering." *ACM Transactions on Graphics (TOG), 39(6)*, 1-14.

[^ravi2020]: Ravi, N., Reizenstein, J., Novotny, D., Gordon, T., Lo, W., Johnson, J., & Gkioxari, G. (2020). "Accelerating 3D deep learning with PyTorch3D." *arXiv preprint arXiv:2007.08501*.

[^liu2019]: Liu, S., Li, T., Chen, W., & Li, H. (2019). "Soft rasterizer: A differentiable renderer for image-based 3D reasoning." *Proceedings of the IEEE/CVF International Conference on Computer Vision (ICCV)*, 7708-7717.

[^tewari2020]: Tewari, A., Fried, O., Thies, J., Sitzmann, V., Lombardi, S., Sunkavalli, K., Martin-Brualla, R., Simon, T., Saragih, J., Nießner, M., & others (2020). "State of the art on neural rendering." *Computer Graphics Forum, 39(2)*, 701-727.

[^wang2004]: Wang, Z., Bovik, A. C., Sheikh, H. R., & Simoncelli, E. P. (2004). "Image quality assessment: from error visibility to structural similarity." *IEEE Transactions on Image Processing, 13(4)*, 600-612.

[^zhang2018]: Zhang, R., Isola, P., Efros, A. A., Shechtman, E., & Wang, O. (2018). "The unreasonable effectiveness of deep features as a perceptual metric." *Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition (CVPR)*, 586-595.

[^ding2020]: Ding, K., Ma, K., Wang, S., & Simoncelli, E. P. (2020). "Image quality assessment: Unifying structure and texture similarity." *IEEE Transactions on Pattern Analysis and Machine Intelligence (TPAMI), 44(5)*, 2567-2581.

[^deb2002]: Deb, K., Pratap, A., Agarwal, S., & Meyarivan, T. (2002). "A fast and elitist multiobjective genetic algorithm: NSGA-II." *IEEE Transactions on Evolutionary Computation, 6(2)*, 182-197.

[^zhang2007]: Zhang, Q., & Li, H. (2007). "MOEA/D: A multiobjective evolutionary algorithm based on decomposition." *IEEE Transactions on Evolutionary Computation, 11(6)*, 712-731.

[^igel2007]: Igel, C., Hansen, N., & Roth, S. (2007). "Covariance matrix adaptation for multi-objective optimization." *Evolutionary Computation, 15(1)*, 1-28.

[^sitthi2011]: Sitthi-Amorn, P., Modly, N., Weimer, W., & Lawrence, J. (2011). "Genetic programming for shader simplification." *ACM Transactions on Graphics (TOG), 30(6)*, 1-12.

---

> **修订记录**
>
> - v0.1（2026-05-06）：初稿，完成所有十节内容 + 22 条参考文献。

