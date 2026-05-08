# Agent Onboarding — Material Fit Inspector

> 你（新接手的 LLM agent）来到这个仓库，请**先读这一篇**，再去翻 `README.md` / `docs/` 等其他文档。
>
> 这一篇的目的：让你 **5 分钟内** 知道工具是什么、当前状态、不要被早期文档误导，然后挑对该读哪份文档继续。

---

## 1. 这是什么工具

**Material Fit Inspector** 是一个把 Unity 游戏里的某个材质效果，自动迁移到 LayaAir 项目里对应 `.lmat` 材质上的工具。

工作流：

1. 用户在 Unity 里**手动**调好一个角色 / 鱼 / 炮台等的材质效果，并把它当前的真实参数（不是 Shader 默认值）和渲染图导出来。
2. 用户在 Laya 项目里**手动**指定一个目标 `.lmat`（要被改的那个材质）。
3. 工具反复改写 Laya `.lmat` → 等 Laya 编辑器重渲染 → 截屏 → 跟 Unity 参考图比对打分 → 决定下一组参数 → 写回 `.lmat`，直到分数收敛或达到迭代上限。
4. UI（Vue + FastAPI）让用户能在浏览器里建项目、跑探针、点开始、实时看每轮迭代细节。

**重要**：工具**不**自动剖析 Unity Shader 等价转写为 Laya Shader。它把这件事当作黑盒优化——给定一组 Laya `.lmat` 参数 → 让 Laya 渲染 → 看像不像 Unity 参考图——纯粹靠"反复调到像"。

---

## 2. 工具的两层结构

```text
material_fit/         <-- 算法 / CLI / 文档
material_fit_ui/      <-- FastAPI 后端 + Vue 前端 + 一键启动器
```

两个目录是**独立的**：

- `material_fit/` 自己就是一个完整的 CLI 工具，可以脱离 UI 直接 `python -m tools.material_fit.fit_material --config xxx.json` 跑。
- `material_fit_ui/` 套在 `material_fit/` 外面，给人类用浏览器操作的能力。后端 import `tools.material_fit.*` 是**单向依赖**，反过来 `material_fit/` **不**依赖 UI 任何代码。

> ⚠️ **包路径硬约束**：所有源码内部都用 `from tools.material_fit.X import Y` / `from tools.material_fit_ui.Y import Z`。这意味着把这个工具复制到新仓库时，**必须保留 `tools/` 这个父目录**，不能把 `material_fit/` 直接放到新仓库根。详见下文 §6"独立部署"。

---

## 3. 当前能力状态 — 直接看 ExperimentLog §0

工具的**所有关键能力**和**版本状态**都在 [`docs/ExperimentLog.md`](docs/ExperimentLog.md) 的 **§0 头部表**里维护。规则是：

- ✅ shipped — 用户点"开始"立刻能用
- 🟡 scaffolded — 代码 + 测试都做了，没接到主流程
- 🔵 researched — 只有调研文档
- ⚫ deprecated — 试过了不用了

**做任何决策前先看 §0**。如果用户问"现在 X 能用吗"，§0 是权威答案；不要靠你自己的猜测，也不要相信比 §0 早的文档。

迄今的实验编号：E-001 ... E-012，每条都在 [`docs/ExperimentLog.md`](docs/ExperimentLog.md) §3 有详细记录（背景、方案、测试、副作用）。

---

## 4. 历史文档的"信用等级"

新接手 agent 最容易被坑的地方：**早期设计文档** 写于工具刚启动时，描述的是"我们打算做什么"，并不代表当前实现。如果你看到一份文档说"工具会做 X"，先去 ExperimentLog 验证 X 真的 ship 了没。

按可信度从高到低：

