# 实验进展日志（Experiment Log）

> **这是干嘛的？** 每次有新的算法实验、关键 bug 修复、或者影响"app 能不能跑"的改动，都在这里记一笔。
> **怎么读？** 直接看 §0 头部表，1 秒判断"我现在能在 app 里用什么"。下面每条按时间倒序，最新的在最上面。

---

## §0  当前 app 实际能用的能力（每次更新这里！）

> ⚠️ 这是给 "我现在打开 app 点 Start 会发生什么？" 这一问题的权威答案。

### 现在 `fit_material.py` 实际跑的优化器

| 项目 | 状态 | 备注 |
|---|---|---|
| **优化算法 — 启发式（默认）** | ✅ 启发式 stage 调度 (`propose_next_params`) | 跑 6 个 stage 顺序，每 stage 按 channel-bias 反向修正参数；带 `STUCK_NO_IMPROVE_LIMIT` / `GLOBAL_NO_IMPROVE_LIMIT` 防止卡死 |
| **优化算法 — `cma_cold`** | ✅ 已接 (E-006) | UI `AlgoConfigView` 选 cma_cold；vanilla CMA-ES 从初始 .lmat 起步无 prior |
| **优化算法 — `cma_warm`** | ✅ 已接 (E-006) | UI 选 cma_warm；自动扫描 `auto_adjust/iter_*/` 取已有 (params, fit_score) 对作 prior。&lt;2 轮历史时降级到 cold |
| **CMA-ES 不再被启发式 4-step abort 卡死 (E-010)** | ✅ shipped | `OptimizerStrategy.wants_global_no_improve_check()` 接口；CMA-ES 返回 False；老的启发式逻辑保持 True 完全不变 |
| **CMA-ES 默认迭代预算 (E-010)** | ✅ shipped | `job_manager` 按 optimizer 选默认：heuristic=6，cma_*=30。用户在 UI `max_iterations` 显式填的值仍然完全生效 |
| **专家 hint 偏置注入 CMA-ES (E-010)** | ✅ shipped | `analysis.adjustment_hints` 的 channel 级"应增/应减 + severity"通过 `bias_callback` 加在 `CMA.ask()` 出来的样本上；UI `AlgoConfigView` "hint_bias_mix_ratio" 滑块（默认 0.30，0 = 纯 CMA-ES，&gt; 0.5 偏置主导）|
| **`.lmat` 写入** | ✅ 严格模式 `lmat_io.write_candidate_lmat` | 写完会自动重读校验，发现结构损坏自动删除文件 + 抛异常 |
| **评价指标 — 自动背景 mask + 通道加权 MAE + SSIM (E-009)** | ✅ shipped | `analysis.perceptual_fit_score` 默认接管 `fit_score`，`fit_score_mode=perceptual` 是 fallback；`decision.json.perceptual_signals` 每轮记录 weighted_mae / ssim / fg_ratio |
| **背景色统一预处理 (E-011)** | ✅ shipped | 当 Unity / Laya 各自渲染到不同纯色背景时，自动检测各自 bg 并替换为统一 `target_bg`（默认中性灰 `(128,128,128)`）。`auto_mask` 不动，仅影响 SSIM 看到的"非 mask 区"颜色；synthetic 实验关闭 16.9% 背景失配 fit_score 缺口，`weighted_mae` 完全不动 |
| **截图卫生 (E-012)** | ✅ shipped | 探针 3 张图直写 `preflight/{baseline,probe,restored}.png` 固定槽位，不再每跑一次往 `test_image/` 多塞 3 张垃圾；auto-adjust 的 `laya_candidate_NN.png` 池默认只保留最新 30 张（`screen_capture.max_keep`，CLI `--screen-capture-max-keep`）；UI 探针图加 `?t=<时间戳>` cache-buster 防浏览器拿陈帧 |
| **大模型（LLM）辅助参数映射 / 调参** | ❌ 没接 | `LlmAssistView.vue` 是占位 UI |
| **可微分渲染 baseline (nvdiffmodeling)** | ❌ 没接 | 调研完成，没动手 |

### 一句话回答常见疑问

- **Q：CMA-ES 的实验结果能在 app 里看到吗？** 能。在项目页"算法配置"里把 optimizer 切成 cma_warm 或 cma_cold，下次 Start 就走 CMA-ES。每轮 `decision.json` 里的 `decision.optimizer == "cma_es"` 字段标记走的是哪条路径。
- **Q：cma_warm 第一次跑没历史怎么办？** 自动 fallback 到 cma_cold。已经有过启发式跑过几轮的项目，cma_warm 才有 prior。要从启发式切到 cma_warm 的标准流程：先用 heuristic 跑 3-5 轮拿一些样本，再切 cma_warm 接力。
- **Q：现在 UI 上的"算法配置 / fit_score_mode / target_score"对哪个算法生效？** 全都生效。target_score / max_iterations 是 stop 条件，不挑算法；fit_score_mode 影响 CMA-ES 的 loss 缩放（loss = 1 - fit_score）。
- **Q：如果我现在跑一遍 fish_1580，会跟之前 12 轮那次有什么不同？** 不会卡在 base_color 了（stage 推进 bug 已修），`.lmat` 也不会被写坏（`lmat_io` 已加严格校验）。如果切 cma_warm 还能享受 WS-CMA-ES 的合成 benchmark 里证实的 ~2-3× 加速（注意：合成验证，不是真 Laya 验证）。
- **Q：为什么 heuristic 一次只动 1-2 个参数？** 这是 heuristic 的设计——每个 stage 只动 stage 关心的参数子集（比如 base_color stage 只动 u_BaseColor）。stage 内通过 `STUCK_NO_IMPROVE_LIMIT`（默认 2）触发跳到下一个 stage。所以"6 轮调 6 个参数"是预期行为而非 bug。**想要单次提议联动调多个参数，切 cma_warm / cma_cold**——CMA-ES 每个 ask 出来的就是全部 ~25 维一起扰动的样本。
- **Q：Laya 在我们改 .lmat 之后真的会立刻重渲染吗？** 这个是必须验证的假设，否则后面 fit_score 全是假的。**E-007 加了 magenta 探针**：UI 项目页"验证 Laya 是否真的在刷新"按钮 → 写一个洋红色到 `u_BaseColor` → 等 `rerender_wait_ms` → 截屏 → 还原 → 截屏。三张图肉眼可见地变红再变回，且洋红像素占比统计一致才算通过。CLI 里同等功能：`--laya-refresh-check`。这一步不通过就不要相信任何 fit_score。
- **Q：fit_score 高就真的代表"看起来像 Unity"吗？** **E-009 之前不行，现在差不多了**。E-009 之前的 fit_score 用全图 RGB MAE 打分，而 Laya 截图 70% 是编辑器纯色背景，所以 fit_score 大约 50-60% 是"两张图背景颜色之间的距离"——纯噪音。E-009 引入 `auto_background_mask` 自动识别两张图的背景色 + `channel_weighted_mae`（按视觉重要性加权 6 个材质 channel）+ SSIM（容忍 1 像素位移）。新指标在 `decision.json.perceptual_signals` 里能完整看到 weighted_mae / ssim / fg_ratio 三个独立信号。详见 [`Metric_Validation.md`](Metric_Validation.md)。**重要**：E-009 之前跑过的 `best_fit_score` 数字不能跨版本直接比，需要用 `tests/manual/rescore_e009.py` 重新打分才有意义。

---

## §1  按状态分类的进展矩阵

> 给每条改动一个生命周期标签，让"算法验证完了 ≠ app 已经能用"这件事一眼可见。

生命周期：

- 🟢 **shipped** — 已经接到 `fit_material.py`/UI，`pip pull` 后点 Start 立刻能用
- 🟡 **scaffolded** — 代码 + 测试 + 合成实验都做了，**还没接进主流程**
- 🔵 **researched** — 只有调研文档/设计，没写代码
- ⚫ **deprecated** — 试过了，不用了

| # | 改动/实验 | 状态 | 文件 | 报告 |
|---|---|---|---|---|
| E-001 | `lmat_io` 严格校验（防写坏） | 🟢 shipped | `optimizer/parameter_search.py`, `laya/lmat_io.py`, `tests/test_lmat_io.py` | 见 §3 E-001 |
| E-002 | Stage 推进 bug 修复（不再卡 base_color） | 🟢 shipped | `optimizer/adjustment_algorithm.py`, `tests/test_stage_progression.py`, `tests/test_real_run_simulation.py` | 见 §3 E-002 |
| E-003 | UI 屏幕框选 + 项目化新建流程 | 🟢 shipped | `tools/material_fit_ui/**` | 见 §3 E-003 |
| E-004 | Fit score perceptual 模式 | 🟢 shipped | `fit_material.py`, UI `AlgoConfigView` | 见 §3 E-004 |
| E-005 | 跨引擎材质迁移问题学术化 + Related Work 调研 | 🔵 researched | `docs/CrossEngineMaterialFit_Research.md`, `docs/RelatedWork_Survey.md` | 见 §3 E-005 |
| E-006 | WS-CMA-ES 合成 benchmark 验证 + 接进 fit_material/UI | 🟢 shipped | `optimizer/cma_es_optimizer.py`, `optimizer/strategy.py`, `fit_material.py`, `tools/material_fit_ui/**` | [`Experiment_Phase1_CMA_ES_WarmStart.md`](Experiment_Phase1_CMA_ES_WarmStart.md) + 见 §3 E-006 更新 |
| E-007 | Laya refresh 探针 preflight | 🟢 shipped | `laya/refresh_probe.py`, `fit_material.py --laya-refresh-check`, `tools/material_fit_ui/backend/preflight.py`, `tools/material_fit_ui/frontend/src/components/RefreshPreflightCard.vue` | 见 §3 E-007 |
| E-008 | Laya 窗口自动聚焦（解 E-007 后续发现：Laya 失焦时不渲染） | 🟢 shipped | `laya/window_focus.py`, `laya/refresh_probe.py focus 参数`, `fit_material.py --laya-window-process/title`, `project_store laya_window`, `ProjectConfigView Laya 窗口聚焦面板`, `RefreshPreflightCard focus_log 表格` | 见 §3 E-007 后续段落 |
| E-009 | 评价指标科学化（auto-mask + channel-weighted MAE + SSIM）| 🟢 shipped | `vision/perceptual_score.py`, `vision/diff_analysis.py`, `fit_material.py _resolve_fit_score`, `IterationDetail.vue` E-009 pill 行 | [`Metric_Validation.md`](Metric_Validation.md) + 见 §3 E-009 |
| E-010 | CMA-ES 释放 (skip global abort + 默认 30 轮) + 专家 hint 注入偏置 | 🟢 shipped | `optimizer/strategy.py` (`wants_global_no_improve_check`, `_compute_hint_vector`), `optimizer/cma_es_optimizer.py ask(bias_callback)`, `fit_material.py --cma-hint-bias-mix-ratio`, `job_manager.py` 按 optimizer 选默认 iterations, UI `AlgoConfigView` hint_bias 控件 | 见 §3 E-010 |
| E-011 | 跨引擎背景色统一预处理（Unity grey vs Laya sky） | 🟢 shipped | `vision/background_normalize.py`, `vision/diff_analysis.py` (auto_mask 在前 / E-011 在后顺序), `tests/test_background_normalize.py` 18 个单测, `tests/manual/verify_e011.py` synthetic 验证 | 见 §3 E-011 |
| E-012 | 截图卫生：探针固定槽位、auto-adjust 池滚动上限、UI cache-buster | 🟢 shipped | `vision/screen_capture.py` (`prune_old_captures`, `output_path`, `max_keep`), `material_fit_ui/backend/preflight.py`, `fit_material.py --screen-capture-max-keep`, `material_fit_ui/backend/{project_store,job_manager}.py`, `RefreshPreflightCard.vue` cache-buster, `tests/test_screen_capture.py` 12 个单测 | 见 §3 E-012 |
| E-013 | 工具独立化 + 一键启动器 + 文档去 laya/buyu 耦合 | 🟢 shipped | `tools/material_fit_ui/launch.py` + `launch.bat` 一键启动；`tools/material_fit/AGENT_ONBOARDING.md` 新接手 agent 第一读物；`README.md` 重写；老文档（`MaterialAutoFitTool.md` / `IntegrationDifficulties.md` / `LLMContextPrompt.md`）加历史横幅；`fit_config.example.json` 加 `_README_PLEASE_READ` 路径解析说明；`material_fit_ui/README.md` 移除 `d:\project_data\laya\buyu` 死路径；全工具确认无任何对 `laya/buyu` 父项目代码或路径的耦合 | 见 §3 E-013 |

