# 跨引擎材质拟合：相关研究综述

> 这是 `CrossEngineMaterialFit_Research.md` 的姊妹文档。前者描述**问题与提议路线**，
> 本文档系统性地回答一个先决问题：**在动手之前，学术界已有的相关工作是什么？哪些可以
> 直接借用？哪些可以站在肩上扩展？我们之前推荐的 DiffMat 是不是真正的最佳基础？**
>
> 本文采用文献综述的标准范式：先说明调研方法（哪些数据库、关键词、时间窗口），按
> 主题分类梳理代表性工作（含开源代码可用性），再用横向对比表把它们放到统一坐标系下，
> 最后给出**经过证据修正的 baseline 推荐**——剧透：我们之前的 DiffMat 推荐**需要修正**，
> 真正最对口的是 NVIDIA 的 `nvdiffmodeling` / `nvdiffrec` 一线。

---

## 0. 摘要

我们针对 7 个相关研究方向、覆盖 2014-2025 年的 60+ 篇代表性论文与 12+ 个开源项目做了
系统调研。结论：

1. 我们的问题最近的学术坐标是 **inverse rendering / appearance-driven scene simplification**，
   而不是 procedural material capture（DiffMat 所在的领域）。
2. 与我们问题最直接对位的论文是 **Hasselgren et al. EGSR 2021，"Appearance-Driven
   Automatic 3D Model Simplification"** [^hasselgren2021] 及其 CVPR 2022 后续 **nvdiffrec**
   [^munkberg2022]——它们明确关注 "image-only supervision enables easy conversion between
   rendering systems" 这件事，而 DiffMat 关注的是从手机闪光灯照片反推 Substance Designer 节点参数。
3. Phase 1 的 warm-start CMA-ES 想法其实**已经被形式化发表过**（Nomura et al. AAAI 2021
   [^nomura2021]），有可直接 import 的开源实现 `cmaes.get_warm_start_mgd()`，
   不需要我们自己重新发明。
4. LLM 用于 shader / 材质的方向 2024-2025 有显著进展（VLMaterial ICLR 2025
   Spotlight [^vlmaterial2025]、Make-it-Real NeurIPS 2024 [^makeitreal2024]），可作为
   PreanalysisView 的语义先验来源。
5. **跨引擎的 shader/材质迁移作为一个完整的研究问题没有公开发表的论文**——这是真实存在
   的学术 gap，我们的工具有机会成为这个 gap 的第一个系统化方案。

基于这些证据，本文档第 5 节给出修订后的 baseline 推荐，第 6 节给出明确的学术定位与
论文叙事结构。

---

## 1. 调研方法

### 1.1 数据库与时间窗口

- **学术数据库**：ACM Digital Library、IEEE Xplore、SpringerLink、arXiv、OpenReview
- **检索引擎**：Google Scholar、Semantic Scholar、CGF/TVCG 期刊页
- **代码仓库**：GitHub、SourceForge
- **时间窗口**：2014 年至今，重点关注 2020-2025 的工作

### 1.2 关键词组合（中英文）

| 主题 | 检索词 |
|---|---|
| 逆渲染与 SVBRDF | `inverse rendering`, `SVBRDF capture`, `material acquisition`, `appearance acquisition` |
| 可微渲染 | `differentiable rendering`, `differentiable rasterization`, `gradient-based rendering`, `path-space differentiable` |
| 程序化材质 | `procedural material`, `Substance Designer optimization`, `material graph` |
| 跨引擎 | `cross-engine shader`, `Unity Unreal conversion`, `shader translation`, `appearance-driven simplification` |
| 黑盒优化 | `black-box optimization`, `CMA-ES warm start`, `surrogate optimization`, `Bayesian optimization graphics` |
| LLM/VLM | `LLM shader generation`, `VLM material`, `language model 3D asset` |
| 多目标 | `multi-objective optimization graphics`, `Pareto material`, `MO-CMA-ES` |

### 1.3 筛选标准

- **强相关**：至少 2 个核心维度（图像反推材质参数 / 优化算法 / 跨域迁移）跟我们问题
  对齐，且代码或数据公开。
- **中相关**：1 个核心维度对齐，方法或基准可借用。
- **弱相关 / 背景**：领域综述、奠基性工作、提供概念词汇。

---

## 2. 我们的问题在学术坐标系里的位置

按照标准的 inverse rendering 分类法 [^tewari2020] [^kato2020] [^surveydr2024]，
我们的问题可以这样描述：

```
                                    ┌─ 已知 ─┐
   I^*  =  R_unity( θ^unity ;  S_unity )           ← 给定的 Unity 参考图
                                    └────────┘
                                                       
           ┌───────────────── 求解 ──────────────────┐
   θ^*   =  arg min_{θ ∈ Θ}  L( R_laya(θ; S_laya), I^* )
           └─────────────────────────────────────────┘
                                          ↑
                                          R_laya 是黑盒、不可导、
                                          架构与 R_unity 显著不同
```

跟相关研究 setting 的差别：

| 维度 | 经典 inverse rendering | SVBRDF capture | DiffMat / 程序化材质 | **本工作** |
|---|---|---|---|---|
| 目标 | $R(\theta, S^*) \approx I^*$ | 给定光照下还原表面属性 | 还原 Substance 节点参数 | $R_{\text{B}}(\theta) \approx R_{\text{A}}(\theta_A)$ |
| 训练域 | 同 renderer 内 | 假定标准 BRDF | Substance 节点空间 | **跨 renderer 跨 shader 程序** |
| renderer 关系 | 同一个，可微 | 同一个，可微 | 同一个，可微 | **A、B 不同，A 黑盒不可控、B 黑盒可写** |
| 输入图像数 | 多视图 / 单视图 | 单图 / 多曝光 | 单张闪光灯照片 | **单张参考渲染图** |
| 几何 | 通常需要重建 | 平面假设居多 | 平面贴图 | **几何已知且固定** |
| 评估代价 | $10^{-2}\sim 10^{-1}$ s/次 | $10^{-3}\sim 10^{-2}$ s/次 | $10^{-2}$ s/次 | $\mathbf{1\sim 3}$ **s/次** |

**关键观察**：我们的问题最接近 inverse rendering，但有两个独有特征：

1. **跨 renderer**：监督信号 $I^*$ 由一个**完全独立的渲染器**生成，不在我们优化器的可控范围内。
   这意味着**最优损失天然存在不可消除的 domain gap** $\Delta_{\text{domain}} > 0$。
