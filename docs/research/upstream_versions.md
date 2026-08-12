# 上游版本与来源清单

记录日期：2026-07-22。状态分为“实测”“源码审查但缺运行时”“候选未安装”。版本 pin 是阶段 -1 的可复现基线，不自动等于最终发布版本。

| 项目 | 版本 / commit | 状态 | License | 官方来源 | 实际用途 | 修改上游代码 |
|---|---|---|---|---|---|---|
| SU2 | 8.5.0 / `12eb826f049ef7f67df974dfcb44cf36ee07c0f8` | 已实测：官方 Windows x64 OpenMP asset `SU2-v8.5.0-win64-omp.zip`，SHA-256 `4466FE21AEDB5E0BAD57AFD45F829ACBDEC6EC79FE8C3F8954DDEA06A4B4BC11`；QuickStart 与 INC_RANS/SST 均退出 0 | LGPL-2.1 | https://github.com/su2code/SU2 | 标准 CFD、INC_RANS/SST、history/ParaView 输出 | 否 |
| Gmsh | 4.15.2 / `657c8e915f60405e6cad0c8ec7faf812bfff1a60` | Python wheel 与官方示例实测 | GPL-2.0-or-later + linking exception | https://gitlab.onelab.info/gmsh/gmsh | STEP/OCC、布尔、尺寸场、网格 | 否 |
| meshio | 5.3.5 | 实测 | MIT | https://github.com/nschloe/meshio | Gmsh→VTU；其他格式须单独门禁 | 否 |
| PyVista | 0.48.4 | 实测 | MIT | https://github.com/pyvista/pyvista | VTK 高层可视化、流线、截图 | 否 |
| VTK | 9.6.2 | 实测 | BSD-3-Clause | https://gitlab.kitware.com/vtk/vtk | 可视化与数据过滤内核 | 否 |
| PyVistaQt | 0.12.0 | 实测 | MIT | https://github.com/pyvista/pyvistaqt | QtInteractor 嵌入 | 否 |
| PySide6 / Shiboken6 | 6.11.1 | 实测 | wheel：`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`；Qt 商业许可另行取得 | https://doc.qt.io/qtforpython-6/ | 中文桌面 GUI、QProcess、线程/信号 | 否 |
| pandas | 3.0.3 | 导入实测 | BSD-3-Clause | https://github.com/pandas-dev/pandas | history CSV 和表格 | 否 |
| Matplotlib | 3.11.1 | 导入实测 | PSF-based | https://github.com/matplotlib/matplotlib | 收敛与结果图 | 否 |
| Jinja2 | 3.1.6 | 导入实测 | BSD-3-Clause | https://github.com/pallets/jinja | HTML 报告模板 | 否 |
| pytest | 9.1.1 | 测试实测 | MIT | https://github.com/pytest-dev/pytest | 单元/集成测试 | 否 |
| build | 1.5.0 | 打包实测 | MIT | https://github.com/pypa/build | wheel/sdist 构建验证 | 否 |
| Ruff | 0.16.1 | 静态检查实测 | MIT | https://github.com/astral-sh/ruff | 开发与 CI 代码检查 | 否 |
| mypy | 2.3.0 | 核心模块实测 | MIT | https://github.com/python/mypy | 科学核心模块类型检查 | 否 |
| Bandit | 1.9.4 | 安全检查实测 | Apache-2.0 | https://github.com/PyCQA/bandit | 高危 Python 安全扫描 | 否 |
| pip-audit | 2.10.1 | 依赖审计实测 | Apache-2.0 | https://github.com/pypa/pip-audit | 已发布 Python 依赖漏洞审计 | 否 |
| Playwright for Python | 1.62.0 | 已安装待端到端验收 | Apache-2.0 | https://github.com/microsoft/playwright-python | 无头浏览器验收 | 否 |
| psutil | 7.2.2 | 导入实测 | BSD-3-Clause | https://github.com/giampaolo/psutil | CPU、内存和进程诊断 | 否 |
| packaging | 26.2 | 导入实测 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging | 版本与 specifier 校验 | 否 |
| OpenVSP / VSPAERO | 3.50.5 | 候选未安装 | NASA Open Source Agreement 1.3 | https://github.com/OpenVSP/OpenVSP | 快速无黏趋势/交叉检查，不代替 RANS | 否 |
| PyInstaller | 6.21.0 | 候选未安装 | GPL-2.0 + bundling exception；部分 Apache-2.0 | https://pyinstaller.org/en/stable/ | Windows 打包候选 | 否 |

## 版本与许可证门禁

1. Gmsh 的闭源集成/再分发必须在发布前完成许可证评估，必要时取得商业许可。
2. PySide6 发布物必须满足 LGPLv3 或商业许可条件，并携带实际使用组件的 notices。
3. SU2 本机验证证据位于 `artifacts/upstream_validation/su2_install/`、`su2_quickstart/` 与 `su2_inc_rans_sst/`；其本机绝对路径配置仅存于被 Git 忽略的 `config/local_tools.json`，不得进入发布清单。
4. OpenVSP/VSPAERO 未安装、未运行，不能出现在第一版“已验证内核”声明中。
5. meshio 5.3.5 的 SU2 writer 已在本机触发 `CellBlock` 解包错误；只能把 Gmsh→VTU 标为已验证。
6. Python 的完整传递依赖版本记录在 `artifacts/upstream_validation/pip-freeze.txt`；各 wheel 发布的 license metadata 记录在 `artifacts/upstream_validation/environment_python_packages/stdout.txt`。
# 2026-08-01 Local Web runtime additions

The following versions were installed and tested for the loopback-only Web MVP. No upstream source was modified.

### Browser visualization experiment (2026-08-02)

| Project | Version tested | License | Official source | Result |
|---|---:|---|---|---|
| Trame | 3.13.2 | Apache-2.0 | https://github.com/Kitware/trame | Installed for PyVista HTML export experiment |
| trame-vtk | 2.11.8 | Apache-2.0 | https://github.com/Kitware/trame-vtk | PASS with PyVista 0.48.4; selected because PyVista requires `<2.11.9` |
| trame-vuetify | 3.2.5 | MIT | https://github.com/Kitware/trame-vuetify | Installed for supported Trame UI/runtime stack |
| nest-asyncio2 | 1.7.2 | BSD-2-Clause | https://github.com/erdewit/nest_asyncio | Required by PyVista's synchronous `export_html()` launch path |
| VTK.js | 36.1.1 reviewed | BSD-3-Clause | https://github.com/Kitware/vtk-js | Reviewed, not installed or vendored |

Experiment input: a real SU2 `surface_flow.vtu` (44,260 B; 356 points; 708 cells). Output: standalone interactive HTML (1,056,054 B) generated in 0.391 s. Upstream source was not modified.

| Project | Version | License | Official source | Actual use |
|---|---:|---|---|---|
| FastAPI | 0.141.1 | MIT | https://github.com/fastapi/fastapi | Local API and HTML application |
| Uvicorn | 0.52.0 | BSD-3-Clause | https://github.com/Kludex/uvicorn | ASGI server bound to `127.0.0.1` |
| python-multipart | 0.0.32 | Apache-2.0 | https://github.com/Kludex/python-multipart | STEP upload form parsing |
| Starlette | 1.3.1 | BSD-3-Clause | https://github.com/Kludex/starlette | FastAPI runtime dependency |
| Pydantic | 2.13.4 | MIT | https://github.com/pydantic/pydantic | Request and persisted-state validation |
| HTTPX | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx | Integration tests only |