| 文档 | 信用 | 说明 |
|---|---|---|
| [`docs/ExperimentLog.md`](docs/ExperimentLog.md) | 🟢 当前 | §0 是工具状态权威表，§3 是每个实验的详细记录 |
| [`docs/Metric_Validation.md`](docs/Metric_Validation.md) | 🟢 当前 | E-009 评分体系的科学论证 |
| [`docs/Experiment_Phase1_CMA_ES_WarmStart.md`](docs/Experiment_Phase1_CMA_ES_WarmStart.md) | 🟢 当前 | E-006 CMA-ES warm-start 合成 benchmark 报告 |
| [`docs/RelatedWork_Survey.md`](docs/RelatedWork_Survey.md) | 🟢 当前 | 学术 Related Work 调研 |
| [`docs/CrossEngineMaterialFit_Research.md`](docs/CrossEngineMaterialFit_Research.md) | 🟢 当前 | 学术问题形式化、创新点提炼 |
| `README.md`（本目录） | 🟢 当前 | 工具结构入口 |
| [`docs/MaterialAutoFitTool.md`](docs/MaterialAutoFitTool.md) | 🟡 历史 | 工具方案最初设计文档；保留作背景，**不**反映当前实现 |
| [`IntegrationDifficulties.md`](IntegrationDifficulties.md) | 🟡 历史 | 早期"四个关键难点"分析；E-001..E-012 已经覆盖了大部分内容，留作背景 |
| [`LLMContextPrompt.md`](LLMContextPrompt.md) | 🟡 历史 | 给 LLM 的早期 context prompt；LLM 辅助还没接入主流程 |

如果三类文档之间有冲突（比如 README 说 X，老文档说 Y），**以 ExperimentLog §0 + §3 为准**。

---

## 5. 怎么跑工具

### 一键启动

在 repo 根目录（`tools/` 的父目录）执行：

```powershell
python tools/material_fit_ui/launch.py
```

或在 Windows 资源管理器双击 `tools/material_fit_ui/launch.bat`。详见 [`material_fit_ui/README.md`](../material_fit_ui/README.md) "一键启动（推荐）" 小节。

### CLI 直跑（不用 UI）

在 repo 根目录：

```powershell
python -m tools.material_fit.fit_material --config <your-fit-config.json> --auto-adjust --iterations 30 --apply-lmat --capture-screen-after-apply --laya-refresh-check
```

工具默认会从 `<your-fit-config.json>` 里读 `laya_material_path` 等绝对路径并实际写回。新手**强烈建议**在第一次跑之前先在 UI 里跑一次"验证 Laya 是否真的在刷新"探针（详见 ExperimentLog §3 E-007/E-008）。

---

## 6. 独立部署 / 把工具搬到新仓库

工具**完全可以独立**：除了用户运行时通过 `project.json` / CLI 提供的"用户的 .lmat 路径""用户的 Unity 参考图路径""用户的 Laya 编辑器窗口标题"等绝对路径外，工具本身不引用任何外部仓库的代码或路径。

### 必须保留的目录结构

```text
<新仓库根>/
└── tools/                       <-- 必须保留这一层！
    ├── material_fit/
    │   ├── fit_material.py      <-- CLI 入口
    │   ├── README.md
    │   ├── AGENT_ONBOARDING.md  <-- 你正在读的这份
    │   ├── docs/
    │   ├── laya/
    │   ├── unity/
    │   ├── vision/
    │   ├── optimizer/
    │   ├── shared/
    │   ├── tests/
    │   ├── experiments/
    │   └── output/              <-- 项目运行时数据；可选随迁
    └── material_fit_ui/
        ├── launch.py            <-- 一键启动器
        ├── launch.bat           <-- Windows 双击包装
        ├── requirements.txt
        ├── README.md
        ├── backend/
        └── frontend/
```

`tools/` 下不需要其它任何东西。

### 复制清单（对人类）

1. 完整复制整个 `tools/material_fit/` 目录。
2. 完整复制整个 `tools/material_fit_ui/` 目录（**注意**：`tools/material_fit_ui/frontend/node_modules/` 体积大且会自动重装，**可不复制**；启动器第一次跑 `npm install` 自动恢复）。
3. 在新仓库根（必须是 `tools/` 的父目录）新建 / 拷贝任意你想要的顶层 `README.md` / `.gitignore`。

### 用户的 Laya `.lmat` 怎么找到工具？

不用工具找用户。**用户在 UI 里建项目时通过文件管理器选中 `.lmat`，路径以绝对路径存进 `project.json`**。即使工具搬到 `D:/standalone/material_fit_inspector/`，用户的 `.lmat` 仍然是 `D:/path/to/your/laya_project/assets/.../something.lmat`，工具用绝对路径直接读写，不需要任何相对位置假设。