2. **生产引擎在环**：我们的 $R_{\text{laya}}$ 是真实生产引擎，**无法直接梯度反传**。绝大多数现代
   inverse rendering 论文假定 renderer 可微，这条假设在我们这里不成立。

这两点的组合在文献里**没有完整对应的 setting**。最接近的工作是 Hasselgren 2021（详见 §3.2），
但它是单一 renderer 内的 simplification，不是跨 renderer 迁移。

---

## 3. 相关研究领域综述

### 3.1 经典与神经 SVBRDF Capture

#### 3.1.1 综述与基础

最系统的综述是 **Guo et al. CGF 2024，"Deep SVBRDF Acquisition and Modelling: A Survey"**
[^guo2024svbrdf]——梳理了 50+ 篇神经 SVBRDF 工作，按"输入数量 / 监督方式 / 是否需要光照
信息"三轴分类。这篇综述是该领域的标准参考。

奠基性工作：
- **Aittala et al. TOG 2015**，"Two-shot SVBRDF capture for stationary materials" [^aittala2015]——
  用两张差分曝光照片反推平面材质 SVBRDF，奠定后续闪光灯 capture 范式。
- **Aittala et al. TOG 2016**，"Reflectance modeling by neural texture synthesis" [^aittala2016]——
  把 BRDF capture 与 texture synthesis 结合，引入 VGG style loss。

#### 3.1.2 单图深度学习（与我们关系：弱-中）

- **Deschaintre et al. TOG 2018**，"Single-Image SVBRDF Capture with a Rendering-Aware Deep
  Network" [^deschaintre2018]——经典工作，闪光灯下平面材质的 SVBRDF 反推。代码在
  https://repo-sam.inria.fr/fungraph/deep-materials/。
- **Gao et al. TOG 2019**，"Deep Inverse Rendering for High-resolution SVBRDF Estimation
  from an Arbitrary Number of Images" [^gao2019]——把 latent space optimization 与
  rendering loss 结合。

#### 3.1.3 2024-2025 最新工作（与我们关系：弱）

- **DualMat (2025)** [^dualmat2025]——双路扩散模型估计 PBR 材质，albedo 提升 28%。
- **MatFusion (SIGGRAPH 2023)** [^matfusion2023]——生成式扩散模型用于 SVBRDF 捕获。
- **MatE (2025)** [^mate2025]——单图 PBR 材质，加入几何先验。
- **DGRSISE (SIGGRAPH Asia 2025)** [^dgrsise2025]——扩散引导的 relighting 用于 SVBRDF。
- **Material Palette (CVPR 2024)** [^materialpalette2024]——单图提取多个材质 palette。

**与我们的关系**：这一族工作的目标是"**给一张包含未知材质的真实照片，反推出标准
BRDF 参数**"。我们的目标是"**给一张已知材质在 renderer A 下的渲染图，反推 renderer B
中 shader 的参数**"。两者**输入相似但 setting 完全不同**：

- 它们假定**单一固定 BRDF 模型**（通常是 Disney BRDF 或 Cook-Torrance），输出 fixed-channel
  的 albedo/normal/roughness/metallic。
- 我们的目标 shader 由用户提供，参数集合 $\mathcal{U}^{\text{laya}}$ 不固定。
- 它们的输入是**真实照片**，光照未知；我们的输入是**Unity 渲染图**，光照"已 baked"
  在图里且可在 Laya 端复制。

可借用的：单图 → 参数预测网络，可作为 PreanalysisView 中的"快速 warm-start"模块（论文
角度叫 **prior network**）。

### 3.2 ★ Appearance-Driven Simplification（与我们关系：**最强**）

这一族工作目标是"用更便宜的 mesh + shader 复现复杂场景的视觉外观"，是**与我们问题最直接
对位的方向**。

#### 3.2.1 nvdiffmodeling / Hasselgren et al. EGSR 2021

[^hasselgren2021] **"Appearance-Driven Automatic 3D Model Simplification"**
（NVIDIA Real-Time Graphics Research）

**关键引文**："Supervision through images only enables easy conversion between rendering
systems and scene representations."（仅靠图像监督就能在不同渲染系统间转换）

这一句话**就是我们的问题描述**。具体：

- **任务**：joint optimization of triangle meshes and shading models 使其匹配复杂参考场景的外观。
- **方法**：可微 rasterizer（早期版本，后来演化为 nvdiffrast）+ 图像空间损失 + Adam。
- **支持的渲染模型**：normal mapping、SVBRDF、displacement mapping，用户可自定义。
- **输出**：纹理化三角网格，**直接可在生产引擎中使用**。
- **代码**：https://github.com/NVlabs/nvdiffmodeling
- **应用**：mesh decimation、LOD 生成、复杂材质简化。

**与我们的差距**：

- 它在**同一个 renderer 内**做简化（高质量版 vs 低质量版都是用 nvdiffrast 渲）。我们要
  跨 Unity → Laya，且 Laya 是不可微的黑盒。
- 它假定 mesh 也可调（联合优化几何 + 材质），我们的 mesh 是固定的。

但**核心思想完全可复用**：用图像监督 + 可微 surrogate renderer 来训练简化版的
shader 参数。

#### 3.2.2 nvdiffrec / Munkberg et al. CVPR 2022

[^munkberg2022] **"Extracting Triangular 3D Models, Materials, and Lighting From Images"**

Hasselgren 2021 的后续与扩展，CVPR 2022 oral。

- **任务**：从多视图图像联合反推 mesh + materials + lighting。
- **方法**：DMTet (Differentiable Marching Tetrahedrons) + nvdiffrast + split-sum environment
  approximation。
- **关键定位**："The extracted models are compatible with traditional graphics engines
  without modification"（直接可在传统图形引擎中使用，不需修改）。
- **代码**：https://github.com/NVlabs/nvdiffrec

**与我们的契合点**：

- 它**显式追求"engine-portable output"**——这正是我们想要的：优化器吐出来的参数能直接喂给 Laya。
- 它的方法栈（nvdiffrast + DMTet + split-sum env）是工业级、性能优化好的可微 pipeline，
  比 DiffMat 的 PyTorch + Taichi 组合在性能上更有优势。

### 3.3 可微渲染框架（与我们关系：**强**——作为 Phase 3 的底层）

#### 3.3.1 综述

