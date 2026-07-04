# Material Fit Inspector

Material Fit Inspector 是一个跨引擎材质对齐工具。它把 Unity 里已经调好的参考效果作为目标，通过反复改写 Laya `.lmat`、触发同视角渲染截图、比较图像差异，再由黑盒优化器继续提出下一组参数。

这个仓库当前是 standalone 形态，根目录就是项目根。历史代码里仍有 `tools.material_fit.*` / `tools.material_fit_ui.*` import，仓库内的 `tools/__init__.py` 会把这些旧 namespace 映射到当前根目录下的 `material_fit/` 和 `material_fit_ui/`，所以不要删除 `tools/` 这个兼容包。

## 当前结构

```text
.
├── README.md                         # 本入口文档
├── tools/                            # 兼容旧 tools.* import 的 namespace shim
├── material_fit/                     # 算法、CLI、Laya/Unity 适配、视觉评分、测试和文档
│   ├── fit_material.py               # 自动调参主入口，必须通过 python -m tools.material_fit.fit_material 调用
│   ├── auto_adjust/                  # 自动调参循环、历史样本、评分状态
│   ├── optimizer/                    # heuristic / CMA-ES / semantic group / hybrid optimizer
│   ├── laya/                         # .lmat 读写、Laya shader 解析、旧渲染驱动兼容层
│   ├── laya_capture/                 # Laya Editor 截图桥接、runtime capture bridge
│   ├── unity/                        # Unity shader/material 导出辅助
│   ├── vision/                       # 图像 diff、mask、感知评分、人类接受度评分
│   ├── tests/                        # pytest 回归测试
│   └── docs/                         # 架构、评分、优化器、Laya 截图和研究设计文档
└── material_fit_ui/                  # 本地 Web 控制台，FastAPI backend + Vue/Vite frontend
    ├── launch.py                     # 一键启动后端和前端
    ├── requirements.txt              # Python 依赖
    ├── backend/                      # 项目管理、预分析、探针、job runner、API
    └── frontend/                     # Vue 3 + TypeScript UI
```

## 什么会进 Git

应该提交的是源码、测试、配置模板和文档：

```text
tools/
material_fit/
material_fit_ui/
README.md
.gitignore
```

不要提交本地运行载荷、缓存和实验产物：

```text
artifacts/
LayaAirIDE-*/
laya_project_minimal/
unity_references/
material_fit/output/
material_fit_ui/frontend/node_modules/
material_fit_ui/frontend/dist/
__pycache__/
.pytest_cache/
.codex/
.agents/
```

这些目录要么能重新安装/生成，要么包含本机绝对路径、Laya/Unity 资产、截图、日志或大体积运行结果。`.gitignore` 已经覆盖这些路径。

## 环境准备

基础开发和测试需要：

- Python 3.10+
- Node.js 18+ 和 npm，仅在启动前端 UI 时需要
- pytest，用于跑测试
- `material_fit_ui/requirements.txt` 中的 Python 依赖，用于 UI 后端、CMA-ES、图像评分和感知指标

安装 Python 依赖：

```powershell
python -m pip install -r material_fit_ui/requirements.txt
python -m pip install pytest
```

启动 UI 时，`material_fit_ui/launch.py` 会在缺少 `node_modules/` 时自动执行一次 `npm install`。如果要手动安装前端依赖：

```powershell
cd material_fit_ui/frontend
npm install
```

## 启动 UI

在仓库根目录执行：

```powershell
python material_fit_ui/launch.py
```

常用参数：

```powershell
python material_fit_ui/launch.py --no-browser
python material_fit_ui/launch.py --backend-only
python material_fit_ui/launch.py --frontend-only
```

Windows 上也可以双击：

```text
material_fit_ui/launch.bat
```

UI 负责项目配置、预分析、Laya 刷新探针、启动/取消优化 job、查看每轮截图和评分。真正的优化逻辑仍在 `material_fit/` 中。

## 运行 CLI

不要直接执行 `python material_fit/fit_material.py`，这个文件内部使用 package relative import，直接跑会失败。应从仓库根目录通过兼容 namespace 调用：

```powershell
python -m tools.material_fit.fit_material --help
```

典型自动调参命令：

```powershell
python -m tools.material_fit.fit_material `
  --config material_fit/output/<project_id>/runs/<run_id>/fit_config.json `
  --auto-adjust `
  --iterations 100 `
  --target-score 0.98 `
  --optimizer semantic_group `
  --fit-score-mode human_accept `
  --apply-lmat
```

真实闭环运行还需要用户提供有效的 Laya/Unity 资产路径，通常包括：

- Unity 参考图，作为目标图像。
- Laya shader 和目标 `.lmat`。
- Laya 项目路径和 Laya Editor 截图命令文件。
- 可选的 Unity shader/material 参数导出文件。

`material_fit/fit_config.example.json` 是配置形状示例，不是可直接运行的配置。里面的路径需要替换成本机真实路径。

## 测试

在仓库根目录执行：

```powershell
python -m pytest material_fit/tests -q
```

测试覆盖 `.lmat` 读写、评分、优化器、UI 后端项目存储、Laya capture bridge 和若干 legacy 兼容路径。测试会产生 `__pycache__/` 和 `.pytest_cache/`，这些缓存不应提交。

## 关键文档

- `material_fit/docs/README.md`：文档索引和当前代码入口。
- `material_fit/docs/Project_Architecture.md`：项目结构、数据流、源码/产物清理边界。
- `material_fit/docs/File_Layout_And_Artifacts.md`：运行产物和文件布局约定。
- `material_fit/docs/Laya_Multiview_Capture.md`：Laya 多视角截图链路。
- `material_fit/docs/Core_Algorithms_and_Metrics.md`：核心算法和指标。
- `material_fit/docs/Scoring_Mechanism_Design.md`：评分机制设计。
- `material_fit/docs/learned_incremental_optimizer_design.html`：学习型增量优化器的理论设计稿。

部分深层历史文档仍可能使用 `tools/material_fit` 这种旧路径写法。当前 standalone 仓库以本 README 的目录边界和命令为准。

## 开发注意事项

- 算法主循环在 `material_fit/fit_material.py`。
- 搜索策略集中在 `material_fit/optimizer/`。
- 图像评分集中在 `material_fit/vision/`。
- Laya `.lmat` 安全写入在 `material_fit/laya/lmat_io.py`。
- Laya Editor 截图桥接在 `material_fit/laya_capture/`。
- UI job 生命周期在 `material_fit_ui/backend/job_manager.py`。
- UI 项目状态在 `material_fit_ui/backend/project_store.py`。

项目目标是优化“最终渲染表现”的相似度，不是恢复唯一正确的材质参数。当前主线仍是黑盒优化系统，没有训练一个端到端模型；学习型优化器设计目前作为研究方案和后续路线保留在文档中。
