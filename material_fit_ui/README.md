# Material Fit Inspector — UI

`tools/material_fit_ui/` 是 `tools/material_fit/` 的浏览器交互层（FastAPI 后端 + Vue 3 前端）。

工具完整能力分布：

- **`tools/material_fit/`**：算法、CLI、`.lmat` 读写、Laya 窗口控制、图像评分。**第一次接触这套工具请先读** [`../material_fit/AGENT_ONBOARDING.md`](../material_fit/AGENT_ONBOARDING.md)。
- **`tools/material_fit_ui/`**（本目录）：把上面那一坨能力包成浏览器 UI——建项目、改算法配置、跑探针、点开始、实时看每轮迭代细节。

> 本目录原本叫 "Stage A 只读 inspector"。当前实际状态远超 Stage A：UI 已经能驱动后端跑完整 auto-adjust 闭环（启动 / 取消 / 实时日志 / 探针 / 配置 / 算法切换）。具体每一项的状态以 [`../material_fit/docs/ExperimentLog.md`](../material_fit/docs/ExperimentLog.md) §0 的"shipped / scaffolded / researched / deprecated"标签为准。

## 目录结构

```text
tools/material_fit_ui/
├── README.md
├── requirements.txt          # Python 后端依赖
├── launch.py                 # 一键启动器：起后端 + 起前端 + 开浏览器 + Ctrl+C 一起收
├── launch.bat                # Windows 双击包装，转发参数给 launch.py
├── .gitignore
├── backend/                  # FastAPI 后端，包装 tools/material_fit/output 读取
│   ├── __init__.py
│   ├── case_loader.py        # 纯文件系统读取，不依赖 FastAPI
│   └── main.py               # FastAPI 路由与错误映射
└── frontend/                 # Vue 3 + Vite + TS 前端
    ├── package.json
    ├── vite.config.ts        # /api 代理到 127.0.0.1:8000
    ├── tsconfig.json
    ├── tsconfig.node.json
    ├── env.d.ts
    ├── index.html
    └── src/
        ├── main.ts
        ├── App.vue           # 主壳：header/sidebar/main/footer
        ├── api.ts            # fetch 封装
        ├── types.ts          # 后端响应的 TS 类型映射
        ├── styles.css        # 自带的暗色主题，零 UI 库依赖
        └── components/
            ├── CaseSelector.vue
            ├── IterationList.vue
            ├── IterationDetail.vue
            ├── ImageComparison.vue
            ├── ChannelMetricsTable.vue
            ├── ParamChangesTable.vue
            └── ScoreCurve.vue
```

## 安装与启动

### 前置要求

- Python 3.10+
- Node 18+ / npm
- 工作区根目录存在 `tools/material_fit/output/<case>/` 跑过的产物（例如 `fish_1580_smoke`）

### 一键启动（推荐）

在 Windows 上直接 **双击** `tools/material_fit_ui/launch.bat`，或在任意终端里跑：

```powershell
python tools/material_fit_ui/launch.py
```

它会自动：

1. 检查 `uvicorn` / `fastapi` 已 `pip install`，没装就提示一行修复命令；
2. 检查 `frontend/node_modules` 是否存在，没装就替你跑一次 `npm install`；
3. 起 FastAPI 后端（`127.0.0.1:8000`）和 Vite 前端（`localhost:5173`），两路日志交贴到同一个控制台、各自带前缀色；
4. 后端 `/api/health` 通了之后，自动用默认浏览器打开 `http://localhost:5173/`；
5. 按 `Ctrl+C` 一次，干净杀掉两个子进程（含 `npm` 派生的孙进程）。

可选参数（详见 `--help`）：

| 选项 | 用途 |
|---|---|
| `--no-browser` | 不自动开浏览器（CI / 远程开发常用） |
| `--no-reload` | 关掉 uvicorn `--reload`（无 auto-reload，进程更轻） |
| `--no-npm-install` | 即使没 `node_modules` 也不自动 `npm install` |
| `--backend-only` | 只起后端 |
| `--frontend-only` | 只起前端 |
| `--health-timeout 60` | 后端健康检查超时（秒，默认 30） |

> ⚠️ 双击 `.bat` 后，关闭那个控制台窗口 = 关掉两个服务器；Ctrl+C 也是同样效果。

### 手动启动（备用）

如果你想分别看 backend / frontend 的日志，或者一键启动器在你的环境里有问题，可以仍然按老方法分两个终端起：

#### 1) 后端

在 **repo 根目录**（即 `tools/` 的父目录）执行：

```powershell
pip install -r tools/material_fit_ui/requirements.txt
python -m uvicorn tools.material_fit_ui.backend.main:app --reload --port 8000
```

> 用 `python -m uvicorn ...` 而不是裸 `uvicorn`，避免 `uvicorn.exe` 装在 user site Scripts 但未加入 PATH 的常见问题。

健康检查：

```powershell
curl http://127.0.0.1:8000/api/health
```

预期返回包含 `"status": "ok"` 和 `"output_dir_exists": true`。

#### 2) 前端

新开终端，进 `tools/material_fit_ui/frontend/`：

```powershell
cd tools/material_fit_ui/frontend
npm install
npm run dev
```