- **Kato et al. 2020 / TPAMI 2024**，"Differentiable Rendering: A Survey" [^kato2020]——
  最权威的综述，把 DR 分为 rasterization-based 和 ray-tracing-based 两族。
- **Zhao et al. 2024**，"A Brief Review on Differentiable Rendering" [^zhao2024dr]——
  最新进展（包括 Gaussian Splatting、PSDR-WAS 等）。
- **Physics-Based Differentiable Rendering Survey**（中文电子学报 2024）[^cjig2024dr]——
  侧重于物理基础 DR 的 path-space formulation。

#### 3.3.2 主流可微渲染器

| 框架 | 范式 | 强项 | 弱项 | 与我们契合度 |
|---|---|---|---|---|
| **Mitsuba 3** [^jakob2022] | path tracing | 物理精确、支持 caustics | 重、慢、跟 Laya 的 forward rasterization 范式不同 | 中 |
| **nvdiffrast** [^laine2020] | rasterization | 高性能 GPU、模块化、与 Laya 范式同源 | 自己不带 BRDF / lighting | **强** |
| **PyTorch3D** [^ravi2020] | rasterization | 易上手、文档好 | 性能不如 nvdiffrast | 中 |
| **Soft Rasterizer** [^liu2019] | rasterization | 早期工作 | 已被 nvdiffrast 取代 | 弱 |
| **redner** [^li2018redner] | path tracing | 早期可微 path tracer | 维护停滞 | 弱 |
| **Taichi** [^hu2019taichi] | DSL | 元编程、自动求导 | 学习曲线 | 中 |

**结论**：作为 Phase 3 的底层，**nvdiffrast** 是最对口的选择——同样基于 rasterization、
NVIDIA 持续维护到 2025-12（v0.4.0）、跟 Laya 的 WebGL/forward rendering 范式同构。

#### 3.3.3 物理基础 DR 的最新进展（与我们关系：弱）

- **PSDR-WAS** [^psdr2023]——SIGGRAPH Asia 2023 Best Paper，path-space differentiable
  rendering 的进展，能可微地处理 occlusion / boundary 等几何不连续。
  - **为什么不用**：我们不需要光线追踪精度，且 Laya 是 rasterization-based。
- **Differentiable Inverse Rendering with Interpretable Basis BRDFs** [^basis2024]——
  把 SVBRDF 表示为可学习 basis BRDF 的 spatial blend。
  - **可借鉴**：interpretability 的思路与我们的"多通道材质语义损失"理念一致。

### 3.4 程序化材质捕获（与我们关系：**中**——参考方法学，不是直接 baseline）

#### 3.4.1 DiffMat 系列

- **MATch / Shi et al. SIGGRAPH Asia 2020** [^shi2020match]——把 Substance Designer 节点图
  转为可微 PyTorch 程序，用 style transfer loss 优化节点参数。
- **DiffMat v2 / Li et al. SIGGRAPH 2023** [^li2023diffmat]——proxy-free mixed-integer
  optimization，扩展到带噪声生成器的复杂材质。**支持连续 + 离散参数联合优化**。
- **代码**：https://github.com/mit-gfx/diffmat（v0.2.1，2025-01 更新）。

**为什么之前的推荐需要修正**：DiffMat 的参数空间是 **Substance Designer 节点参数**——它
假定材质由 Substance 节点图描述，把节点逐个翻译为可微算子。我们的目标 shader 是 **GLSL
编写的 FishStandard.shader**，**不是**基于 Substance 节点。要用 DiffMat 我们需要先把
FishStandard 重写为 Substance 节点图——这是一个**跑题的转换**。

DiffMat 的**真正可借用部分**：

1. **Mixed-integer optimization 思想**——我们有 `u_GGXSpecular` 这种 0/1 参数，DiffMat v2
   的 proxy-free 整数优化技术值得照搬。
2. **节点级可微化范式**——可作为我们 Phase 3 把 GLSL FishStandard 翻译为 PyTorch 算子时
   的代码组织参考。

#### 3.4.2 其他程序化材质工作

- **Henzler et al. SIGGRAPH Asia 2021** [^henzler2021]——Generative Modelling of BRDF
  Textures from Flash Images，扩展到 stochastic 纹理。
- **MaterialGAN / Guo et al. 2020** [^materialgan2020]——StyleGAN2 over BRDF maps，先验
  非常强。
- **Yale Inverse Procedural Texture** [^yale2010ipt]——早期工作，CNN 分类 + 参数回归。
- **Semi-Procedural Textures using PPTBF** [^semipptbf]——Point Process Texture Basis
  Functions，半程序化合成。

### 3.5 ★ 黑盒优化与 Warm-Start（与我们关系：**最强**——Phase 1 的核心方法）

#### 3.5.1 经典方法

- **CMA-ES** [^hansen2003]——黑盒优化金标准，连续高维 box-constrained 问题首选。
- **Bayesian Optimization** [^mockus1975] [^snoek2012]——评估极贵 + 维度 < 15 时最佳。
- **TuRBO** [^eriksson2019]——高维 BO 的 trust region 变体，扩展到 $d > 100$。
- **Differential Evolution** [^storn1997]——种群进化算法，鲁棒但评估贵。
- **NSGA-II** [^deb2002]——多目标遗传算法，Pareto 前沿。
- **MO-CMA-ES** [^igel2007]——多目标 CMA-ES。
- **REMBO / Random Embedding BO** [^wang2016rembo]——高维 BO 的随机嵌入降维。

#### 3.5.2 ★ Warm-Starting CMA-ES

[^nomura2021] **Nomura et al., "Warm Starting CMA-ES for Hyperparameter Optimization",
AAAI 2021**

**这正是我们 Phase 1 想要做的事的学术化表述**：

- **问题**：CMA-ES 需要 long adaptation phase 才能采样到 promising region，预算有限时
  会浪费大量评估在初始化阶段。
- **方法**：基于先前类似任务的 GMM (Gaussian mixture models) 通过最小化 KL 散度初始化
  CMA-ES 的多元高斯分布参数（mean、step-size、协方差矩阵）。
- **结果**：在 HPO 任务上**优于 vanilla CMA-ES 与 BO**。
- **代码**：`pip install cmaes`（CyberAgent AILab），有 `get_warm_start_mgd()` 函数直接可用。
  https://github.com/CyberAgentAILab/cmaes

**对我们的指导**：