---

## §2  待办（按优先级）

> 未做的关键事项。完成一个就把它移到 §3。

### P0 — 影响 app 能不能用的硬阻塞

1. ~~**把 CMA-ES 接进 `fit_material.py`**~~ ✅ 已完成（2026-05-06，见 §3 E-006 后续段落）
   - `optimizer/strategy.py` 抽出 OptimizerStrategy 接口；`fit_material.py` 加 `--optimizer` CLI；`project_store` / `job_manager` 透传；UI `AlgoConfigView` 加下拉。
   - 22 个新增测试，全套 60/60 通过。

2. ~~**Laya refresh 假设的 magenta 探针**~~ ✅ 已完成（2026-05-06，见 §3 E-007）
   - 用户测试反馈："不知道 Laya 是不是修改之后立马重新渲染"。如果不是，所有 fit_score 都是假的。
   - 加了 `laya/refresh_probe.py`：写洋红色 → 等 → 截屏 → 还原 → 截屏。三张图洋红占比对比能精确判定 Laya 是否在刷新。
   - CLI flag `--laya-refresh-check`；UI "验证 Laya 是否真的在刷新" 按钮 + 三联图展示。
   - 12 个新增测试，全套 72/72 通过。

3. ~~**Laya 窗口自动聚焦（E-007 后续发现）**~~ ✅ 已完成（2026-05-06，见 §3 E-007 后续段落 / E-008）
   - 用户实测探针不通过，定位到根因：**Laya 在窗口失焦时暂停渲染**。
   - 加了 `laya/window_focus.py`，pipeline 在每张截屏前 + 每次 .lmat 写入前自动 `SetForegroundWindow` 拉前 Laya。
   - 17 个新增测试，全套 89/89 通过。

4. **真闭环验证 `fish_1580` 单 case，对照 6 条件 × 50 evals**（见 [`Experiment_Phase1_CMA_ES_WarmStart.md`](Experiment_Phase1_CMA_ES_WarmStart.md) §6 Step 3）
   - **强制前置**：先在 UI 跑一次 E-007 的"验证 Laya 是否真的在刷新"按钮，看到三张图分别是 baseline / 洋红 / 还原。如果不通过，先调"Laya 窗口聚焦"区域的 `title_pattern`（多 Laya 项目时锁定要调的那个）或 `rerender_wait_ms`，再跑这个对照实验，否则结果无意义。
   - 6 组对照：heuristic / cma_cold / cma_warm-12 / cma_warm-24 / **cma_warm-bias=0.30 (E-010)** / **cma_warm-bias=0.50 (E-010)**
   - 这是真正能写进论文/报告的"是否值得 ship CMA-ES + hint bias"的判据。
   - 工作量：~1 天人时 + ~6 小时机器时间。
   - **E-009 后必须重跑**：之前的所有 fit_score 都是用老指标（70% 是背景噪音）打的，对算法选型的判断不可信。E-009 已 ship，新跑的所有 run 自动用新指标，老的历史 run 需要 `python tools/material_fit/tests/manual/rescore_e009.py` 重打分才能跨期比较。建议把 P0-4 直接当 "E-009 + E-010 第一次真验证"。
   - **target_score 重新校准**：之前 0.9 是按老指标尺度估的，新指标下几乎不可达。建议初次跑 target_score=0.30-0.40 看实际能到多少。
   - **背景统一前置**：E-009 verify 实验已证明 Unity / Laya 背景颜色不一致会自动咬掉 ~0.29 fit_score 动态范围；建议跑 P0-4 前手动把两个引擎的背景调成同一种纯色（推荐中性灰 #808080），让 fit_score 重新覆盖 0-1 整个区间。
   - **E-010 ablation**：除了 `cma_warm-bias=0.30 / 0.50` 外，可以扫一下 `mix_ratio ∈ {0, 0.15, 0.30, 0.50}`，看 hint 注入对 50-eval budget 内最终 fit_score 的边际收益。同样数据可以直接进论文 Section 5 的 "expert prior injection ablation" 表。

### P1 — 论文级别但不阻塞 app

3. **基准套件扩到 3 种材质**（toon / PBR / rim-light），让 §6 的结论可推广。
4. ~~**Phase 2：感知损失（LPIPS）替换 RGB MAE**~~ 部分完成于 E-009（已加 SSIM + auto-mask + channel-weighted）。**剩余工作**：替换 SSIM 为 LPIPS / DISTS（深度学习感知度量），加 ECC 对齐（OpenCV 一行）解决 > 5 像素位移情况，为 region 划分用 alpha + normal 替换径向假设。详见 [`Metric_Validation.md`](Metric_Validation.md) §6。
5. **可微分渲染 baseline (nvdiffmodeling)** 翻译 FishStandard 的最简版（base color + 简单 lighting），验证 PyTorch 重写可行性。
6. **E-009 指标的人类评分校准**——收集 ~30 张 ref/cand pair 找 5 个评分人做 MOS，验证 `new_fit` 跟"看着像"的 Pearson 相关。可以直接进论文 Section 4。

### P2 — 探索性

6. LLM 辅助参数语义映射（用 GPT-4 替换 `preanalysis._build_param_mapping` 里的字典+模糊匹配）。
7. 多目标 NSGA-II 优化（同时优化 base_color / specular / fresnel 三个 channel score）。

---

## §3  改动详细记录（按时间倒序）

### E-013 (2026-05-07) — 工具独立化 + 一键启动器 + 文档去 laya/buyu 耦合

> **一键启动器** 也在本节落地，理由：用户在同一周提了"自动调参没反应（要点命令行）"和"独立化"两个连续诉求，启动器是独立化的必要补充——独立工具不能依赖技术用户记得 `python -m uvicorn ...`。`tools/material_fit_ui/launch.py` + `launch.bat` 见 [`material_fit_ui/README.md`](../material_fit_ui/README.md) "一键启动" 小节。


**目标**：用户准备把整个工具从当前 laya 项目（`tools/material_fit*`）剥离出去，放到一个独立仓库继续开发。需要保证：

1. 工具所有功能与当前 laya 项目的功能/路径**完全无耦合**——可在任何位置独立运行；
2. 即使工具搬到新位置，仍能处理用户 laya 项目里的 `.lmat` 文件；
3. 文档完整最新——新仓库里给一个新 agent 读，不会被早期文档（描述"打算做什么"）误导成"工具能力还停留在早期"。

**调查结果**：

代码层无硬耦合：

- 全工具内部 import 一律走 `tools.material_fit.*` / `tools.material_fit_ui.*`，**只要保留 `tools/` 这个父目录**，工具就可整体搬到任何位置。
- 没有任何源码引用 `D:/project_data/laya/buyu` 之类的硬编码路径（只有 `material_fit_ui/README.md` 第 89 行旧的"项目根目录"提示用了死路径，已替换为"`tools/` 的父目录"）。
- 用户 `.lmat` 路径走 UI 文件管理器选择，以**绝对路径**写入 `project.json` → `derive_fit_config` 写绝对路径到 fit_config.json → `fit_material._resolve_path` 读绝对路径直接用。**工具新位置 ≠ 用户 Laya 项目位置**，绝对路径桥接不需要任何相对位置假设。
- `vision/screen_capture.process_pattern = "LayaAirIDE"` 是 LayaAir IDE 的 Windows 进程名，用户级可移植；用户可在 UI 里覆盖。
- 所有 `parents[N]` sys.path 计算都假设"`tools/` 的父目录是 repo root"，这条约束跟工具走，跟 laya/buyu 父项目无关。

文档层有大量历史毛刺需要修：

- `tools/material_fit/README.md` 还是早期"框架 + dry-run"的描述，对当前实际 ship 的 12 个 E-001..E-012 能力一字未提，**会让新 agent 严重低估工具现状**。
- `MaterialAutoFitTool.md` / `IntegrationDifficulties.md` / `LLMContextPrompt.md` 是 2025 年的设计稿，描述"打算做什么"。它们仍有背景价值，但顶部需要明确告诉读者"已被 ExperimentLog 覆盖"。
- `material_fit_ui/README.md` 顶部"Stage A 只读 inspector / 不在本阶段做"等段落已经被现实远超（UI 已经能写 .lmat、调 screen_capture、控制 Laya 窗口聚焦、跑探针），新 agent 读到会被错误锚定。
- `fit_config.example.json` 里的相对路径（`assets/resources/...`）仅适用于一个特定用户的 Laya 项目，外人会以为是默认数据。

**实施**：

1.  **新增 `tools/material_fit/AGENT_ONBOARDING.md`** —— 新接手 agent 的第一读物，5 分钟解释：工具是什么 / 两层结构 / 当前能力（指向 ExperimentLog §0）/ 文档信用等级 / 怎么跑 / 怎么独立部署 / 反直觉踩坑点。这个文件是后续防止新 agent"被早期文档误导"的核心防火墙。

2.  **重写 `tools/material_fit/README.md`** —— 内容反映当前实现：12 个 E-001..E-012 能力的状态表、当前目录结构、CLI / UI 跑法、用户输入 / 工具产物清单、测试。**显式声明老的"fit_score = 1 - RGB MAE"已被 E-009 替换**，避免新 agent 看到老 README 后给出错误结论。

3.  **重写 `tools/material_fit_ui/README.md`** 顶部段落 + "不在本阶段做"清单 —— 把"Stage A 只读"改为"已远超 Stage A，能力以 ExperimentLog §0 为准"；"不写 .lmat / 不调 screen_capture / 不嵌 Laya 控制"清单加 ⚠️ 横幅指出已经被现实覆盖；剩余真未做的两件（LLM mapper、iframe 嵌 Laya）单独列出。把第 89 行 `d:\project_data\laya\buyu` 死路径改为 "`tools/` 的父目录"。

4.  **三份历史文档加横幅**：
    -   `IntegrationDifficulties.md`（顶部）—— "历史文档（2025），实施已完成大部分内容，以 ExperimentLog §0 为准"；
    -   `LLMContextPrompt.md`（顶部）—— "历史文档（2025），LLM 辅助还没接入主流程"；
    -   `docs/MaterialAutoFitTool.md`（顶部）—— "历史文档（2025），最初设计稿，落地状态以 ExperimentLog §0 为准"。

