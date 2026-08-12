# 🚀 Phoenix Aero Lite

[![CI](https://github.com/IAMFanxy13/Phoenix-Aero-Lite/actions/workflows/ci.yml/badge.svg)](https://github.com/IAMFanxy13/Phoenix-Aero-Lite/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![SU2 8.5](https://img.shields.io/badge/SU2-8.5-00599C)](https://github.com/su2code/SU2)
[![License GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Status Alpha](https://img.shields.io/badge/Status-Alpha-orange.svg)](docs/validation/limitations.md)

**面向固定翼飞行器的 Windows 本地 CFD 工作台。**

导入 STEP，点选主翼，生成外流场网格，调用 SU2 求解，在网页查看真实压力、Y+、速度截面和流线。

🌐 [English](README.en.md) · 📘 [快速开始](docs/QUICK_START.md) · 🧭 [用户指南](docs/USER_GUIDE.md) · 🧪 [科学方法](docs/SCIENTIFIC_METHOD.md) · ⚠️ [已知限制](docs/validation/limitations.md)

> [!WARNING]
> 当前为 **Alpha**，适合几何检查、CFD 流程学习、排错和初步趋势比较。“计算完成”不等于“数值收敛”，更不等于“已经试验验证”。请勿直接用于适航、飞行安全或结构定型结论。

## ✨ 你能做什么

- 📦 导入 `.step` / `.stp`，通过 Gmsh OpenCASCADE 检查几何，不修改原始文件。
- 👆 在真实三维表面点选左右主翼，重算 `S_ref`、`c_ref` 和翼展，保留人工覆盖记录。
- 🧱 生成三维外流场网格，记录物理组、网格质量、近壁层设计与风险。
- 🌬️ 使用官方 `SU2_CFD.exe`外部求解，支持进度、取消、日志、任务历史和一次保守重算。
- 🎨 互动查看 Cp/静压力、求解后壁面 Y+、可移动速度截面和体流场流线。
- 🛡️ 分开判定进程执行、数值收敛、网格可信度、验证等级和结果使用权限。

## 💻 界面预览

| 主翼表面真实点选 | 求解后壁面 Y+ |
|---|---|
| ![主翼点选](artifacts/e2e/public_workbench_surface_selected.png) | ![壁面 Y+](artifacts/e2e/public_workbench_y_plus.png) |

> 截图使用公开合成模型和可重现测试数组，用于验证三维交互、点选和科学权限门槛，不是飞行器气动正确性证明。

## ♻️ Reuse First：不重复发明成熟工具

| 能力 | 复用的成熟项目 |
|---|---|
| STEP 导入、CAD 布尔运算、网格 | [Gmsh](https://gmsh.info/) + OpenCASCADE |
| RANS/SST 求解 | [SU2](https://su2code.github.io/) |
| Gmsh/SU2/VTK 数据转换 | [meshio](https://github.com/nschloe/meshio) |
| 三维结果、截面、流线 | [PyVista](https://pyvista.org/) + VTK + Trame |
| 本地网页和任务 API | [FastAPI](https://fastapi.tiangolo.com/) |

项目主要实现参数封装、流程调度、可信度判定、中文交互和报告，不自研 CFD 求解器、STEP 解析器、网格算法或渲染引擎。详见 [开源复用审计](docs/research/open_source_reuse_audit.md)。

## ⚡ 快速开始（Windows）

### 1. 准备环境

- Python `3.12`
- 官方 SU2 `8.5.0` Windows x64 OpenMP
- Git

```powershell
git clone https://github.com/IAMFanxy13/Phoenix-Aero-Lite.git
cd Phoenix-Aero-Lite
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### 2. 配置 SU2

复制本地工具配置格式，把官方 `SU2_CFD.exe` 绝对路径写入被 Git 忽略的 `config/local_tools.json`。具体字段和安装要求见 [Windows 安装说明](docs/user/windows_installation.md)。

### 3. 双击启动

```text
Start_Phoenix_Aero_Lite.cmd
```

启动器会检查 Python、Gmsh、PyVista、SU2 和端口，然后只在 `127.0.0.1` 启动本地服务并打开浏览器。

## 🧪 科学证据

- ✅ 官方 SU2 NACA0012 SST 粗/中/细三套网格已独立运行并收敛。
- ✅ 细网格数值结果：`CL = 1.083985`，`CD = 0.0130319`。
- 📊 细网格 GCI：`CL 0.128%`，`CD 1.772%`，`L/D 9.412%`。
- ⚠️ 这些属于 **L3 数值网格验证**，不是与风洞/飞行试验的完整物理验证，也不能证明任意三维飞机结果正确。

详见 [基准矩阵](docs/validation/benchmark-matrix.md)、[数值验证](docs/validation/numerical-verification.md) 和 [可重现性](docs/REPRODUCIBILITY.md)。

## 🛡️ 数据与安全

- CAD、网格和求解结果默认仅在本机保存。
- FastAPI 默认只绑定 `127.0.0.1`，不支持直接暴露到公网。
- 请勿在公开 Issue 中附加私有 CAD、本机配置或未脱敏任务目录。

📖 [隐私与数据](docs/PRIVACY_AND_DATA.md) · 🔐 [安全策略](SECURITY.md) · 🤝 [贡献指南](CONTRIBUTING.md)

## 🗂️ 项目状态

- 版本：`0.1.0.dev0`
- 阶段：Alpha
- 许可证：`GPL-3.0-or-later`
- 平台：Windows 10/11，Python 3.12
- 维护者：Xinyu Fan

第三方组件保留各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [依赖许可矩阵](docs/legal/dependency-license-matrix.md)。