- 我们的"启发式跑 5 轮 → 用结果当 CMA-ES 初值"这个 idea **不是新发明**，是 Nomura 2021
  的直接应用。
- 我们应当 cite 这篇，并明确我们的"先验"是**shader semantic prior**（启发式产物）而不是
  Nomura 假设的"similar task GMM"。这是一个**领域定制化的扩展**，可作为论文 contribution。

#### 3.5.3 Surrogate-Assisted BBO（与我们关系：中-高）

- **PMBO** [^pmbo2024]——polynomial surrogate + GP error model。
- **Surrogate-assisted EA with clustering** [^surrogateea2024]——RBF surrogate + DE 局部搜索。
- **DOSS** [^doss2024]——sparse directional surrogate search，36-60 维优于 TuRBO。
- **Gradient Matching Surrogates** [^gradmatch2024]——离线 BBO 的理论框架。

**与我们的契合点**：Phase 3 的**可微代理 renderer** 本质上就是一个 surrogate—— surrogate-assisted
BBO 的理论框架可作为我们论文 method section 的 grounding。

### 3.6 跨引擎工具与 Shader 翻译（与我们关系：**强**——证实学术 gap）

这一节的发现非常重要：**学术界几乎没有公开发表的跨引擎材质迁移工作**，工业界的工具也都
停留在"语法层翻译"而非"视觉等价"。

#### 3.6.1 工业工具

- **HLSLcc** [^hlslcc]（Unity Technologies）——DirectX bytecode → GLSL/Metal/Vulkan 的
  跨编译器。**纯语法，不保证视觉等价**。
- **Unifree** [^unifree2023]——用 ChatGPT 把 Unity 项目翻译为 Godot/Unreal。**已停更
  且作者承认不稳定**。
- **HLSL Cross Compiler**（Unreal Engine）——HLSL → GLSL，针对设备无关编译，**不涉及材质参数**。
- **com.jollysamurai.unrealengine4-import**——UE4 → Unity 材质迁移 Unity 包，**不全且
  停更**。

#### 3.6.2 学术工作

- **Sitthi-Amorn et al. TOG 2011**，"Genetic Programming for Shader Simplification"
  [^sitthi2011]——用遗传编程在 shader AST 上做简化。**目标是性能优化，不是跨引擎**。
- **Wang et al. 2014**，"Surface signal approximation for shader simplification"——更早的
  shader 简化工作。

#### 3.6.3 学术 GAP 总结

> **本组数据是本综述的关键发现**：截止 2026-05，**没有任何同行评审论文**专门讨论"用一个
> 引擎的渲染图作监督，自动调整另一个引擎的 shader 参数"这个完整问题。最近的工作 Hasselgren
> 2021 在思想上最接近，但他们的 setting 是同 renderer 内简化，不是跨 renderer 迁移。
>
> 这个 gap 既证实了我们工作的学术新意，也意味着我们可能是**第一个把这件事系统化**的工作。

### 3.7 LLM / VLM 用于 Shader 与材质（与我们关系：中——可作为辅助 prior）

2024-2025 涌现大量 LLM-graphics 交叉工作，部分对我们有借鉴价值。

#### 3.7.1 关键工作

- **VLMaterial / ICLR 2025 Spotlight** [^vlmaterial2025]——用 VLM (vision-language model)
  生成程序化材质（Python 代码形式）。在 Blender 上验证。代码已开源。
- **Make-it-Real / NeurIPS 2024** [^makeitreal2024]——用 GPT-4V 给 3D 物体的不同部位
  分配真实材质，含 80+ 子类的材质库。代码 https://github.com/Aleafy/Make_it_Real。
- **LL3M (2025)** [^ll3m2025]——多 agent LLM 系统在 Blender 中生成 3D asset（含 shader）。
- **Demokritos** [^demokritos]——LLM 驱动的 GLSL shader 社区生成项目。

#### 3.7.2 对我们的启发

- **VLMaterial 的 "VLM 看图 → 生成程序化材质代码"** 范式可以**反向**用：让 VLM 看 Unity
  参考图 + Laya shader 代码 → 输出"建议的 Laya 参数初值"，作为 CMA-ES warm-start 的另一个来源。
- **Make-it-Real 的"VLM 识别材质 + 推荐参数"** 流程几乎可以直接移植到我们的 PreanalysisView。

但**不应让 LLM 接管主优化循环**：LLM 是 stochastic、慢、贵、不可重现的。它适合做 prior 而
非 driver。

### 3.8 公开数据集（与我们关系：中——基准建设阶段需要）

- **MatSynth (2024)** [^matsynth2024]——4069 个 4K PBR 材质 + 3.4M 渲染图，CC0 协议。
  目前最大的公开 PBR 数据集。
- **Adobe Materials**（半公开）——Adobe Substance Source 部分开放。
- **Deep Materials Dataset** [^deschaintre2018]——Deschaintre 2018 配套数据，85 GB。
- **MERL BRDF Database** [^merl2003]——经典 BRDF 测量数据集，100 个材质。
- **TwoShotBRDFShape** [^boss2020]——Boss 2020 配套，shape + SVBRDF。

**对我们的启示**：第 5 阶段的"CrossEngineMat 基准"应当借鉴 MatSynth 的发布范式（4K
分辨率、CC0、含完整渲染脚本与参数文件），但**关键差异**是我们要包含**两端 shader 程序 +
两端渲染图 + 美术 ground-truth**，这是 MatSynth 没有的。

---

## 4. 横向对比表：我们能从哪些工作中拿到什么