5.  **`fit_config.example.json` 加 `_README_PLEASE_READ` 顶层 key** —— 显式说明：相对路径解析规则（`config_path.resolve().parents[2]`）、UI 派生 config 走绝对路径、example 里的 `assets/resources/...` 是某个用户 Laya 项目的特例不是默认。同时把 `optimizer` 默认值从 `heuristic` 改成 `cma_warm` 反映 E-006 / E-010 之后的推荐设置，加 `fit_score_mode: perceptual`、`hint_bias_mix_ratio: 0.30`、`screen_capture.max_keep: 30`、`laya_window`、`laya_capture_anchor` 字段反映 E-008 / E-010 / E-011 / E-012 已 ship 的能力。

6.  **ExperimentLog §0 / §1 加一行 E-013** + **§3 加本段记录**。

**脱离独立后，搬运清单**：

- ✅ 整个 `tools/material_fit/` —— 算法 / 文档 / 测试 / CLI 入口
- ✅ 整个 `tools/material_fit_ui/` —— 后端 / 前端 / 启动器（`frontend/node_modules/` 可不复制，启动器跑 `npm install` 自动装回）
- 选项 `tools/material_fit/output/<project_id>/` —— 用户已有项目数据，搬到新机器需用户在 UI 里重新选 `.lmat` / Unity 参考图（绝对路径会失效，工具会清楚报错）

**用户只需做一件事**：复制 `tools/` 整个目录到新仓库根，**保留 `tools/` 这层父目录**。

**测试**：测试套保持 152/152 通过；启动器干跑（`launch.py --skip-checks`）行为不变。无新增 unit test（本次改动只动文档与一份示例配置）。


**问题**：用户发现三个相互独立但都让人不爽的工程毛病。

1.  **UI 探针下面三张图不是最新的**——点完探针，UI 仍显示上一次的 baseline / probe / restored。原因：探针写到 `output/<project>/preflight/{baseline,probe,restored}.png` 的 3 个固定文件名，URL 永远一样，浏览器按 URL key 缓存图片，所以点几次都是第一次拉到的那一张。
2.  **每次跑探针 / 每次跑实验都新增一张截图**，长期累积。诊断 `vision/test_image/` 看到 `laya_candidate_1.png`、`laya_candidate_02.png`、`laya_candidate_19.png`、`laya_candidate_135.png` 等 22+ 张混着不同 padding 的历史截图躺尸——本质原因：`screen_capture.next_candidate_path()` 单调递增、永不回收，且**探针与 auto-adjust 共用同一个池**，每跑一次探针 +3 张垃圾。
3.  **实验截图无上限**，跑 10 次 50-iter 的实验就是 500 张 PNG 没人清理。

**方案**：

#### A. `screen_capture.py` 加两个新参数

-   `output_path: str | Path | None = None` — 显式给出写入路径，**完全跳过** `next_candidate_path()` 滚动池。探针 / preflight 这种"我就要这一个固定槽位"的场景用它。`output_path` 模式下也**不**触发剪枝（固定文件名本身就是它自己的保留策略）。
-   `max_keep: int | None = None` — 仅在滚动池模式（`output_path is None`）生效，写完新图后调用 `prune_old_captures(directory, prefix, max_keep)` 把最旧的 N 张以外都 `unlink`。`None` / `<=0` 是 no-op，老行为不变。
-   返回值新增 `fixed_output_path: bool`、`max_keep: int | None`、`pruned: list[str]`，方便上层做诊断 / 写日志。

#### B. 探针两条调用路径都改成固定槽位

-   `material_fit_ui/backend/preflight.py` 的 `_capture` 直接 `output_path = preflight_dir / f"{step}.png"`，不再调 `shutil.copyfile`，不再污染 `test_image/`。
-   `fit_material._run_laya_refresh_preflight` 的 `_capture` 同样改成 `output_path = preflight_capture_dir / f"{step}.png"`。

#### C. auto-adjust 真捕获接 `max_keep`

-   `fit_material.py` `_run_auto_adjustment` 加新形参 `screen_capture_max_keep: int | None = None`，按 CLI > config > 默认 30 的优先级解析。
-   CLI 加 `--screen-capture-max-keep`（type=int，0 = 关闭剪枝）。
-   `material_fit_ui/backend/project_store.py` 的 `derive_fit_config` 给 `screen_capture` 增加 `max_keep` 字段，从 `inputs.laya_capture_max_keep` 读，默认 30。
-   `job_manager.py` 在 build CLI args 时把 `max_keep` 透传成 `--screen-capture-max-keep`。

#### D. UI cache-buster

`RefreshPreflightCard.vue` 维护一个 `cacheBust = ref(Date.now())`，每次 `run()` / `load()` 成功后刷新。新加 `bustedSrc(path)` 助手在 URL 后面塞 `?t=<cacheBust>`，强制浏览器重新请求图片，URL 不变也不会被缓存了。

#### 测试

新加 `tools/material_fit/tests/test_screen_capture.py` 12 个单测，覆盖：

-   `prune_old_captures` 正常裁、`max_keep=None|0` no-op、目录不存在、不匹配 prefix 的文件不被误删、低于上限不动；
-   `capture_laya_region(output_path=...)` 写到固定槽位并**不**生成滚动池文件；
-   `capture_laya_region(output_path=...)` 即使带 `max_keep` 也**不**裁同名滚动池；
-   `capture_laya_region(max_keep=...)` 滚动池写完之后裁到最近 N；
-   `dry_run=True` 不写不裁。

全套 152/152 测试通过。

#### 用户可见的副作用

-   下次跑一次探针：UI 上三张图必然刷新（cache-buster），且 `test_image/` 里**不会再多 3 张** `laya_candidate_NN.png` 垃圾。
-   下次跑 auto-adjust：`test_image/` 里 `laya_candidate_NN.png` 总数会被剪到 30 张以内（旧的就地 `unlink`）。如果想保留所有截图（比如做长跨度对照），把 `inputs.laya_capture_max_keep` 改成 0 或大于实际实验轮数即可。
-   ⚠️ 已被剪掉的截图，对应 iteration 的 `decision.json.screen_capture_after_apply.output_path` 字段会指向不存在的文件。UI 的 `IterationDetail` 在那种情况下会渲染断图 (`alt`) 兜底，不会崩溃，但回看 30 轮以前的截图就没了。**这是用户明确接受的取舍**。

---

### E-011 (2026-05-07) — 跨引擎背景色统一预处理

**背景**：用户在 E-010 之后实际去 Unity / Laya 都把背景调成了纯色（避免 E-009 verify 实验里发现的 0.29 fit_score 漏损），但**两边并没有调成同一种纯色**：

- Unity 渲染背景：`(71, 71, 71)`  纯中性深灰（4 角全一致）
- Laya  渲染背景：`(134, 151, 180)` 纯蓝灰（天空色，4 角全一致）

用户原话："我现在将背景都改成了纯色了，但是目前没有改成像你说的那样的颜色，这个设置我还没有找到，不过我感觉可以先就按照这样的纯色进行处理，你只要加一点预处理就好了，如果后面再更换了背景色，这个预处理你稍微修改一下即可"。所以本节做的是：在 metric 这一层补一个预处理，**让 metric 看到的两张图共享同一种 bg 颜色**，把"用户没法在引擎里改 bg" 这个约束在指标侧消化掉。

**抽象出来的科学问题**：alpha-compositing 在 silhouette 处会把 engine-specific 的背景色"渗"进前景边缘像素（``edge = α·material + (1−α)·engine_bg``）。E-009 引入的 auto_mask 已经能把 *纯背景* 像素从 weighted_MAE 和 SSIM 中扣出去，但：

1. 边缘抗锯齿带（典型 1-2 px）的像素既不是纯 bg、又有显著 engine_bg 污染，被 mask 当成前景送进 metric → 系统性 ≈0.05-0.10 fit_score 损失（synthetic 测得 0.088）
2. SSIM 是 7×7 窗口算的，mask 边界附近的窗口同时包含前景和背景，**当两张图的背景颜色不同时，SSIM 在 mask 边附近会持续打折**

**做了什么**：

- **新增 `tools/material_fit/vision/background_normalize.py`**（300 行 + 详细 docstring）：
  - `BackgroundNormalizeConfig` —— `enabled / target_bg / soft_low / soft_high / corner_size`，所有字段都有 docstring 解释为什么默认值是这样
  - `detect_corner_background(image, corner_size=12)` —— 4 角中位数 bg 检测器，与 `auto_background_mask` 的检测器**算法一致**（语义同源）
  - `normalize_background(image, config, *, source_bg_override=None)` —— 主预处理函数。逐像素计算 L2 距离、构造 soft α_fg ∈ [0, 1]，按 alpha-compositing 反演公式 `new = pixel + (1 − α_fg) · (target_bg − bg)` 重组
  - `normalize_pair(reference, candidate, config)` —— 对一对图独立处理（关键：each engine 的 bg 被各自检测、各自替换成同一 `target_bg`）
  - `NormalizeResult.as_dict()` JSON-friendly 摘要，方便写进 `decision.json` 取证

- **`vision/diff_analysis.py` 接入（含关键的顺序设计）**：
  - `ImageDiffConfig` 新增 5 个 `bg_normalize_*` 字段，默认 `enabled=True / target=(128,128,128) / soft_low=2 / soft_high=4`
  - **关键**：`auto_background_mask` 在前 → 拿到原始 engine bg → `normalize_background` 用 `source_bg_override=auto_mask.reference_bg_color` 各自替换，**不再独立检测一遍 bg**。这是单一真相源。
  - 同等重要：mask 是在**未替换**的原图上算的，所以替换不影响 mask 边界 → weighted_MAE 完全等价于不做 E-011 的情况
  - 唯一实质改变：SSIM 的 7×7 窗口在 mask 边附近看到的"非 mask 邻接像素" 是统一 target 灰，不再是 engine-specific 的 bg → SSIM 涨
  - 输出新增 `analysis.bg_normalize` 子块（带 `enabled / reference / candidate` 三段，每段含 `detected_bg / target_bg / soft_low / soft_high / coverage / n_pixels_*`）

- **synthetic 验证（`tests/manual/verify_e011.py`）**——4 个对照实验，覆盖识别 E-011 是不是真的有用 / 副作用大不大 / 还能不能区分前景变化：

  | 条件 | fit_score | weighted_MAE | SSIM |
  |---|---|---|---|
  | Q1 相同前景 / 不同 bg / E-011 OFF（status quo）| 0.9120 | 0.0018 | 0.9030 |
  | **Q2 相同前景 / 不同 bg / E-011 ON**            | **0.9268** | **0.0018** | **0.9525** |
  | Q3 相同前景 / 相同 bg（不可达上界）             | 1.0000 | 0.0000 | 1.0000 |
  | Q4 +30% emission 前景 / 不同 bg / E-011 ON      | 0.8784 | 0.0058 | 0.9503 |

  **结论**：
  1. **E-011 关闭 16.9% 的 bg-mismatch fit_score 缺口**（Q2 − Q1 = +0.0148 vs Q3 − Q1 = +0.088）。剩下的 83% 是 silhouette 抗锯齿真实贡献，post-hoc 处理无法恢复（需要 alpha matting / ECC 对齐 / 或者用户改成完全相同 bg 颜色）
  2. **`weighted_MAE` 完全没动**（0.0018 → 0.0018）—— 因为 mask 是在替换前算的，FG 区域的像素值也没动。**纯收益没副作用**
  3. SSIM 涨 0.05（0.903 → 0.953），全部来自 mask 边界附近的窗口看到一致的 target_bg
  4. Q4 vs Q2 = -0.0485 → metric 仍能区分"+30% emission 的 fg 改变"

  **错误尝试也记一下**（避免后人重蹈）：第一版把 E-011 放在 auto_mask **前面** + 用 `[8, 32]` 大 soft 区，结果 Q2 fit 比 Q1 低 0.006。原因：(a) 大 soft 区让 Unity-edge 像素离 bg 近 → 被 nudged 一下，Laya-edge 离 bg 远 → 不动，**两张图的边缘被非对称修改**；(b) auto_mask 在 E-011 之后跑 → bg 颜色变成 (128,128,128) → mask 边界整体 reframe → 边缘像素的 fg/bg 分类翻转。两个 bug 修了之后才有现在的 +17% 净增益。