举例：

- 工具新位置：`D:/work/material_fit_standalone/tools/material_fit/`
- 用户 Laya `.lmat`：`D:/games/my_laya_proj/assets/play/fish/1580/mat/1580_body.lmat`
- `project.json` 里 `inputs.laya_material_lmat_path` 直接存第二个绝对路径

→ 工具完全能正常读写 `.lmat`，无关 Laya 项目位置。

### 唯一与"用户机器"耦合的点

- **Laya 编辑器进程名**：`vision/screen_capture.py` 默认 `process_pattern = "LayaAirIDE"`。这是 LayaAir IDE 在 Windows 上的进程名，跨用户可移植。如果用户 Laya IDE 是别的版本（Mac、Linux、自定义命名），用户在 UI 里改"Laya 窗口聚焦"区域的 `process_pattern` / `title_pattern`。
- **Laya 编辑器窗口标题**：用户在 UI 里给（比如 `effect`、`fish`），存进 `project.json`，运行时 Win32 `EnumWindows` 匹配。

工具自身**不**假设 Laya 编辑器 / Laya 项目装在哪里。

---

## 7. 现存"用户运行历史"目录的处理

`tools/material_fit/output/` 下面有用户实际跑过的项目数据（每个项目一个子目录）。这些数据：

- **属于用户**，不属于工具代码。
- 复制工具到新仓库时**可以一起搬**，也**可以**清空（用户重新建项目即可）。
- 路径里有用户机器的绝对路径（比如 Laya `.lmat` 路径）。**搬到别的机器时**这些路径会失效——但工具会在第一次跑时清楚报错"`.lmat not found at xxx`"，用户在 UI 里重新选一遍即可。

---

## 8. 一些反直觉的点 / 常见踩坑

1. **fit_score 不再是 1 - RGB MAE**。E-009 之后默认是 `perceptual_fit_score = 0.7·(1 - sqrt(weighted_MAE·4)) + 0.3·SSIM`，且只统计自动 mask 出来的前景区域。详见 [`docs/Metric_Validation.md`](docs/Metric_Validation.md)。如果你看到老文档说 fit_score = 1 - MAE，**那是错的**。
2. **CMA-ES 默认迭代是 30 轮，启发式是 6 轮**。`job_manager` 按 optimizer 选默认（E-010）。
3. **CMA-ES 不参与 4-step abort 机制**。`OptimizerStrategy.wants_global_no_improve_check()` 让 CMA-ES 跑满预算（E-010）。
4. **截图池有滚动上限**。`tools/material_fit/vision/test_image/laya_candidate_NN.png` 默认只保留 30 张，老的会被剪掉（E-012）。回看 30 轮以前的 iter 截图就没了。
5. **Laya 编辑器失焦时不渲染**。E-007/E-008 在每次 .lmat 写入和截图之前都会 `SetForegroundWindow`。但 Windows 安全策略**有时**会拒绝；不通过的话 UI 探针会清楚显示"Laya is NOT refreshing"。
6. **背景色统一**。E-011 在比较前会自动把 Unity / Laya 两张图的纯色背景替换成统一中性灰，避免轮廓抗锯齿伪影掉分。

---

## 9. 该读的下一份文档

- 想跑起来：[`material_fit_ui/README.md`](../material_fit_ui/README.md)
- 想看代码组织：本目录 `README.md`
- 想看现在的算法 / 评分细节：[`docs/ExperimentLog.md`](docs/ExperimentLog.md)（必读）+ [`docs/Metric_Validation.md`](docs/Metric_Validation.md)
- 想看学术定位 / 创新点 / 论文方向：[`docs/CrossEngineMaterialFit_Research.md`](docs/CrossEngineMaterialFit_Research.md) + [`docs/RelatedWork_Survey.md`](docs/RelatedWork_Survey.md)
- 想知道下一步该做什么：[`docs/ExperimentLog.md`](docs/ExperimentLog.md) §2 "待办"

祝你接手顺利。