| 论文/项目 | 与我们问题契合度 | 可直接 import | 可学习的方法 | 代码状态 |
|---|---|---|---|---|
| Hasselgren 2021 nvdiffmodeling | **极强** | 思想上的 baseline | 图像监督跨 renderer 范式、可微 surrogate 训练 | 活跃 |
| Munkberg 2022 nvdiffrec | **极强** | DMTet 不需要、但 nvdiffrast 可用 | engine-portable output 设计、split-sum env | 活跃 |
| nvdiffrast | **极强** | 直接当底层 | rasterization API | 极活跃（NVIDIA 维护到 2025-12） |
| DiffMat v2 (Li 2023) | 中 | 不直接，需要 shader → Substance 翻译 | mixed-integer optimization、节点可微化 | 活跃 |
| Mitsuba 3 | 中 | 备选 path tracer | 完整 inverse rendering 教程 | 活跃 |
| Nomura 2021 WS-CMA-ES | **极强** | `pip install cmaes` 直接用 | warm-start KL-divergence 初始化 | 活跃 |
| nevergrad | **极强** | 直接 import | 统一 BBO API、含 CMA-ES/DE/PSO/MO | 活跃 |
| Deschaintre 2018 | 弱 | 不适合 | 单图 prior 网络架构 | 公开但旧 |
| Gao 2019 | 弱 | 不适合 | latent space optimization | 半公开 |
| MatFusion 2023 | 弱 | 不适合 | 扩散模型作为 prior | 公开 |
| VLMaterial 2025 | 中 | LLM prior 来源 | VLM → 程序化材质代码 | 公开 |
| Make-it-Real 2024 | 中 | LLM prior 来源 | GPT-4V 识别材质 + 分配参数 | 公开 |
| Sitthi-Amorn 2011 | 弱 | 概念相关 | 遗传编程在 shader AST 上的搜索 | 不公开 |
| HLSLcc / Unifree | 不相关 | 工业工具，不解决我们的问题 | — | 部分活跃 |
| MatSynth 2024 | 中 | 数据集发布范式 | 大规模材质数据组织方式 | 数据集公开 |
| Hansen 2003 CMA-ES | 极强 | `pip install cma` | 黑盒优化基准方法 | 活跃 |
| Eriksson 2019 TuRBO | 强 | 论文方法可借用 | 高维 BO 的 trust region | 公开 |
| Deb 2002 NSGA-II | 强 | 多目标 baseline | Pareto 进化算法 | 多个 Python 实现 |

---

## 5. 重新评估候选 Baseline

### 5.1 之前推荐 DiffMat 的依据回看

我之前在 `CrossEngineMaterialFit_Research.md` 推荐 DiffMat 作为 Phase 3 的核心基础，理由：

> "DiffMat 解决的问题跟我们几乎同构：参数空间→可微图→匹配参考图"。

**经过本次调研，这个推荐需要修正**。具体差距：

| 维度 | DiffMat | nvdiffmodeling/nvdiffrec | 我们 |
|---|---|---|---|
| 参数空间 | Substance 节点参数 | shader 内任意参数 | shader 内任意参数 |
| Forward 模型 | Substance 节点图（需先翻译） | nvdiffrast 上自定义 shader | 自定义 FishStandard shader |
| 跨 renderer | 不考虑 | **明确支持，且明文写在动机** | **核心需求** |
| Engine portability | 不强调 | **核心目标** | **核心目标** |

**一句话总结**：DiffMat 假定材质由 Substance 节点图描述，**预设了输入材质的表达形式**；
nvdiffmodeling/nvdiffrec 假定材质由用户自定义的 forward shader 描述，**对表达形式不做预设**——
后者跟我们的需求**完全契合**。

### 5.2 修订后的 Baseline 推荐

#### 5.2.1 Phase 1（黑盒优化替换启发式）

**采用**：
- **`pip install cmaes`** [Nomura 2021 / CyberAgent AILab]——内置 `get_warm_start_mgd()`，
  把启发式输出转成 GMM 然后 KL-初始化 CMA-ES。这是我们 Phase 1 的**直接学术对应**。
- **`pip install nevergrad`** [Meta]——作为统一 BBO API，方便后续 swap 到 DE/PSO/TuRBO 对比。

**学术 cite**：[^nomura2021] [^hansen2003]。

#### 5.2.2 Phase 3（可微代理 renderer）★ **核心修正**

**采用**：
- **底层**：**nvdiffrast** [^laine2020]——可微 rasterizer，性能 + 维护都顶级。
- **范式参考**：**Hasselgren 2021 nvdiffmodeling** [^hasselgren2021]——直接作为思想 baseline，
  代码 https://github.com/NVlabs/nvdiffmodeling 可作为代码组织参考。
- **engine-portability 设计**：**Munkberg 2022 nvdiffrec** [^munkberg2022]——
  borrow split-sum env approximation 等让产物可在传统引擎使用的关键技术。

**学术 cite**：[^hasselgren2021] [^munkberg2022] [^laine2020]。

**改用 DiffMat 的位置**：仅作为 mixed-integer optimization 技术参考（Li 2023 [^li2023diffmat]
的 proxy-free MIO），cite 一下，不作为 method backbone。

#### 5.2.3 Phase 2（多通道感知损失）

**采用**：
- **LPIPS** [^zhang2018lpips]——感知距离。
- **DISTS** [^ding2020dists]——结构 + 纹理感知距离（备选）。
- 我们自己的多通道材质损失保留。

#### 5.2.4 Phase 4（多目标）

**采用**：
- **MO-CMA-ES** [^igel2007]——nevergrad 已封装。
- **NSGA-II** [^deb2002]——同。

#### 5.2.5 Phase 5（基准数据集）

**参考发布范式**：MatSynth [^matsynth2024]。
**关键差异**：包含两端 shader + 两端渲染图 + 美术 ground-truth。

#### 5.2.6 LLM Prior（PreanalysisView 的后续增强）

**参考**：
- **VLMaterial** [^vlmaterial2025]——VLM 看图生成材质代码。
- **Make-it-Real** [^makeitreal2024]——GPT-4V 识别 + 分配材质参数。

---

## 6. 学术 GAP 分析与我们工作的定位

### 6.1 系统性 GAP

经过本次调研，我们识别出 4 个**学术界尚未解答**的具体问题：

#### GAP 1：跨 renderer 的 inverse rendering

> 现有 inverse rendering 都假定监督信号与待优化 renderer 在同一个渲染管线下。
> **没有公开论文**研究"参考图来自完全独立、不可控、不可微的 renderer A，目标是
> 调 renderer B 的参数"这个 setting。

**我们的 contribution 候选**：把这件事形式化为 **cross-renderer inverse problem**，
明确定义 domain gap $\Delta_{\text{domain}}$，并给出实证测量方法。

#### GAP 2：黑盒生产引擎在环优化的方法学

> 现有 inverse rendering 都依赖可微 renderer。**没有论文**专门讨论"用真实生产引擎
> 作为 ground-truth oracle、可微代理作为优化媒介、定期回环验证"这个 hybrid 流水线
> 的设计原则、收敛保证与 domain gap 控制策略。

**我们的 contribution 候选**：提出 **"Hybrid Real-Surrogate Optimization (HRSO)"**
框架，给出代理偏差的在线估计与代理重校准机制。

#### GAP 3：跨 shader 程序的语义参数对齐

