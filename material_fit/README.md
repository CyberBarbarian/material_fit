# Material Fit Inspector — 算法 / CLI / 文档

把 Unity 中某个材质实例的渲染效果，**反复改写 Laya `.lmat` 直到肉眼像** 的自动化工具。本目录是工具的**算法层 + CLI 入口 + 文档库**；UI 在隔壁 [`../material_fit_ui/`](../material_fit_ui/)。

> **第一次接触本仓库？** 请先读 [`AGENT_ONBOARDING.md`](AGENT_ONBOARDING.md)（5 分钟把工具概貌、当前能力状态、文档可信度全弄清楚），再看本文。

---

## 当前目录结构

```text
tools/material_fit/
├── AGENT_ONBOARDING.md          # 新接手 agent 的第一读物
├── README.md                    # 本文档
├── fit_material.py              # CLI 入口；自动调参主循环
├── fit_config.example.json      # 示例配置（路径需用户自填，详见文件内注释）
├── IntegrationDifficulties.md   # （历史）早期"四个关键难点"分析
├── LLMContextPrompt.md          # （历史）早期 LLM 上下文规范
│
├── docs/                        # 当前文档（全部反映工具现状）
│   ├── ExperimentLog.md         # ⭐ 实验日志 + 工具能力状态权威表（必读）
│   ├── Metric_Validation.md     # E-009 评分体系科学论证
│   ├── Experiment_Phase1_CMA_ES_WarmStart.md
│   ├── RelatedWork_Survey.md    # 学术 Related Work
│   ├── CrossEngineMaterialFit_Research.md  # 学术定位 + 创新点提炼
│   └── MaterialAutoFitTool.md   # （历史）最初设计文档
│
├── unity/                       # Unity 端：解析 ShaderLab + 导出真实材质
│   ├── shader_parser.py
│   ├── unity_material_exporter.cs
│   └── unity_shader/
│
├── laya/                        # Laya 端：解析 Shader3D + 读写 .lmat + 窗口控制
│   ├── shader_parser.py         # 解析 Laya Shader3D uniformMap / defines
│   ├── lmat_io.py               # 读 / 备份 / 严格写 .lmat（写后立刻校验）
│   ├── render_driver.py         # Laya 渲染驱动（dry-run / Puppeteer）
│   ├── window_focus.py          # E-008: Win32 强制把 Laya 窗口拉到前台
│   └── refresh_probe.py         # E-007: 验证 Laya 真在重渲染（magenta probe）
│
├── vision/                      # 图像处理 / 评分 / 桌面截图
│   ├── perceptual_score.py      # E-009: 自动背景 mask + 通道加权 MAE + SSIM
│   ├── background_normalize.py  # E-011: 跨引擎背景色统一预处理
│   ├── diff_analysis.py         # 主分析入口（接 perceptual_score + background_normalize）
│   ├── screen_capture.py        # 桌面截图；E-012 加 max_keep 滚动上限 + output_path 固定槽位
│   ├── analyze_diff.py          # 单次差异分析的 CLI
│   ├── image_score.py           # 老的全图 RGB MAE（保底，新流程默认不走它）
│   └── capture_laya.js          # Puppeteer 自动截图原型
│
├── optimizer/                   # 算法层（启发式 + CMA-ES 可插拔）
│   ├── parameter_search.py      # 启发式 stage 调度
│   ├── cma_es_optimizer.py      # E-006/E-010: CMA-ES 包装 + hint bias 注入
│   ├── strategy.py              # OptimizerStrategy 接口；HeuristicStrategy / CmaesStrategy
│   ├── adjustment_algorithm.py  # 启发式参数调整核心
│   └── parameter_encoder.py     # 参数 ↔ CMA-ES 实数向量转换
│
├── shared/                      # 跨模块共享数据结构 / 报告
│   ├── models.py
│   └── report.py
│
├── tests/                       # pytest 测试套（150+ 个用例）
│   ├── test_*.py
│   └── manual/                  # 人工跑的 smoke / verify 脚本
│
├── experiments/                 # 合成 benchmark 脚本
│   └── cma_es_warm_start_benchmark.py
│
└── output/                      # ⚠️ 用户运行时数据（不属于工具代码）
    └── <project_id>/            # 每个 UI 项目一个子目录
        ├── project.json         # UI 持久化的项目设定（绝对路径形式）
        ├── fit_config.json      # 由 project.json 派生，喂给 fit_material.py 的配置
        ├── auto_adjust/         # 每轮迭代的 decision.json + 候选 .lmat + 图像分析
        ├── preflight/           # E-007 探针的 baseline/probe/restored.png
        └── ...
```

---

## 这工具今天到底能做什么

请直接看 [`docs/ExperimentLog.md`](docs/ExperimentLog.md) 的 **§0 头部表**，那里维护"哪个特性是 shipped / scaffolded / researched / deprecated"的权威状态。