- **单测（`tests/test_background_normalize.py`）**——18 个新增测试覆盖：
  - 4 角中位数检测器（纯色 / 4 角带噪声 / 小图自适应 / 非图像输入 raises）
  - 主函数（纯 bg 替换 / 前景不动 / `enabled=False` 字节级一致 / `source_bg_override` 跳过检测器 / soft 区域对称线性混合 / RGBA 输入保 alpha / 灰度输入 raises / `soft_high ≤ soft_low` 退化为 hard step）
  - `normalize_pair` 双图独立处理
  - `NormalizeResult.coverage` 总和为 1
  - `NormalizeResult.as_dict()` JSON 可序列化
  - `analyze_image_diff` 集成（payload 出现 / disabled 时跳过 / 显式 mask 时跳过）

- **回归**：`pytest tools/material_fit/tests` 140/140 通过（122 baseline + 18 E-011 新增）

**怎么调（"如果后面再更换了背景色"）**：

- 改 Unity 或 Laya 的渲染背景颜色 → 不需要改任何代码或配置，corner detector 会自动适配
- 改 `target_bg` 默认（比如想统一到深色背景）→ 编辑 `vision/diff_analysis.ImageDiffConfig.bg_normalize_target` 默认值，或者在调用方显式传 `bg_normalize_target=(R, G, B)`
- 想完全关掉 E-011 跑 ablation → `ImageDiffConfig(bg_normalize_enabled=False)` 或 UI 端将这个 boolean 接进 algorithm_config（当前没接，需要时再说）
- **不要把 `soft_high` 调到 > 8** —— synthetic 实验明确证明会引入非对称边缘修正，反而拉低 fit_score

**论文角度**：

E-011 是 E-009 metric 落地工程的延伸 patch，不是独立科学贡献。但**可以作为 Section 4.4 的子节"背景色不变性"**，配合 E-009 verify 实验和 E-011 verify 实验展示一组完整的 ablation：

- naive 全图 MAE （E-009 之前）
- + auto_mask（E-009）
- + bg substitution（E-011） ← 这一节
- + 完美同 bg （ground truth 上界）

定量回答："metric 对 engine-specific 渲染细节的不变性能做到多少"。

**剩余局限**：

- silhouette 抗锯齿带的 ~83% 缺口仍未关闭。要进一步减损需要 (a) 真正的 alpha matting（per-pixel α 估计 → 重组）或 (b) 用户在两个引擎里都用相同 bg 颜色重新渲染。前者是 P2 工作，后者用户已经表态暂时不做
- 当一张图的背景**不是纯色**（比如 Unity 用了 sky gradient 或环境贴图），corner detector 会返回一个仍然有用的 mode 颜色，但 `bg_normalize_target` 替换会把所有相似颜色的像素都拉到 target —— 这时建议关掉 E-011（`bg_normalize_enabled=False`）
- 当一张图的 4 个角不是 bg（比如 Laya UI 的 dock 或工具栏挤入截图），corner detector 会取到 UI 颜色而非 render bg —— `vision/screen_capture.py` 的 anchored region 已经规避了这个问题，但用户如果手工传图就要注意

**文件清单**：

| 文件 | 改动量 | 性质 |
|---|---|---|
| `tools/material_fit/vision/background_normalize.py` | +300 行 | 新模块 |
| `tools/material_fit/vision/diff_analysis.py` | +60 行 | `ImageDiffConfig` 新字段 + `analyze_image_diff` 顺序重排 |
| `tools/material_fit/tests/test_background_normalize.py` | +320 行 | 18 个新测试 |
| `tools/material_fit/tests/manual/verify_e011.py` | +220 行 | synthetic 4-条件对照实验 |
| `tools/material_fit/tests/manual/diagnose_real_bg.py` | +60 行 | 用户实图诊断脚本（输出每张 laya_candidate*.png 的 fit_score / mae / ssim / fg_ratio）|

---

### E-010 (2026-05-06) — 解放 CMA-ES（关 4-step abort + 默认 30 轮）+ 专家 hint 偏置注入

**背景**：用户在 E-008 / E-009 收尾后用刚装好的窗口聚焦 + 新指标跑了几轮 `fish_1580`，反馈"目前的算法目前还不能在很短的时间内抵达和unity原图很像的效果"。检查实际 run logs 后发现两条独立的 silent failure：

1. **CMA-ES 跑 5 轮就被启发式的 `should_abort_global` 砍了**。`adjustment_algorithm.should_abort_global` 在 `state.global_no_improve >= GLOBAL_NO_IMPROVE_LIMIT (=4)` 时强制 break，原本是给 heuristic 防卡死的——可 CMA-ES 是**随机采样器**，前几代采到比 best-so-far 差的样本是预期行为而非"卡住"。在 49 维空间里，4 步连续不刷新 best 几乎一定会发生在 CMA-ES 的第一代（population_size = 4 + 3·ln(49) ≈ 16）走完之前。所以**之前每次切 cma_warm/cma_cold，5 轮就强制收摊，根本没机会让协方差矩阵学到任何东西**。
2. **专家级先验信息（`adjustment_hints`）完全没喂给 CMA-ES**。`vision/diff_analysis.py` 在每轮分析时已经会输出 channel-level "应增/应减 + severity (high/medium/low)"——这是高质量的 inverse-rendering 经验梯度，启发式的 channel-bias 修正模式就是吃这个的。**但走 CMA-ES 路径时这个信号被整个扔掉了**，CMA-ES 只看 fit_score 标量，等于丢了 ~80% 已有的领域知识。

**抽象出来的改动**：

#### A. CMA-ES 退出路径的 ownership 转给 strategy

`OptimizerStrategy` 新增方法 `wants_global_no_improve_check() -> bool`：
- `HeuristicStrategy` 继承 base 默认 `True` —— 完全保留 E-002 启发式的卡死保护，老 case 行为不变。
- `CmaesStrategy` override 为 `False` —— 让 `cmaes.CMA.should_stop()`（基于 sigma 收敛 / condition number / fit 平稳）做决定，配合 `iterations` 预算双重 stop 条件。

`fit_material._run_auto_adjustment` 把硬编码的 `if should_abort_global(state):` 改成 `if strategy.wants_global_no_improve_check() and should_abort_global(state):`。**这一个改动单独就能让 CMA-ES 跑满预算**。

#### B. UI 默认迭代预算按算法分流

`tools/material_fit_ui/backend/job_manager.py` 不再用固定 `algo.get("max_iterations", 6)`：
- 用户显式填了 `max_iterations`，永远用用户的值（向后兼容）。
- 没填时按 optimizer 选默认：`heuristic=6`（一 stage 一轮的设计预期），`cma_cold/cma_warm=30`（CMA-ES 文献和我们 E-006 的合成 benchmark 都指出 49 维空间 100+ 评估才稳定收敛；30 是 1-2 代 + 一些迭代的折衷起点）。

#### C. `adjustment_hints` 注入 CMA-ES 样本（核心算法贡献）

**接口设计**：`CmaesOptimizer.ask(bias_callback=None)` 新加一个可选 hook，签名 `Callable[[np.ndarray], np.ndarray]`。callback 收到的是**原始坐标空间**的样本向量（不是归一化后的），返回 biased 向量。`ask` 拿到 biased 之后**重新归一化**塞进 `_pending`，所以下次 `tell(fitness)` 喂给 CMA-ES 的 `(point, fitness)` 是真实评估了什么就喂什么——CMA-ES 协方差是从真实样本/真实损失对学的，不是从"想象的"。这是数学上正确的把先验注入 CMA-ES 的方式：等价于在目标函数上加一个"靠近 hint 方向"的软偏好，而不是去 hack mean / sigma 内部状态。

**hint vector 计算** (`CmaesStrategy._compute_hint_vector`)：

1. 对每条 hint，提取：`severity_weight ∈ {high:1.0, medium:0.5, low:0.25}` 和 `direction_sign ∈ {increase:+1, decrease:-1}`。无 severity / 无 direction / 非 increase/decrease 的 hint 忽略。
2. 对每个 CMA-ES 编码轴 `axis_i`：扫所有 hint 的 `related_params`，匹配到当前轴的 `param_name` 就累加 `severity * sign`。匹配支持 `*` 通配（`u_MetallicRemap*` 自动展开到 `u_MetallicRemapMin/Max` 两轴）。
3. 最终该轴上的 delta：

```
delta_i = sum_signed_weight × 0.05 × (axis.high - axis.low) × mix_ratio
```

`0.05` 是 heuristic 的标准 step（`AdjustmentStagePolicy.iteration_gain` 默认值），保证 bias 永远比 CMA-ES 自己的 sigma（默认 ~0.30 normalized 即 30% range）小至少一个量级，**bias 永远不会主导 CMA-ES 的探索**。

4. callback 应用 `vec_orig + bias_vec` 后 clip 到 `[lower_bounds, upper_bounds]`，越界的轴自动收回到合法区间（避免污染协方差估计）。

**冲突处理**：相同参数被两条 severity 相同方向相反的 hint 引用时，`signed_weight` 自然为 0，该轴不动。这是设计意图：**channel 级证据相互矛盾时拒绝盲推**。

#### D. UI 暴露 mix_ratio 滑块

`AlgoConfigView.vue` 在 CMA-ES 子表加一行：

| 控件 | 默认 | 含义 |
|---|---|---|
| `hint_bias_mix_ratio`（带 E-010 badge）| 0.30 | 0 = 完全不偏置（cma_cold/cma_warm 旧版行为）；0.30 推荐起步；> 0.5 偏置主导 |

`CmaesStrategyConfig.hint_bias_mix_ratio: float = 0.30` + `cmaes_strategy_config_from_dict` 自动 clamp 到 [0, 1] + 处理 `""` / `NaN` / 字符串等错误输入；`fit_material.py --cma-hint-bias-mix-ratio` CLI 参数；`job_manager` 把 `cma_es.hint_bias_mix_ratio` 透传成 CLI 参数。

#### E. `decision.json` 新增 `cma_es.hint_bias` 块

```json
"hint_bias": {
  "mix_ratio": 0.30,
  "applied": true,
  "n_axes_biased": 7,
  "max_abs_delta": 0.024,
  "channels_used": ["base_color_main_texture", "emission", "color_grading_hsv_contrast"]
}
```

5 个字段足以事后 forensics：bias 是否真的生效、动了几个轴、最大单轴推力多少、哪几个 channel 的 hint 真贡献了。