> 现有 SVBRDF capture 假定固定 BRDF 模型。**没有论文**讨论"两端 shader 程序的 uniform
> 集合不同、命名传统不同、数学定义不同"时如何系统建立参数语义映射。

**我们的 contribution 候选**：提出 **shader semantic mapping** 框架（manual / curated /
exact / fuzzy / LLM 五级 priority），并给出 mapping 准确率对最终拟合误差的影响曲线。

#### GAP 4：跨引擎材质迁移基准

> **没有公开数据集**专门用于评估"跨引擎材质迁移"算法。MatSynth 是单引擎多视图渲染；
> Deep Materials 是闪光灯照片；TwoShotBRDFShape 是 shape + SVBRDF。**都不是跨引擎**。

**我们的 contribution 候选**：建立 **CrossEngineMat-50** 或更大规模的基准数据集，含
Unity-Laya 配对、shader 配对、渲染图配对、美术 ground-truth 参数。

### 6.2 我们工作的精确学术定位

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   Closest existing method                  Our work                         │
│                                                                             │
│   Hasselgren 2021                          Cross-renderer extension         │
│   nvdiffmodeling                  ───►     - real production engine in loop │
│   (same-renderer simplification)           - shader semantic mapping        │
│                                            - black-box ground-truth oracle  │
│                                                                             │
│   Nomura 2021                              Domain-specialized prior         │
│   WS-CMA-ES                       ───►     - shader-stage prior injection   │
│   (HPO meta-learning)                      - covariance from semantic group │
│                                                                             │
│   DiffMat v2                               Different problem                │
│   (Substance procedural capture)  ───►     - we keep their mixed-integer    │
│                                              technique only as a lemma     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 修订后的论文叙事框架

```
Title:    "Cross-Renderer Material Fitting via Hybrid Real-Surrogate
           Optimization with Shader-Semantic Priors"

Pitch:    We extend appearance-driven differentiable simplification
          [Hasselgren 2021, Munkberg 2022] to the cross-renderer setting,
          where the supervising image comes from an independent black-box
          renderer and the target renderer is also black-box. We propose:
          (1) a hybrid real-surrogate optimization scheme that uses a real
              production engine as ground-truth oracle while optimizing on
              a differentiable surrogate, with online domain-gap calibration,
          (2) a shader-semantic prior framework that injects domain knowledge
              into both the surrogate's parameter coupling structure and a
              warm-start CMA-ES [Nomura 2021] initialization,
          (3) a cross-engine material migration benchmark CrossEngineMat-50
              with artist ground-truth solutions for quantitative evaluation.

Method sections (从 outermost 到 innermost)：
   1. Cross-renderer problem formulation (the gap analysis above)
   2. Differentiable surrogate of FishStandard (built on nvdiffrast,
      following Hasselgren 2021 's appearance-driven paradigm)
   3. Real-engine validation loop (our novel HRSO framework)
   4. Shader-semantic prior injection
      4.1 Stage decomposition as parameter coupling structure
      4.2 Multi-channel material-oriented loss (interpretable channels)
      4.3 Warm-start CMA-ES with shader-aware GMM (extending Nomura 2021)
      4.4 LLM prior via VLMaterial-style code understanding (optional)
   5. Mixed-integer parameter handling (borrow from Li 2023 DiffMat v2)

Experiments：
   - CrossEngineMat-50 benchmark establishment
   - Quantitative comparison against:
        Baseline 0: Identity mapping (Unity params → Laya verbatim)
        Baseline 1: Heuristic-only (current tool, ablation reference)
        Baseline 2: Vanilla CMA-ES
        Baseline 3: Vanilla nvdiffmodeling-style on FishStandard surrogate
        Baseline 4: DiffMat v2 (after manual translation to Substance graph)
        Ours:       Full HRSO + shader-semantic prior + LLM warm-start
   - Ablation study on each prior component
   - Artist blind evaluation (N=10 TAs, 3-way ranking)
   - Domain gap quantification (Δ_domain across the 50 cases)

Target venue: 
   首选 Computer Graphics Forum (CGF) — 适合工程系统 + 基准数据集类工作
   备选 IEEE TVCG — 偏视觉计算系统类
   备选 SIGGRAPH Asia Technical Briefs — 短篇但顶级会议
```

---

## 7. 修订后的具体下一步

### 7.1 新一周可行性研究计划（从原 1 周延长到 1.5 周）

| 天 | 动作 | 产出 |
|---|---|---|
| Day 1 | clone & 跑通 nvdiffmodeling demo | 确认 nvdiffrast + Hasselgren 风格 pipeline 在我们环境能跑 |
| Day 2 | clone & 跑通 cmaes 库的 `get_warm_start_mgd` 示例 | 确认 WS-CMA-ES 可用 |
| Day 3 | 用 `cmaes` 库替换 `propose_next_params`，在 `fish_1580` 上跑 200 评估 | 跟当前启发式对比，得 fit_score 收敛曲线对比图 |
| Day 4-5 | 用 nvdiffmodeling 框架尝试翻译 FishStandard 的最简版（仅 base color + 简单 lighting） | 验证 FishStandard → nvdiffrast 翻译可行 + 校准误差量级 |
| Day 6 | 评估 DiffMat v2 在我们 setting 下 mixed-integer 优化的可移植性 | 一份 1-page ADR：DiffMat 是否值得翻译 FishStandard 进 Substance 节点图 |
| Day 7 | 跨阶段决策：基于 Day 1-6 实测数据决定 Phase 3 用 nvdiffmodeling 路线还是 DiffMat 路线 | 一份 2-page 决策文档 + 修订后的 5-Phase roadmap |

### 7.2 文档维护计划

- 本文档 (`RelatedWork_Survey.md`) 在每完成一个新 phase 时增量更新最新文献。
- `CrossEngineMaterialFit_Research.md` 的 §6（提议路线）依据本调研结果修订，把 baseline
  从 DiffMat 改为 nvdiffmodeling/nvdiffrec 一线，cite 链整理到位。
- 加一份 `BaselineComparison.md`，把 §4 的横向对比表抽出来作为单独的工程参考。

### 7.3 立刻该做的最小事

如果你只允许做一件事，**就是 §7.1 Day 3 的实验**：用现成的 `cmaes` 库（含 warm-start）
替换我们的启发式调度，在 `fish_1580` 真实 case 上跑一遍。这个实验：