简短摘要（截至 2026-05-07）：

| 模块 | 状态 |
|---|---|
| 启发式自动调参 | ✅ shipped — `fit_material.py --optimizer heuristic` |
| CMA-ES (cold / warm) | ✅ shipped — `--optimizer cma_cold/cma_warm` |
| `.lmat` 严格写入 + 自动备份 | ✅ shipped |
| Laya refresh 探针 (E-007) | ✅ shipped — `--laya-refresh-check` 或 UI 按钮 |
| Laya 窗口自动聚焦 (E-008) | ✅ shipped — `--laya-window-process/title` |
| 自动背景 mask + 通道加权 MAE + SSIM (E-009) | ✅ shipped |
| 跨引擎背景色统一 (E-011) | ✅ shipped |
| CMA-ES hint-bias 注入 (E-010) | ✅ shipped |
| 截图池滚动上限 (E-012) | ✅ shipped |
| LLM 辅助参数映射 / 调参 | ❌ 未接 |
| 可微分渲染 baseline | ❌ 未接（调研完成） |

---

## 怎么跑

### 推荐：UI + 一键启动

详见 [`../material_fit_ui/README.md`](../material_fit_ui/README.md)。最简形式：

```powershell
# 在 tools/ 的父目录（repo 根）执行
python tools/material_fit_ui/launch.py
```

或在 Windows 双击 `tools/material_fit_ui/launch.bat`。

### 备选：CLI 直跑

在 repo 根目录：

```powershell
python -m tools.material_fit.fit_material `
    --config tools/material_fit/output/<your_project>/fit_config.json `
    --auto-adjust `
    --iterations 30 `
    --target-score 0.5 `
    --apply-lmat `
    --capture-screen-after-apply `
    --laya-refresh-check `
    --optimizer cma_warm `
    --fit-score-mode perceptual
```

> **路径解析**：`fit_config.json` 里的相对路径会被解析成"配置文件位置往上 2 层"的相对路径（`config_path.resolve().parents[2]`）。UI 派生出的 fit_config 全部用绝对路径，所以这条规则不会咬到你；自己手写 fit_config 时直接给绝对路径最稳。

### 单独跑某个子工具

桌面区域截图：

```powershell
python -m tools.material_fit.vision.screen_capture --reuse-last
```

单次图像差异分析（用 E-009 的新评分体系）：

```powershell
python -m tools.material_fit.vision.analyze_diff `
    --reference path/to/unity.png `
    --candidate path/to/laya.png `
    --output-dir tools/material_fit/output/diff_debug
```

---

## 输入：用户需要提供什么

- **Unity Shader 文件**（`.shader`）—— 仅做参数表抽取参考，可选
- **Unity 材质实例参数 JSON** —— 用 `unity/unity_material_exporter.cs` 在 Unity Editor 里导出，包含真实 Float / Color / Vector / Texture / Keyword
- **Unity 渲染参考图**（`.png`）—— Unity 里把效果调好后截一张，作为"目标长这样"的 ground truth
- **Laya Shader 文件**（`.shader`）—— Laya 自定义 Shader，工具读它的 uniformMap / defines
- **Laya 目标材质**（`.lmat`）—— ⚠️ **工具会写这个文件**。每轮迭代前先 `.bak` 备份，写入后用 `lmat_io` 严格校验回读。这就是"工具改写的对象"。
- **Laya 截图区域**（屏幕坐标 `x,y,width,height`）—— UI 里有交互式框选；CLI 用 `--screen-capture-region` 或 `--reuse-last`

工具产物：

- 每轮 `auto_adjust/iter_NNNN/decision.json` —— 本轮选了哪个 stage / optimizer、改了哪些参数、改前改后值、本轮 fit_score / weighted_MAE / SSIM、是否聚焦成功、本轮截图路径
- `auto_adjust/auto_adjust_result.json` —— 整次调参的总结（最佳分数、最佳参数）
- 每轮 `auto_adjust/iter_NNNN/candidate/` —— 候选 .lmat 与 params.json
- `iter_NNNN/image_analysis/diff_analysis.json` + `diff_visual.png` —— 本轮图像分析结果

---

## 测试

```powershell
python -m pytest tools/material_fit/tests/ -q
```

当前 152 个用例，全过。

要 smoke 跑一遍真闭环（需要 Laya 编辑器开着）：参考 [`docs/ExperimentLog.md`](docs/ExperimentLog.md) §2 "待办"里的 P0-4 步骤。

---

## 后续路线

详见 [`docs/ExperimentLog.md`](docs/ExperimentLog.md) §2 "待办"。要把工具往学术 / 论文方向推，看 [`docs/CrossEngineMaterialFit_Research.md`](docs/CrossEngineMaterialFit_Research.md) §6 "创新点提炼"。