打开浏览器访问 [http://localhost:5173](http://localhost:5173)。Vite 开发服务器会把 `/api/*` 自动代理到 `127.0.0.1:8000`。

### 生产构建（可选）

```powershell
cd tools/material_fit_ui/frontend
npm run build
```

构建产物在 `frontend/dist/`。生产部署时可以用任意静态服务器（或让 FastAPI 直接挂 `StaticFiles`）服务它，目前 Stage A 不做这层。

## 后端 API 契约

所有响应为 JSON，路径都在 `/api/` 前缀下。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务健康，返回 project_root / output_dir |
| GET | `/api/cases` | 列出 `tools/material_fit/output/` 下所有 case |
| GET | `/api/cases/{case_id}/overview` | case 概要：auto_adjust 摘要、stage_plan、policies、shader/material 参数 |
| GET | `/api/cases/{case_id}/iterations` | 迭代时间轴摘要数组（含本轮 fit_score、stage、changes_count） |
| GET | `/api/cases/{case_id}/iterations/{iter_id}` | 单轮详情：decision、diff_analysis、candidate params/lmat、图像 URL |
| GET | `/api/image?path=...` | 安全读取一个图像文件，强制限制在 `tools/material_fit/` 子树内 |

安全策略：

- `case_id` 不允许出现 `/`、`\`、`..`，并强制落在 `output_dir` 之下。
- `/api/image` 只服务 `tools/material_fit/` 子树下的文件，超出会返回 403。

## 前端布局

```text
┌──────────────────────────────────────────────────────────┐
│ Header: 标题 · case 选择 · 刷新 · 顶部统计 pill          │
├──────────────┬───────────────────────────────────────────┤
│ Iter sidebar │  Image: Unity ref · Laya cand · Diff      │
│ (列表)       │  Tabs: 决策与变化 / 通道分析 /            │
│              │        本轮参数 / 候选 .lmat              │
├──────────────┴───────────────────────────────────────────┤
│ ScoreCurve: fit_score 时间轴（点击点跳转选中迭代）       │
└──────────────────────────────────────────────────────────┘
```

## 已经能直接看到的东西

跑一次后端 + 前端，选中 `fish_1580_smoke`：

- 顶部 pill 显示 status / target / best fit / best mae。
- 左侧能看到所有 `auto_adjust/iter_XXXX/`，每行显示选中的 stage、本轮 changes 数、fit_score 着色 badge。
- 中间能看到 Unity reference / Laya candidate / diff_visual 三联对比图。
- "决策与变化" tab：本轮所有参数旧值/新值/Δ/原因表格。
- "通道分析" tab：`material_channels` 各 severity、RGB MAE、luma/sat/contrast bias，按 RGB MAE 倒序。
- "本轮参数" / "候选 .lmat" tab：原始 JSON / 文本可滚动查看。
- 底部 fit_score 折线，target 用黄色虚线标，点击点直接跳转。

## ⚠️ 历史栏目（已被现状覆盖）

> 早期版本 README 里有一段 "不在本阶段做的事" 列表，写着 "不写 `.lmat`、不调 `screen_capture` 重新截图、不嵌 Laya 控制等"。**那已经是 2026-05 之前的目标**——当前 UI 实际已经接管了写 `.lmat` / 调 `screen_capture` / 控制 Laya 窗口聚焦 / 跑探针 / 启停 auto-adjust subprocess 的全部能力。每一项的具体接入时间和实现细节，请到 [`../material_fit/docs/ExperimentLog.md`](../material_fit/docs/ExperimentLog.md) §3 按 E-001 .. E-012 顺序查看。
>
> 仍未接入的两件事：
>
> - LLM 辅助参数语义映射 / 调参（`LlmAssistView.vue` 仅占位）
> - Laya 调试场景嵌 iframe（不在路线图）

## 常见问题

- **`uvicorn` 提示找不到命令**：用 `python -m uvicorn ...` 启动，不要裸用 `uvicorn`。或者直接用 `launch.bat` 就完全不必关心这点。
- **`uvicorn` 提示 module not found**：必须在**项目根目录**运行，不要 `cd` 进 `tools/material_fit_ui/`。`launch.bat` / `launch.py` 已经替你处理。
- **`launch.bat` 双击闪退**：用 PowerShell 在 `tools/material_fit_ui/` 里跑 `.\launch.bat` 看真实错误；最常见是没装 Python 或 PATH 没刷。.bat 末尾有 `pause` 会停住等你按键。
- **`launch.py` 提示找不到 `npm.cmd`**：装 Node.js（[https://nodejs.org/](https://nodejs.org/)），然后**重开**终端让 PATH 生效。
- **`launch.py` 提示后端健康检查超时**：看那个控制台 `[backend]` 前缀的日志，多半是 `pip install -r tools/material_fit_ui/requirements.txt` 没跑过，或者 8000 端口被别的进程占住了。
- **页面空白 / `/api/cases` 404**：检查后端是否真的跑在 8000 端口；Vite 默认代理 `127.0.0.1:8000`。
- **图片 403**：图片路径必须落在 `tools/material_fit/` 子树内；这是后端的硬约束，避免任意文件读取漏洞。
- **Pillow 没装也能看 diff_visual.png**：可视化只读 PNG，不需要 Pillow；Pillow 只在 `tools/material_fit` 算法侧才需要。