- 工作量 < 0.5 天；
- 不依赖任何 Phase 3 的可微 renderer；
- **直接验证我们的核心假设**："启发式 warm-start 能压缩 5-10× CMA-ES 评估代价"。

如果这个实验显示 WS-CMA-ES 在 200 评估内就能把 fit_score 推进 30%+，那论文方向稳。
如果实验显示 WS-CMA-ES 跟启发式差不多甚至更差，**我们就不用浪费时间投入 Phase 3 了**——
说明问题更深层（可能是 FishStandard 这个具体 shader 的 loss landscape 太病态），需要换
研究角度。

---

## 8. 参考文献

[^hasselgren2021]: Hasselgren, J., Munkberg, J., Lehtinen, J., Aittala, M., & Laine, S. (2021). "Appearance-Driven Automatic 3D Model Simplification." *Eurographics Symposium on Rendering (EGSR)*. https://github.com/NVlabs/nvdiffmodeling

[^munkberg2022]: Munkberg, J., Hasselgren, J., Shen, T., Gao, J., Chen, W., Evans, A., Müller, T., & Fidler, S. (2022). "Extracting Triangular 3D Models, Materials, and Lighting From Images." *CVPR (Oral)*. https://github.com/NVlabs/nvdiffrec

[^laine2020]: Laine, S., Hellsten, J., Karras, T., Seol, Y., Lehtinen, J., & Aila, T. (2020). "Modular Primitives for High-Performance Differentiable Rendering." *ACM Transactions on Graphics (SIGGRAPH Asia), 39(6)*. https://github.com/NVlabs/nvdiffrast

[^jakob2022]: Jakob, W., Speierer, S., Roussel, N., Nimier-David, M., Vicini, D., Zeltner, T., Nicolet, B., Crespo, M., Leroy, V., & Zhang, Z. (2022). "Mitsuba 3 Renderer." https://www.mitsuba-renderer.org

[^ravi2020]: Ravi, N., Reizenstein, J., Novotny, D., Gordon, T., Lo, W., Johnson, J., & Gkioxari, G. (2020). "Accelerating 3D Deep Learning with PyTorch3D." *arXiv:2007.08501*.

[^liu2019]: Liu, S., Li, T., Chen, W., & Li, H. (2019). "Soft Rasterizer: A Differentiable Renderer for Image-Based 3D Reasoning." *ICCV*.

[^li2018redner]: Li, T.-M., Aittala, M., Durand, F., & Lehtinen, J. (2018). "Differentiable Monte Carlo Ray Tracing through Edge Sampling." *SIGGRAPH Asia*.

[^hu2019taichi]: Hu, Y., Li, T.-M., Anderson, L., Ragan-Kelley, J., & Durand, F. (2019). "Taichi: a language for high-performance computation on spatially sparse data structures." *SIGGRAPH Asia*.

[^kato2020]: Kato, H., Beker, D., Morariu, M., Ando, T., Matsuoka, T., Kehl, W., & Gaidon, A. (2020). "Differentiable Rendering: A Survey." *arXiv:2006.12057*.

[^zhao2024dr]: Zhao, S. et al. (2024). "A Brief Review on Differentiable Rendering: Recent Advances and Challenges." *MDPI Electronics, 13(17)*.

[^cjig2024dr]: 中文综述 (2024). "物理基础可微渲染综述." *中国图象图形学报*. doi:10.11834/jig.230715.

[^surveydr2024]: (2024). "Differentiable Rendering Survey." *arXiv:2504.01402*.

[^psdr2023]: Xu, P., Bangaru, S., Li, T.-M., & Zhao, S. (2023). "Warped-Area Reparameterization of Differential Path Integrals (PSDR-WAS)." *SIGGRAPH Asia 2023 Best Paper*.

[^basis2024]: (2024). "Differentiable Inverse Rendering with Interpretable Basis BRDFs." *arXiv:2411.17994*.

[^aittala2015]: Aittala, M., Weyrich, T., & Lehtinen, J. (2015). "Two-shot SVBRDF capture for stationary materials." *ACM TOG, 34(4)*.

[^aittala2016]: Aittala, M., Aila, T., & Lehtinen, J. (2016). "Reflectance modeling by neural texture synthesis." *ACM TOG, 35(4)*.

[^deschaintre2018]: Deschaintre, V., Aittala, M., Durand, F., Drettakis, G., & Bousseau, A. (2018). "Single-Image SVBRDF Capture with a Rendering-Aware Deep Network." *ACM TOG, 37(4)*. https://repo-sam.inria.fr/fungraph/deep-materials/

[^gao2019]: Gao, D., Li, X., Dong, Y., Peers, P., Xu, K., & Tong, X. (2019). "Deep Inverse Rendering for High-resolution SVBRDF Estimation from an Arbitrary Number of Images." *ACM TOG, 38(4)*.

[^henzler2021]: Henzler, P., Deschaintre, V., Mitra, N. J., & Ritschel, T. (2021). "Generative Modelling of BRDF Textures from Flash Images." *ACM TOG (SIGGRAPH Asia), 40(6)*.

[^materialgan2020]: Guo, Y., Smith, C., Hasan, M., Sunkavalli, K., & Zhao, S. (2020). "MaterialGAN: Reflectance Capture using a Generative SVBRDF Model." *ACM TOG, 39(6)*. https://github.com/tflsguoyu/materialgan

[^boss2020]: Boss, M., Jampani, V., Kim, K., Lensch, H. P. A., & Kautz, J. (2020). "Two-Shot Spatially-Varying BRDF and Shape Estimation." *CVPR*.

[^guo2024svbrdf]: Guo, J., et al. (2024). "Deep SVBRDF Acquisition and Modelling: A Survey." *Computer Graphics Forum, 43(7)*.

[^dualmat2025]: (2025). "DualMat: PBR Material Estimation via Coherent Dual-Path Diffusion." *arXiv:2508.05060*.

[^matfusion2023]: Sartor, S., & Peers, P. (2023). "MatFusion: A Generative Diffusion Model for SVBRDF Capture." *ACM TOG (SIGGRAPH Asia)*.

[^mate2025]: (2025). "MatE: Material Extraction from Single-Image via Geometric Prior." *arXiv:2512.18312*.

[^dgrsise2025]: (2025). "DGRSISE: Diffusion-Guided Relighting for Single-Image SVBRDF Estimation." *SIGGRAPH Asia 2025*.