**测试**：`tests/test_strategy.py` 新增 7 个测试覆盖：
- `wants_global_no_improve_check` 在两种 strategy 上的差异
- mix_ratio=0 时 callback 是 None / decision 上 `applied=False`（legacy 对照线）
- mix_ratio>0 + hints present 时确实有 ≥2 个轴被偏置 + decision 字段完整
- 同一参数被相反方向同 severity hint 时 net delta = 0（拒绝盲推）
- `u_MetallicRemap*` 通配匹配 `Min/Max` 两轴
- config dict round-trip 包含新字段
- `hint_bias_mix_ratio` 自动 clamp 越界值（5.0 → 1.0, -0.5 → 0.0, "abc" → 0.30, NaN → 0.0）

**回归**：`pytest tools/material_fit/tests` 122/122 通过（含新增 4 个 E-010 测试 + 现有 118 个）。

**待验证（不是这条改动能 ship 的）**：
- 真闭环 fish_1580 4 条件 × 50 evals 对照（P0-4），现在多一条对照线 `cma_warm-bias=0.30`，能直接看出"专家 hint 注入"实际带来多少 fit_score 提升。这条实验**强烈建议在用户把 Unity 和 Laya 背景手动统一成纯灰之后跑**——E-009 的 verify_e009.py 实验已经证明背景统一能让 fit_score 动态范围从 [0, 0.71] 恢复到 [0, 1.0]。
- `mix_ratio` 的 ablation（0 vs 0.15 vs 0.30 vs 0.50）等真实数据对照后才能定论文里的最佳默认值。0.30 是基于 "bias step 比 CMA-ES sigma 小一个量级" 的工程直觉，没有实测数据支持。

**论文角度**：
这一节是"如何把领域知识无损注入 black-box CMA-ES"的可发表小贡献——和"在 search loop 之外把 hint 当 warm-start"或"用 hint 重定义 sigma 各向异性"两种 alternative 设计相比，本方案的优点是：
1. 不修改 CMA-ES 内部状态（mean / C / sigma 的更新规则完全保留），所以保证理论上的收敛性（CMA-ES 论文里所有的收敛证明都依赖未受污染的内部更新）；
2. bias 是逐步施加的，不像 warm-start 一次性注入，可以**一直推**到收敛；
3. mix_ratio 提供了"专家 vs 数据"权衡的连续旋钮，0 / 1 两端都还是合法 CMA-ES 实例。

**文件清单**（新增 / 大改 / 小改）：

| 文件 | 改动量 | 性质 |
|---|---|---|
| `tools/material_fit/optimizer/cma_es_optimizer.py` | +28 行 | `ask(bias_callback)` + `BiasCallback` 类型别名 |
| `tools/material_fit/optimizer/strategy.py` | +200 行 | `wants_global_no_improve_check`, `CmaesStrategyConfig.hint_bias_mix_ratio`, `_build_hint_bias_payload`, `_compute_hint_vector`, `_param_match`, `_SEVERITY_WEIGHT`，dict 序列化 clamp |
| `tools/material_fit/fit_material.py` | +20 行 | `--cma-hint-bias-mix-ratio` CLI + `_override_cmaes_from_cli` clamp + `wants_global_no_improve_check()` 路由 |
| `tools/material_fit_ui/backend/job_manager.py` | +12 行 | optimizer 分流默认 iterations + `--cma-hint-bias-mix-ratio` 透传 |
| `tools/material_fit_ui/backend/project_store.py` | +14 行 | `hint_bias_mix_ratio` 默认值 + clamp |
| `tools/material_fit_ui/frontend/src/types.ts` | +6 行 | `CmaEsConfig.hint_bias_mix_ratio` 字段 |
| `tools/material_fit_ui/frontend/src/components/AlgoConfigView.vue` | +20 行 | hint_bias 控件 + `.badge` 样式 |
| `tools/material_fit/tests/test_strategy.py` | +160 行 | 7 个新测试 |

---

### E-009 (2026-05-06) — 评价指标科学化（auto-mask + channel-weighted MAE + SSIM）

**背景**：用户在 E-008 收尾后提出了一个**比算法选型更根本的问题**："各个分层的评分都抵达很高的水平，是否一定意味着我们的图像和原图像的差距基本就很小，肉眼观感已经很接近了？我觉得我们一定要先确定好这个问题"。

逐字检视 `vision/diff_analysis.py` + `vision/image_score.py` + `fit_material._diff_score_to_fit_score` 后定位出 7 个独立缺陷（详见 [`Metric_Validation.md`](Metric_Validation.md) §3）。其中两条是**致命的**：
1. **70% 信号污染**：Laya 截图 70.5% 像素是编辑器纯色背景 [134,151,180]，Unity 参考 21% 像素是另一种背景 [172,160,146]，两个不同色的背景被强行像素对比，对总 MAE 贡献巨大且与材质无关。
2. **指标在历史轨迹上对"哪个 iteration 最优"判断完全错误**：用 E-009 重新打分 fish_1580 12 轮历史轨迹后发现，老指标认为的最优 `iter_0001 (legacy_fit=0.114)` 在新指标下其实比 `iter_0000` 更差（0.0256 vs 0.0275）；真正的最优是被老指标当成"global_no_improvement"扔掉的 `iter_0004` (new_fit=0.0317)。**算法之前一直在追"背景颜色对齐"的幻觉，把噪声当 signal。**

**做了什么**：

