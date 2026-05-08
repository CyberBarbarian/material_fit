# Material Fit Inspector

Unity → Laya 跨引擎材质自动拟合工具。把 Unity 中调好的材质效果，靠"反复改写 Laya `.lmat` + 截图比分"的方式自动迁移到 Laya 项目里。

## 仓库结构

```text
.                          <-- git 仓库根（即 tools/）
├── material_fit/          <-- 算法 / CLI / 文档（核心层）
│   ├── AGENT_ONBOARDING.md   ⭐ 新接手 agent 第一读物（先读这份！）
│   ├── README.md
│   ├── fit_material.py       CLI 入口
│   ├── docs/                 当前文档（ExperimentLog 是权威状态表）
│   ├── laya/  unity/  vision/  optimizer/  shared/
│   └── tests/                152 个 pytest 测试
└── material_fit_ui/       <-- 浏览器 UI（FastAPI + Vue 3 + 一键启动器）
    ├── README.md
    ├── launch.py             一键启动入口
    ├── launch.bat            Windows 双击包装
    ├── backend/  frontend/
    └── requirements.txt
```

## 快速开始

```powershell
# 在仓库根（即 tools/ 这一层）执行
python material_fit_ui/launch.py
```

或在 Windows 资源管理器双击 `material_fit_ui/launch.bat`。

> ⚠️ 注意：源码内部全部用 `from tools.material_fit.X import Y` 风格的 import。**这个仓库根目录必须是 `tools/`（即 `material_fit/` 和 `material_fit_ui/` 共同的父目录），否则 import 会失败**。换句话说，git clone 之后**不要**把 `material_fit*` 移出 `tools/`。
>
> 如果你 clone 到的位置不叫 `tools/`，需要把它改回来，或者在外面套一层名为 `tools/` 的目录把这两个子包包进去。

## 文档导览

- [`material_fit/AGENT_ONBOARDING.md`](material_fit/AGENT_ONBOARDING.md) — 新接手 agent 的第一读物（5 分钟全貌）
- [`material_fit/README.md`](material_fit/README.md) — 算法层结构与 CLI 跑法
- [`material_fit_ui/README.md`](material_fit_ui/README.md) — UI 跑法 + 一键启动 + 故障排查
- [`material_fit/docs/ExperimentLog.md`](material_fit/docs/ExperimentLog.md) — ⭐ 实验日志 + **当前能力状态权威表**（必读）
- [`material_fit/docs/Metric_Validation.md`](material_fit/docs/Metric_Validation.md) — E-009 评分体系科学论证
- [`material_fit/docs/CrossEngineMaterialFit_Research.md`](material_fit/docs/CrossEngineMaterialFit_Research.md) — 学术问题形式化与论文方向
- [`material_fit/docs/RelatedWork_Survey.md`](material_fit/docs/RelatedWork_Survey.md) — 学术 Related Work 调研

## 测试

```powershell
python -m pytest material_fit/tests/ -q
```

应当 152/152 通过。