[^materialpalette2024]: Lopes, I., et al. (2024). "Material Palette: Extraction of Materials from a Single Image." *CVPR*.

[^shi2020match]: Shi, L., Li, B., Hašan, M., Sunkavalli, K., Boubekeur, T., Mech, R., & Matusik, W. (2020). "MATch: Differentiable Material Graphs for Procedural Material Capture." *ACM TOG (SIGGRAPH Asia), 39(6)*. https://github.com/mit-gfx/diffmat

[^li2023diffmat]: Li, B., Shi, L., & Matusik, W. (2023). "End-to-End Procedural Material Capture with Proxy-Free Mixed-Integer Optimization." *ACM TOG (SIGGRAPH), 42(4)*.

[^yale2010ipt]: Theobalt, C., et al. (2010). "A Novel Framework For Inverse Procedural Texture Modeling." Yale Computer Graphics Group.

[^semipptbf]: ASTex-ICube (2021). "Semi-Procedural Textures Using Point Process Texture Basis Functions." https://github.com/ASTex-ICube/semiproctex

[^hansen2003]: Hansen, N., Müller, S. D., & Koumoutsakos, P. (2003). "Reducing the Time Complexity of the Derandomized Evolution Strategy with Covariance Matrix Adaptation (CMA-ES)." *Evolutionary Computation, 11(1)*.

[^mockus1975]: Mockus, J. (1975). "On Bayesian Methods for Seeking the Extremum." *Optimization Techniques IFIP Technical Conference*.

[^snoek2012]: Snoek, J., Larochelle, H., & Adams, R. P. (2012). "Practical Bayesian Optimization of Machine Learning Algorithms." *NeurIPS*.

[^eriksson2019]: Eriksson, D., Pearce, M., Gardner, J., Turner, R. D., & Poloczek, M. (2019). "Scalable Global Optimization via Local Bayesian Optimization (TuRBO)." *NeurIPS*.

[^storn1997]: Storn, R., & Price, K. (1997). "Differential Evolution—A Simple and Efficient Heuristic for Global Optimization over Continuous Spaces." *Journal of Global Optimization, 11(4)*.

[^deb2002]: Deb, K., Pratap, A., Agarwal, S., & Meyarivan, T. (2002). "A Fast and Elitist Multiobjective Genetic Algorithm: NSGA-II." *IEEE Trans. Evolutionary Computation, 6(2)*.

[^igel2007]: Igel, C., Hansen, N., & Roth, S. (2007). "Covariance Matrix Adaptation for Multi-Objective Optimization (MO-CMA-ES)." *Evolutionary Computation, 15(1)*.

[^wang2016rembo]: Wang, Z., Hutter, F., Zoghi, M., Matheson, D., & De Freitas, N. (2016). "Bayesian Optimization in a Billion Dimensions via Random Embeddings (REMBO)." *JAIR, 55*.

[^nomura2021]: Nomura, M., Watanabe, S., Akimoto, Y., Ozaki, Y., & Onishi, M. (2021). "Warm Starting CMA-ES for Hyperparameter Optimization." *AAAI*. https://github.com/CyberAgentAILab/cmaes

[^pmbo2024]: (2024). "PMBO: Enhancing Black-Box Optimization through Multivariate Polynomial Surrogates." *arXiv:2403.07485*.

[^surrogateea2024]: (2024). "A Surrogate-Assisted Evolutionary Algorithm with Clustering-Based Sampling for High-Dimensional Expensive Blackbox Optimization." *Journal of Global Optimization, 89*.

[^doss2024]: (2024). "Solving Higher Dimensional Expensive Black Box Global Optimization Problems Using Sparse Directional Search on Surrogates (DOSS)." *Mathematical Programming Computation*.

[^gradmatch2024]: Hoang, M.-H., et al. (2024). "Learning Surrogates for Offline Black-Box Optimization via Gradient Matching." *ICML*.

[^vlmaterial2025]: (2025). "VLMaterial: Procedural Material Generation with Large Vision-Language Models." *ICLR (Spotlight)*.

[^makeitreal2024]: Fang, Y., et al. (2024). "Make-it-Real: Unleashing Large Multimodal Model for Painting 3D Objects with Realistic Materials." *NeurIPS*. https://github.com/Aleafy/Make_it_Real

[^ll3m2025]: (2025). "LL3M: Large Language 3D Modelers." *arXiv:2508.08228*.

[^demokritos]: Demokritos: Interactive, Community-Centred, Self-Improving Shader Generation using LLMs. ISEA 2025. https://demokritos.xyz/

[^matsynth2024]: Vecchio, G., et al. (2024). "MatSynth: A Modern PBR Materials Dataset." *arXiv:2401.06056*.

[^merl2003]: Matusik, W., Pfister, H., Brand, M., & McMillan, L. (2003). "A Data-Driven Reflectance Model." *ACM TOG (SIGGRAPH)*.

[^sitthi2011]: Sitthi-Amorn, P., Modly, N., Weimer, W., & Lawrence, J. (2011). "Genetic Programming for Shader Simplification." *ACM TOG, 30(6)*.

[^hlslcc]: Unity Technologies. "HLSLcc: DirectX Shader Bytecode Cross Compiler." https://github.com/Unity-Technologies/HLSLcc

[^unifree2023]: ProjectUnifree (2023). "Unifree: Migrating Unity Projects to Other Engines." https://github.com/ProjectUnifree/unifree

[^zhang2018lpips]: Zhang, R., Isola, P., Efros, A. A., Shechtman, E., & Wang, O. (2018). "The Unreasonable Effectiveness of Deep Features as a Perceptual Metric (LPIPS)." *CVPR*.

[^ding2020dists]: Ding, K., Ma, K., Wang, S., & Simoncelli, E. P. (2020). "Image Quality Assessment: Unifying Structure and Texture Similarity (DISTS)." *IEEE TPAMI*.

[^tewari2020]: Tewari, A., et al. (2020). "State of the Art on Neural Rendering." *Computer Graphics Forum, 39(2)*.

---

> **修订记录**
>
> - v0.1（2026-05-06）：初稿，覆盖 7 个研究方向、60+ 篇文献、完整决策矩阵。
>   关键发现：DiffMat 不是最佳基础，应改为 nvdiffmodeling/nvdiffrec 一线；
>   WS-CMA-ES 已经发表过，可直接 import；跨引擎材质迁移作为完整研究问题学术 gap 真实存在。