- **新增 `tools/material_fit/vision/perceptual_score.py`**（450 行 + 完整 docstring + 论文引用骨架）：
  - `auto_background_mask(reference, candidate, AutoMaskConfig)` — 取两张图四角 12×12 块各自计算颜色中位数当背景色，把每张图离自己背景色 L∞ ≤ 16 的像素标为背景，最终 mask 是"**两张图都认为是前景**的像素"。当前景占比 < 5% graceful fallback 到无 mask。
  - `channel_weighted_mae(material_channels, ChannelWeightConfig)` — 6 个材质 channel 加权平均，默认权重为 stylized PBR 校准 (`base=0.30, metallic=0.18, grading=0.18, emission=0.12, fresnel=0.12, shadow=0.10` 总和 1.0，权重和不为 1 时构造期 raise）。无效 channel 自动剔除并对剩下重新归一化。
  - `ssim_score(reference, candidate, mask=None, win_size=7)` — 调 `skimage.metrics.structural_similarity`，可选 spatial mask 加权。SSIM 用 7×7 高斯窗口，对 1px 位移天然容忍。numpy/scikit-image 缺失时 graceful return `status="unavailable"`，永不抛错。
  - `combine_fit_score(weighted_mae, ssim, weights=(0.7, 0.3))` — MAE 分支 `1 - sqrt(4 * weighted_mae)`，SSIM 分支 `max(0, ssim)`，按 0.7 : 0.3 加权得最终 `fit_score`。SSIM 缺失时降级到 MAE-only。
  - `perceptual_score_from_analysis(analysis, ref_path, cand_path)` — 高层入口，给一个 diff_analysis 结果就吐出 `PerceptualScoreResult(fit_score, weighted_mae, ssim, auto_mask, ...)`.

- **`vision/diff_analysis.py` 接入**：
  - `ImageDiffConfig` 新增 `auto_mask_enabled=True / threshold=16 / corner_size=12`、`channel_weights / fit_branch_weights`。
  - `analyze_image_diff` 在累加像素 stats **之前**先跑 `auto_background_mask`，把得到的 numpy mask 当作每像素 weight 注入主循环（取代之前的 `weight = 1.0`）。这意味着所有 region MAE / channel MAE 自动建立在前景像素上，不需要下游 caller 再做。
  - 结果 dict 新增 `perceptual_fit_score` (顶层标量) + `perceptual` (子 block：`weighted_mae / weights_used / contributions / coverage / ssim / fit_components / branch_weights`) + `auto_mask` (`reference_bg_color / candidate_bg_color / foreground_ratio / status`)。老的 `score`（全图 RGB MAE）保留作向后兼容，但**已不再是优化器实际跟踪的目标**。

- **`fit_material.py` 切换默认 fit_score**：
  - 新增 `_resolve_fit_score(analysis, diff_score, mode)` —— 优先用 `analysis.perceptual_fit_score`，否则回退到 `_diff_score_to_fit_score(diff_score, mode)`。这意味着所有 E-009 之后的 run 都自动走新指标，老的 `fit_score_mode=perceptual` / `linear` 仅作 fallback。
  - `decision.json` 每轮新增 `perceptual_signals` 块（weighted_mae / ssim / fg_ratio / fit_components / weights_used / coverage + auto_mask 颜色），方便事后 forensics（出现 fit_score 退步时能拆是 MAE 漂还是 SSIM 漂还是 mask 漂）。
  - `state.best_score` 仍跟踪 `diff_score` (raw MAE)，保持 heuristic stage progression 的兼容；`best_fit_score` 已自动用新指标。

- **UI** `IterationDetail.vue` 加一行 E-009 perceptual pill：`weighted MAE` / `SSIM` / `fg ratio`，每个 pill 加 hover tooltip 解释它是什么。当 `decision.perceptual_signals` 缺失（老 run）时这一行自动隐藏，向后兼容。

- **`docs/Metric_Validation.md`**（新增 470 行）—— **专门当论文"指标设计"那一章的素材**：
  1. 问题陈述（pixel-MAE 不能代表"看起来像"的科学问题）
  2. 7 个具体缺陷的正式列举，每个引用代码路径 + 实测数据
  3. 新指标的三阶段定义（公式 + LaTeX + 默认权重表）
  4. 实证对照：fish_1580 12 轮历史轨迹用新指标重打分后**两套指标对"最优 iteration"的判断截然相反**
  5. 局限与 Tier 2 / Tier 3 工作（LPIPS、ECC alignment、人工评分校准、JND-based 缩放、多视角联评）
  6. 引用骨架：Wang+2004 (SSIM) / Zhang+2018 (LPIPS) / Itti+Koch 2001 (saliency) / Laine+2020 (alpha compositing)
  7. 默认 channel 权重的敏感性表（4 套 profile：default / colour_only / lighting_focused / equal）以备未来 ablation 研究

- **`tests/test_perceptual_score.py`**（20 个新测试，全套 116/116 通过）：
  - `auto_background_mask` 4 个：corner-bg 排除、disabled fallback、low-signal fallback、shape mismatch。
  - `channel_weighted_mae` 4 个：等值 sanity、部分 invalid 重归一化、全 invalid → ∞、权重和不为 1 raise。
  - `ssim_score` 3 个：identical → 1.0、masked SSIM 不抛、shape mismatch → unavailable。
  - `combine_fit_score` 3 个：MAE 单调递减、SSIM 单调递增、SSIM 缺失降级。
  - `analyze_image_diff` 集成 2 个：新字段全部存在、explicit mask 时 auto_mask=None。
  - `_resolve_fit_score` 集成 3 个：偏好 perceptual_fit_score / fallback / clamp 到 [0,1]。

- **`tests/manual/rescore_e009.py` + `tests/manual/smoke_e009.py`**：手动诊断脚本，前者重打分历史轨迹生成 `e009_rescore.json`，后者一次性 dump 当前 ref/cand 的所有新指标信号。这两个不是 pytest 用例，是"我现在到底测出了什么"的 first-line 工具。

**重打分得到的关键数据**（fish_1580，12 轮）：

```
iter   legacy_fit    new_fit   legacy_mae   weighted_mae    ssim    fg_ratio
0000     0.0675     0.0275       0.2174        0.3495      0.0916    0.287
0001     0.1143  ★  0.0256       0.1961        0.3427      0.0855    0.286
0004     0.0673     0.0317  ★    0.2175        0.3443      0.1055    0.287
0011     0.0594     0.0239       0.2212        0.3579      0.0798    0.243
```

老指标的"最优"在新指标下是退步；新指标的"最优"被老指标当成 `global_no_improvement` 扔掉。这意味着 §2 P0-4（fish_1580 真闭环验证）必须用新指标重跑，**E-006 / E-007 之前的所有"算法效果"结论都不能直接使用**。

**给用户的实操建议**：
1. 老 run 的 `best_fit_score` 数字（如 0.114）**不能直接跟新 run 比**——它们尺度不同。需要先跑 `python tools/material_fit/tests/manual/rescore_e009.py` 重打分。
2. UI 上看每轮新增的 `weighted MAE` / `SSIM` / `fg ratio` 三个 pill 才是判断"是否真的在变好"的依据。`fg ratio` < 0.10 时建议重新框选截图区域（说明背景太多了）。
3. 我们之前用 `target_score = 0.9` 是按老指标尺度估的；新指标尺度下 0.9 几乎不可达。建议 target_score 临时下调到 **0.30-0.50** 等几轮真闭环跑出来再校准。

**留下的边界情况**：
- 默认权重 `{base=0.30, metallic=0.18, grading=0.18, emission=0.12, fresnel=0.12, shadow=0.10}` 是按 `fish_1580` 这种 stylized PBR 校准的。toon / hard surface / 卡通厚涂 这些场景可能要换 profile（`Metric_Validation.md` Appendix A 列了 4 套备选 profile）。
- `auto_background_mask` 用 4 角颜色聚类找背景。如果模型恰好占据图像 4 角（极少见），算法会把模型当背景 mask 掉、触发 `low_signal` fallback 到无 mask。需要时可以 disable auto_mask 走显式 mask_path。
- SSIM 用 7×7 窗口，对 ≤ 3 像素位移敏感，对更大位移（> 5 像素）几乎不区分。下一阶段 (Tier 2) 会加 ECC pre-alignment 解这个问题。
- 还没接 LPIPS / DISTS（论文级感知度量）；当前 SSIM 是 cheap 替身，下一阶段 (Tier 2) 替换。

**E-009 后续验证（2026-05-06，同晚 follow-up）**：

跑了 [`tests/manual/verify_e009.py`](../tests/manual/verify_e009.py) 合成对照实验，发现 **E-009 自身解不掉的一个盲点**——silhouette 抗锯齿。**前景完全相同、仅背景颜色不同时，fit_score 从理论上的 1.0 掉到 0.71**——0.29 的损失全部来自模型边缘像素跟不同背景做的 alpha-blend，那些像素 auto-mask 正确认作前景但携带系统性色差。

定量结论：

| 实验 | fit_score | 含义 |
|---|---|---|
| 完全相同前景 + 相同 bg | **1.000** | 黄金参考 |
| 完全相同前景 + 不同 bg (Unity vs Laya) | 0.711 | **0.289 是纯粹的 silhouette AA 噪声** |
| 鱼略有差异 + 不同 bg（当前生产） | 0.668 | "tiny error" 的 baseline |
| 鱼略有差异 + 相同 bg（统一后） | **0.801** | **+0.133 纯背景统一收益** |
| 完全相同前景 + 1px 位移 | 0.710 | SSIM 完美吸收，penalty 仅 0.0016 |

**关键推论**：在不同 bg 下，**fit_score 的实际天花板是 0.71，不是 1.0**——`target_score = 0.9` 在数学上根本不可达。统一 bg 后才能恢复完整 0-1 量程。

**给用户的实操建议（E-009 后续）**：把 Unity 的 Camera Clear Color 和 Laya 的 Scene Clear Color **都设成纯中灰 `(128, 128, 128)`**，5 分钟工作量等价于跳过 5-15 轮算法迭代：
- 不要用纯黑（边缘 AA 让所有边缘看起来变暗，会诱导算法调亮 BaseColor）
- 不要保留 Laya 默认蓝灰 (134,151,180)（B 通道偏高 + 亮度 63%，会污染 highlight 桶）
- 中灰对 RGB 三通道贡献相等，AA 边缘最公平

target_score 在统一 bg 之后建议设 0.85；不统一时任何 > 0.71 的目标都是不可达的伪目标。

详见 [`Metric_Validation.md` §5.5](Metric_Validation.md)。

---

### E-007 (2026-05-06) — Laya refresh 假设的 magenta 探针

**背景**：用户反馈"目前算法的每轮迭代好像就四次就停了，调整的参数部分也不是很多……我到目前都不清楚 Laya 是不是在我们调整完参数之后立马重新渲染了"。

这是一个**致命的开放假设**：整条 fit pipeline 都建立在"写完 .lmat → Laya 立刻重渲染 → 截屏拿到的是新帧"上。如果这个链条任何一环没成立（Laya 不开 file watcher / `rerender_wait_ms` 太短 / 截图区域选错 / .lmat 路径不是当前 Laya 加载的那个 / Laya 缓存了旧材质），那么 `fit_score` 全是错的，optimizer 在跟一个鬼魂搏斗。任何"算法效果一般"的结论在没验证这个假设之前都不可信。

**做了什么**：
- **`tools/material_fit/laya/refresh_probe.py`** — 三步法 magenta 探针：
  1. 用当前 .lmat 截一次 baseline。
  2. 备份 .lmat，写一个 magenta 探针色（默认 `u_BaseColor = [1, 0, 1, 1]`）→ `time.sleep(rerender_wait_ms / 1000)` → 截屏。
  3. shutil 还原 .lmat → 等 → 再截屏。
  - 判定：probe 截图的 magenta 像素占比 ≥ baseline + 10%（detection threshold）；restored 截图的 magenta 像素占比 ≤ probe - 10%（restore threshold）。两个都满足 → success。
  - 选 magenta 是因为 fish_1580 / 大多数自然材质都不会自然产生 magenta，信噪比高，threshold 可以设很激进。
  - 整个过程是 transactional 的：捕获/还原任何一步抛异常都会尝试 best-effort restore，原 .lmat 用 `<lmat>.refresh_probe.bak` 留下证据；**写探针 .lmat 走 `lmat_io.write_candidate_lmat` 严格校验**，写不出去就 fail-fast 不动盘。
- **`fit_material.py`** — 新增 CLI `--laya-refresh-check` + `--laya-refresh-check-param`。开启后，在 `_run_auto_adjustment` 之前跑一次探针，结果落盘到 `output/<case>/auto_adjust/preflight.json` + 三张 PNG `output/<case>/auto_adjust/preflight_captures/{baseline,probe,restored}.png`。如果 `success=False`，`return 0`（不是 crash），但不会进入真正的 auto-adjust 循环——拒绝在错误的假设上烧时间。
- **UI 后端** `tools/material_fit_ui/backend/preflight.py` + `POST /api/projects/{id}/preflight/laya_refresh` endpoint。复用 `capture_laya_region` 同一条路径（不能用别的 capture，否则探针通过的不是真 loop 的事情）。结果持久化到 `output/<project>/preflight/last.json`，`GET` endpoint 拿历史。
- **UI 前端** `RefreshPreflightCard.vue` 嵌入 `ProjectConfigView`，紧跟在"Laya 截图区域"之后——这两个是逻辑上的依赖链：先有截图区域，才能验证截图能拍到 .lmat 改动。卡片显示三张图横向对比 + 每张的 magenta 占比 + reason（success 时是绿色提示，failure 时是红色 + 用户能改的具体原因，比如"`probe param 'u_BaseColor' is not present in the .lmat's props`"）。
- **12 个测试**（`tests/test_refresh_probe.py`），覆盖：
  - `magenta_ratio` 检测器（纯洋红 = 1.0 / 纯灰 = 0.0 / 半半 ≈ 0.5 / 琥珀色 fish_1580 实际色 = 0.0）。
  - happy path（grey → magenta → grey 通过）。
  - **frozen Laya**（三张都 grey → success=False，reason 包含"not refreshing"）—— 这是用户怀疑的那个失败模式。
  - **失败的 restore**（grey → magenta → magenta → success=False，reason 包含"unknown state"）。
  - probe param 不在 .lmat / .lmat 不存在 → 失败前不动盘、不调 capture。
  - **capture 抛异常时仍然恢复 .lmat**（最重要的鲁棒性属性）。
  - round-trip 后 `lmat_io.diff_shapes` 为空（保证不留下结构性损坏）。

**怎么用（操作手册）**：
1. UI 项目页 → 滚到"验证 Laya 是否真的在刷新"卡片 → 点"运行 Laya 刷新探针"。
2. 等 ~5 秒（取决于 `rerender_wait_ms`，默认 1.5s × 3）。
3. 看三张图：
   - **三张都看着像 baseline** → Laya 没在 .lmat 写入后重渲染。先检查（a）`laya_material_lmat_path` 是不是 Laya 项目里那个真正的 .lmat（**不是** tools 目录下的副本）；（b）`rerender_wait_ms` 是不是太短（试 3000-5000ms）；（c）Laya 编辑器是不是开着且关注那个材质球。
   - **中间变红，边上没回来** → restore 失败。.lmat 现在状态未知，去 `<lmat>.refresh_probe.bak` 手动还原。
   - **三张分别灰/红/灰** → 通过。可以放心切到正式 auto-adjust 跑了。
4. **CLI 同等功能**：`python -m tools.material_fit.fit_material --config <path> --auto-adjust --apply-lmat --laya-refresh-check`，preflight 失败会落盘到 `auto_adjust/preflight.json` 并跳过真实跑动。

**E-007 后续发现 (2026-05-06，同一晚 follow-up)**：

用户实测：UI 探针的三张图全是相同的 baseline 帧（红色机甲，magenta 占比 0.0% / 0.1% / 0.0%），但**手动操作时如果先点击 Laya 编辑器窗口，三张图就会正常变色**。

定位结果：**Laya 编辑器跟 Unity Editor、Unreal Editor 一样，在窗口失焦时会暂停渲染**——这是游戏编辑器为了省 GPU 的常规设计。我们的 pipeline 在 FastAPI 子进程里跑，浏览器（前端）是 foreground，所以 Laya 收到 file-watcher 事件但**根本没画下一帧**。结果：probe / restored 截屏拿到的都是 baseline 那一帧的旧像素。

**修复（同一晚 ship）**：
- **新增 `tools/material_fit/laya/window_focus.py`** — Win32 API 封装：`EnumWindows` + `OpenProcess` + `QueryFullProcessImageName` 找窗口，`AttachThreadInput` + `BringWindowToTop` + `SetForegroundWindow` 拉前台，最后兜底一个 `keybd_event(VK_MENU)` ALT 按键模拟来绕过 Windows 的 SetForegroundWindow 限制。非 Windows 上 graceful no-op。
- **API**：`focus_laya_window(FocusTarget(process_pattern, title_pattern), settle_ms)` → `FocusResult`。默认 `process_pattern="LayaAirIDE"`；`title_pattern` 填 Laya 编辑器**窗口标题栏的项目名**（**注意**这跟 UI 项目 id 没关系，在用户机器上 UI 项目 id 是 `fish_1580` 但实际 Laya 窗口标题是 `effect`）。
- **`refresh_probe.py`** 新增 `focus: FocusCallable | None` 参数，**在 5 个时机调用**：每张截屏前 + 每次 .lmat 写入前。`focus_log` 记到 `ProbeResult` 里、UI 显示成表格让用户一眼看出哪一步聚焦失败。
- **`fit_material.py`** 加 CLI `--laya-window-process` / `--laya-window-title`，新建 `_build_focus_callback()` helper，preflight 和 `_run_auto_adjustment` 的 `capture_screen_after_apply` 路径都接上：写 .lmat 之前 focus 一次，sleep `rerender_wait_ms`、截屏之前再 focus 一次。每轮的 focus_log 落到 `decision.json["focus_log"]`。
- **`project.json`** 新增 `inputs.laya_window = {process_pattern, title_pattern, settle_ms}`，UI `ProjectConfigView` 加"Laya 窗口聚焦"配置面板，用户能改 process / title / settle_ms。
- **job_manager** 默认 `algorithm_config.laya_refresh_check=true`，每次跑 auto-adjust 前自动跑一次 preflight 不让用户裸奔。
- **17 个新测试**：`test_window_focus.py`（13 个：pattern 匹配、非 Windows fallback、默认值、多 Laya 项目消歧、SetForegroundWindow 失败上报、ctypes 异常隔离、settle_ms 真的 sleep）+ `test_refresh_probe.py` 加 4 个 focus_callback 行为测试（5 个时机调用顺序、focus 失败不阻断 probe、focus hook 抛异常隔离到 focus_log、None 时向后兼容）。

**给用户的实操建议**：
1. UI 项目页"Laya 窗口聚焦"区域：`process_pattern` 留默认 `LayaAirIDE`；`title_pattern` 填**当前在 Laya 编辑器里打开的项目名**——不是 UI 这边的项目 id，而是看 Laya 编辑器窗口标题栏（在该用户机器上是 `effect`，UI 项目 id `fish_1580` 只是在写 `assets/resources/play/fish/1580/...` 路径下的 .lmat）。同时开多个 Laya 项目时尤其要填，不然可能聚焦到错的那个。
2. `settle_ms` 默认 250ms，慢机器调到 500-1000ms。
3. 然后再跑"运行 Laya 刷新探针"，应当能看到三张图正常变色，且新出现的"Laya 窗口聚焦日志"表格 5 行全部 ✓。

**留下的边界情况**：
- 如果 SetForegroundWindow 仍然被 Windows 拦截（前台进程几秒内有键鼠输入时会发生），那一次会上报 success=False。处理：`focus_log` 表格会标红出来；用户手动点一下 Laya 窗口、或者把鼠标移开几秒再重跑。
- 当前实现是 Windows-only。Mac/Linux 用 AppleScript / wmctrl 在 `_bring_to_foreground_*` 里加分支即可，没在本期做。

**E-007 第二次后续发现 (2026-05-06，再 follow-up)**：

用户测试焦点修好之后又上报：
1. **探针的"洋红像素占比"判定过于严格** —— 截图里 probe 那张明显比 baseline 更"洋红化"，但因为 fish_1580 模型已经叠了基础贴图 + 法线图，原色是深红 (R≈180,G≈40,B≈70)，写入 `u_BaseColor=[1,0,1,1]` 后只是把 G 通道乘 0，结果是 (180,0,70) — 远远不是严格的纯洋红 (255,0,255)，`magenta_ratio` 就只有 0.1%，触不到 10% 的阈值。
2. **询问唤醒 Laya 时窗口位置变化是否被自适应** —— 答案是没有（`SetForegroundWindow` 不动位置只动 Z-order，所以截图区域还命中），但用户后续如果**手动拖 Laya 窗口** 截图就会跑偏。

**修复（同一晚 ship，加 14 个新测试，总 96 通过）**：

(a) **`refresh_probe.py` 把判定算法换成"逐像素平均色差"** —— 直接计算 baseline 和 probe 两张图的 mean L1 距离（在 [0,255] 标度上）。这个算法是色调无关的：
- Laya 冻结（两张完全一样）→ 0
- 单通道变化 40（用户的真实场景）→ 平均 ≈ 13.3
- 灰 vs 纯洋红 → ≈ 127

  默认阈值：变化检测 ≥ 1.5，恢复检测 ≤ 2.5。能稳稳越过 PNG 重编码噪声地板（~0.5），又能稳稳触发"哪怕只有一个通道变了 40"的真实信号。`magenta_ratio` 仍然计算并展示，但**降为辅助诊断**，不再作为通过/失败的依据。

  在 `tests/test_refresh_probe.py` 里加了一个具体的 `test_run_refresh_probe_succeeds_on_dark_red_pbr_modulation` 把用户的实际场景（深红 → 深红+G=0）固定下来。

(b) **加"锚定到 Laya 窗口"的截图模式** —— 解决 Laya 窗口拖动后绝对截图坐标失效的问题：
- `laya/window_focus.py` 加 `WindowRect` + `get_laya_window_rect(target)` 用 `DwmGetWindowAttribute(EXTENDED_FRAME_BOUNDS)` 拿 Laya 窗口当前的可见矩形（排除 Win10 阴影边距）。
- `vision/screen_capture.py` 加 `CaptureAnchor(enabled, offset_x, offset_y, width, height, process_pattern, title_pattern)` 和 `resolve_anchored_region(anchor, fallback)`：每次截屏前查一次 Laya 窗口位置 → `current.left + offset_x` 算出实时绝对坐标。Laya 窗口找不到时降级到上次的绝对坐标，把降级原因记到结果的 `anchor_resolution` 字段里。
- `region_picker.pick_region` 增加可选 `laya_window` 参数。前端调用时把项目的 `laya_window` 配置传过去；后端在用户框选完之后，立刻 `get_laya_window_rect`，把 `(region.x - rect.left, region.y - rect.top, region.w, region.h)` 作为 `anchor` 一并返回。
- `project.json` 新增 `inputs.laya_capture_anchor = {enabled, offset_x, offset_y, width, height}`。默认 `enabled=true`，需要用户重新框选一次才会被填充上具体偏移。
- UI `ProjectConfigView` 在"Laya 截图区域"里加一个 ☑ "锚定到 Laya 窗口" 开关 + 当前偏移状态显示。
- `_run_auto_adjustment` 的 capture_screen_after_apply 路径、`_run_laya_refresh_preflight` 的 capture wrapper、UI `preflight._capture` 都接上 anchor。

(c) **UI 改进** —— `RefreshPreflightCard` 把第二行从"洋红像素占比 + 阈值"改成"色差 vs baseline + 阈值"，色差超阈值时绿、不超时红，用户一眼能看出离判定线还差多少。`magenta_ratio` 退到第二行作为辅助参考。

**给用户的实操建议（继 E-007 之后）**：
1. 重新点一次"在屏幕上框选…"（让 anchor 偏移记录上）。
2. 截图区域下方的"锚定到 Laya 窗口"已默认勾选；偏移信息会显示出来（dx/dy/w/h）。
3. 之后随便拖 Laya 窗口，截图都会自动跟着窗口走。

**留下的边界情况**：
- 如果用户**调整 Laya 窗口大小**（不是拖动），偏移仍然按"相对左上角"算，但模型在窗口里的位置会变化（因为 Laya 内部 layout 跟着窗口大小重排），可能模型不再在那个偏移处了。处理：勾选框旁边的提示告诉用户调整大小后需要重新框选。后期可以加一个"按窗口宽高比例缩放偏移"模式，但收益不大，先不做。
- 多 monitor 场景下 `DwmGetWindowAttribute` 给的是绝对桌面坐标（不是单 monitor 坐标），跟 PIL `ImageGrab.grab(bbox=)` 一致，所以这套也能直接用。

**没做什么**：
- 没做"自动建议合理的 `rerender_wait_ms`"。如果三次 wait 都不够，让用户手动调 algorithm_config.rerender_wait_ms 比让程序猜更可靠——猜错会把成本推到下一个真实跑里。
- 没做"自动选哪个 Color uniform 当 probe param"。`u_BaseColor` 适用于绝大多数 PBR/toon shader；遇到 base color 被贴图 fully masked 的特殊 shader 需要用户在 UI 输入框里改 probe_param。
- 没做"探针通过后自动连跑 auto-adjust"。两件事**应当分开执行**：探针只验证 Laya 行为，跑不跑 auto-adjust 是用户决定。

---

### E-006 (2026-05-06) — WS-CMA-ES 合成 benchmark 验证

**背景**：调研发现 Nomura et al. (AAAI 2021) 的 Warm Starting CMA-ES 已发表 + 有现成库（`pip install cmaes`），是替代当前启发式调度最便宜的候选。需要一个 < 0.5 天的实验验证它在我们这种问题结构上能不能用。

**做了什么**：
- 写了 `optimizer/cma_es_optimizer.py`：`ParameterEncoder`（`dict<param,float|list>` ↔ `np.ndarray`，自动跳过 texture/`*_ST`/blacklist；color 只暴露 RGB 3 维 alpha 缓存）+ `CmaesOptimizer`（包装 `cmaes.CMA`，内部 [0,1] 归一化空间防止异构 bound 问题，支持 `warm_start_samples` 和 `initial_mean`）。
- 11 个单测（`tests/test_cma_es_optimizer.py`）覆盖编解码、bounds、ask-tell、warm-start 构造。
- 合成 benchmark `experiments/cma_es_warm_start_benchmark.py`：33 维 box-bounded + 多模态 + 参数耦合，对比 `cma_warm_good` / `cma_warm_noisy` / `cma_cold` / `random_search`。

**结论**（5 seeds × 800 evals）：

| 算法 | 200 evals 时 final | 800 evals 时 final |
|---|---|---|
| `cma_warm_good` | 0.97 | **0.13** |
| `cma_warm_noisy` | 1.86 | 0.44 |
| `cma_cold` | 2.40 | 0.53 |
| `random_search` | 1.71 | 1.71 |

- 同 200 budget 下 WS-good 比 cold loss 低 **2.47×**。
- WS-good 跑 200 evals 的水平 cold 要跑到 622 evals 才追上 → **3.1× evaluation 节省**。
- Survey 文档里写的"5-10×"过于乐观，**真实可宣的是 2-3×**。

**踩到的两个 bug**（也写进了报告）：

1. 异构 bound 共享 sigma 让 cold CMA-ES 比 random search 还差 → 内部 [0,1] 归一化修复。
2. 每 run 重建 `ParameterEncoder` 让 dict 顺序漂移 → 共享 encoder + `initial_mean` 参数修复。

**不能宣称什么**：
- 合成目标 ≠ 真实 Laya 渲染。
- "good prior" 是从已知 target 周围采样的，比真实启发式 prior 强。
- 没跟我们自己的启发式做过对照（heuristic 用的是 channel-bias 信号，合成目标里没有）。

**下一步**：~~见 §2 P0-1（接进 `fit_material.py`）~~ 已完成 ↓；剩 P0-2（真 Laya 闭环对比）。

**详细报告**：[`Experiment_Phase1_CMA_ES_WarmStart.md`](Experiment_Phase1_CMA_ES_WarmStart.md)

#### E-006 后续 (2026-05-06) — 接进 fit_material + UI（P0-1 完成）

**背景**：用户批准把 CMA-ES 接进生产管线："好的，既然你认为可行，那就做吧"。

**做了什么**：
- **新建 `optimizer/strategy.py`**：抽象出 `OptimizerStrategy` 接口（`propose(StrategyContext) -> (next_params, decision)`）、`HeuristicStrategy`（包装现有 `propose_next_params`）、`CmaesStrategy`（包装 `CmaesOptimizer`，每个 propose 顶部 tell 上一轮 fit_score、再 ask 下一个候选）。`build_strategy(optimizer="heuristic|cma_cold|cma_warm")` 是统一入口；未知名称直接抛 `ValueError`，不静默 fallback（避免实验对照混淆）。
- **`fit_material.py`**：`_run_auto_adjustment` 重构，移除内部 `choose_stage` / `propose_next_params` / `update_stage_progress` 直调（这些现在归 `HeuristicStrategy` 内部管），统一通过 `strategy.propose(ctx)` 拿 `(next_params, decision)`。新增 CLI：`--optimizer {heuristic, cma_cold, cma_warm}`、`--cma-warm-start-iters`、`--cma-population-size`、`--cma-sigma`、`--cma-seed`。`auto_adjust_result.json` 末尾追加 `optimizer` / `cma_es_config` / `warm_start_history_size` 字段。
- **Warm-start 历史从盘面加载**：新增 `_load_warm_start_history(auto_dir, limit)` 扫描 `auto_adjust/iter_*/decision.json` + `candidate/params.json`，按 iteration 升序取最后 `limit` 条作为 prior。当 cma_warm 历史 < 2 条时自动降级到 cold（不抛错）。
- **`cma_es_optimizer.CmaesOptimizer`**：自动放宽 `get_warm_start_mgd` 的 `gamma` 参数——库默认 `gamma=0.1` 需要 `≥10` 个 source samples 才能 floor 出 ≥1 elite，我们的 heuristic prior 通常只有 6-12，所以 `gamma = max(default, 1/N)` 让 N=3 也能跑（取 top-1 当 elite）。
- **UI 后端**：
  - `project_store.py` 默认 `algorithm_config` 加 `optimizer: "heuristic"` + `cma_es: {mode, warm_start_iters, population_size, sigma, seed}`，`derive_fit_config` 透传到 `fit_config.json`。
  - `job_manager.py` 把上述字段渲染成 CLI flag 传给子进程；`_summarize_decision` 提取 `optimizer` / `cma_es` 给 UI 展示。
- **UI 前端**：
  - `types.ts` 加 `OptimizerKind = 'heuristic' | 'cma_cold' | 'cma_warm'` + `CmaEsConfig`，扩 `AlgorithmConfig`。
  - `AlgoConfigView.vue` 加 optimizer 下拉 + CMA-ES 子面板（仅 cma_* 时启用 warm_start_iters 输入；其他三项都接受空值表示用库默认）。每个选项有 hover-style 解释。
- **测试**（共新增 22 个，全套 60 通过）：
  - `tests/test_strategy.py`（17 个）：`build_strategy` 路由 / heuristic 包装一致 / cma_es ask-tell 推进 / fit_score→loss 单调性 / warm_start 自适应 / 空 history fallback / 配置 dict round-trip / 全 texture 输入抛 OptimizerUnavailableError / E-002 stuck 计数契约保留。
  - `tests/test_fit_material_optimizer_branch.py`（5 个）：mock 掉 `analyze_image_diff` + `_collect_image_pairs` + `RenderDriver`，端到端跑 `_run_auto_adjustment(optimizer=...)` 验证：(a) heuristic 分支正常；(b) cma_cold 分支跑 4 轮后 `evaluations==3`；(c) cma_warm 真的从盘面 `iter_000{0..2}` 加载到 3 条 prior 并 `warm_started==True`；(d) 未知 optimizer 返回 `configuration_error` 而不是崩；(e) cma_warm 无历史时安静降级到 cold。

**踩到的坑**：
1. `cmaes.get_warm_start_mgd(gamma=0.1)` 默认要求 ≥10 source samples，否则 `assert gamma_n >= 1` 直接炸。修法：自适应 `gamma`（见上）。
2. 第一版测试的 `last_loss_fed` 断言写错了——CMA-ES 的 propose 在循环顶部 tell 的是 **当前 ctx.fit_score**（即上一次 ask 的候选渲染后得分），所以 N 轮后最后一次 tell 喂的是 `fit_scores[-1]`，不是 `fit_scores[-2]`。

**没做什么 / caveats**：
- **没在真 Laya 上验证**——CMA-ES 的"2-3× 加速"目前只是合成 benchmark 的结论，对 fish_1580 在真实闭环上是否成立没数据。这是 P0-2 的工作，需要 ~5h 机时 + 真实截屏。
- **没做大模型辅助 / 多目标 / 可微渲染**——这些都还在 P1/P2。

**怎么用（操作手册）**：
1. UI 项目页 → "算法配置" → optimizer 下拉选 `cma_warm`（推荐）或 `cma_cold`（无 prior 对照）。
2. CMA-ES 子面板：`warm_start_iters` 默认 12 即可；`population_size` 留空让库自己根据维度算（8-16 之间）；`sigma` 留空 = 0.30；`seed` 留空表示不固定（实验对照时再设固定种子）。
3. 保存配置 → 回项目页 Start → 每轮 `decision.json` 里 `decision.optimizer == "cma_es"` 标记走的是哪条；`auto_adjust_result.json` 末尾的 `optimizer` / `cma_es_config` 字段记录这次实际跑的配置。
4. cma_warm 第一次跑且 `auto_adjust/` 是空的会安静降级到 cold（`warm_started==false`）；先跑几轮 heuristic 再切 cma_warm 接力是标准 workflow。

---

### E-005 (2026-05-06) — 学术化 + Related Work 系统调研

**背景**：用户问"是否可以参考现有学术论文的代码源码 / 思路"。需要把工程问题抽象成科学问题，再调研已有工作判断创新点。

**做了什么**：
- `docs/CrossEngineMaterialFit_Research.md`（737 行）：问题背景 / 现状 / 难点 / 抽象出的科学问题（Inverse Rendering with Engine-as-Black-Box-Renderer）/ 5 阶段路线 / 5 个潜在创新点。
- `docs/RelatedWork_Survey.md`（753 行）：60+ 篇文献，覆盖 Inverse Rendering / Differentiable Rendering / Procedural Material Capture / SVBRDF Estimation / Black-Box Optimization / LLM-Graphics / Cross-Engine Migration 7 个方向，做横向对比表 + 决策矩阵。
- 关键发现：
  - **DiffMat 不是最佳基线**——它的 mixed-integer 优化对我们这种连续参数过度复杂；推荐改用 NVIDIA `nvdiffmodeling` (Hasselgren et al., EGSR 2021)。
  - **WS-CMA-ES 已发表**（Nomura 2021），可直接 import，是 Phase 1 最便宜的实验。
  - **跨引擎材质迁移 + 黑盒商业引擎** 这个组合在学术界基本没人做（HLSLcc/Unifree 是工程项目，不是学术）——是真实存在的 academic gap。

**结论**：路线从"自己重写 DiffMat 风格"调整为"WS-CMA-ES 先验证 → nvdiffmodeling 风格可微 baseline → 跨引擎 benchmark + 论文"。

**这是研究文档，不影响 app 行为**。

---

### E-004 (此前) — Fit score perceptual 模式

**背景**：用户反馈"两张图明显有差异，打分却 0.78，根本没用迭代"。

**做了什么**：
- `fit_material.py` 加 `--fit-score-mode {linear, perceptual}` CLI 参数。
- `linear` 模式 `score = 1 - MAE`（旧的、过宽松）。
- `perceptual` 模式 `score = 1 - sqrt(MAE * 4)`，对小 MAE 更严格。
- UI `AlgoConfigView.vue` 加下拉选择并解释。
- `job_manager.py` 把 `--fit-score-mode` 透传给子进程。

**🟢 shipped**——重启 app 后能直接选。

---

### E-003 (此前) — UI 项目化 + 屏幕框选

**背景**：用户希望"前端能控制后端各种程序活动"，从只读 inspector 进化成完整 control center。

**做了什么**：
- 新建项目向导（`NewProjectWizard.vue`）：选 Unity shader / 材质 JSON / Unity 渲染图 / Laya shader / Laya `.lmat` / 屏幕截图区域。
- 屏幕区域改成"在屏幕上框选"按钮（`region_picker.py` 子进程调 `screen_capture.select_region_interactively`），不再让用户填 `x,y,w,h`。
- 项目页：`ProjectConfigView` / `PreanalysisView`（含手动覆盖参数映射） / `AlgoConfigView` / `RunConsoleView`（实时迭代轮询）。
- 后端 `project_store.py` + `job_manager.py` + `preanalysis.py`。

**🟢 shipped**。

---

### E-002 (此前) — Stage 推进 bug 修复

**背景**：用户跑了 12 轮，全部卡在 `base_color` stage，只动了 `u_BaseColor` 和 `u_Gamma_Power` 两个参数。这违背了"先粗后细"的 stage 设计。

**做了什么**：
- 根因：`choose_stage` 没用 `policy.max_iterations`，也没"卡住自动跳到下个 stage"机制；旧的 `if stop_reason == "no_effective_change": stage_index += 1` 太脆弱。
- `AdjustmentState` 加 `stage_iteration` / `stage_best_score` / `stage_no_improve` / `cycle` / `global_no_improve`。
- 完全重写 `choose_stage`：根据 (1) `target_score` 达成 (2) `max_iterations` 用尽 (3) `STUCK_NO_IMPROVE_LIMIT` 推进，并支持 cycle 回跳到 stage 0 做 refinement。
- 加 `update_stage_progress` 和 `should_abort_global`。
- `tests/test_stage_progression.py`（10 个）+ `tests/test_real_run_simulation.py`（2 个，模拟用户那次 12 轮的真实 channel 分数）。

**🟢 shipped**——再跑就不会卡。

---

### E-001 (此前) — `lmat_io` 严格校验

**背景**：用户报告"修改之后连模型都显示不出来"，只能从存档恢复。三个 root cause：
1. `build_initial_params` 把 texture sampler 的字符串默认值（`"white"`）当 top-level scalar 写进 `props.u_BaseMap`。
2. `shader_parser._read_field` 的正则把向量默认值 `[1,1,1,1]` 截成 `'[1'`。
3. `lmat_io.apply_params` 盲写不校验 type/shape。

**做了什么**：
- `shader_parser._read_field` 正则重排，先匹配 `[...]` 和 `"..."`，再 fallback。
- `parameter_search.build_initial_params` 过滤 texture sampler 和非数值默认值。
- `lmat_io.apply_params` 重写为严格模式：拒绝新 key、拒绝 shape/type 改变、拒绝写保留 key（`textures`、`defines`、`s_*`、`type`）；违反时 raise `LmatWriteError`。
- 新加 `lmat_io.write_candidate_lmat`：先 in-memory 校验 → 写盘 → 重读校验（`diff_shapes`），失败自动删文件。
- `lmat_io.save_lmat` 显式 `newline='\n'`，避免 Windows 把 `\n` 转成 `\r\n` 破坏字节级 round-trip。
- `tests/test_lmat_io.py` 15 个测试，含"导入贴图不被删除""保留 key 不被覆盖""shape 改变被拒绝""round-trip byte-identical"等。

**🟢 shipped**——现在就算 LLM 给你一个完全错的 dict，也只会被拒绝写入而不会写坏。

---

## §4  这份文档怎么维护

- 任何对 `optimizer/` / `laya/` / `vision/` / `fit_material.py` 的非平凡改动，做完后在 §3 加一条 E-xxx。
- 每条 E-xxx 必须填：背景 / 做了什么 / 结论 / 状态（生命周期标签）/ 不能宣称什么 / 下一步。
- 改完后**同步更新 §0 头部表**——这是用户判断"app 能不能用"的唯一权威来源。
- 状态变化时（🟡 → 🟢 那一刻），把对应行从 §2 待办移到 §3 记录。
- 长报告（论文级、>500 行）单独一个 `Experiment_<topic>.md` 文件，§3 这里只放 1 段摘要 + 链接。
