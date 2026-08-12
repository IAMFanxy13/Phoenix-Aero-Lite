# Phoenix Aero Lite 开源技术与复用审计

审计日期：2026-07-22（阶段 -1）

## 结论

Phoenix Aero Lite 应是“参数模型 + 上游适配器 + 进程调度 + 中文工作流”的薄层应用，不是新的 CAD、网格、CFD、格式解析或三维渲染实现。标准求解链选用 SU2；CAD/网格选用 Gmsh OpenCASCADE；格式转换选用 meshio；结果显示选用 PyVista/VTK；桌面层选用 PySide6。

阶段 -1 基础链路现已全部通过：Gmsh、meshio、PyVista、Qt 链路已通过；SU2 8.5.0 官方 Windows x64 OpenMP 包也已安装到用户目录，官方 QuickStart 与 INC_RANS/SST 安装后门禁均退出 0。本阶段仍未启动 example_model.STEP、GUI 或计划 Task 1+。

## 功能复用决策

| 功能 | 候选项目 | 最终选择 | 复用方式 | License | 不自研理由 |
|---|---|---|---|---|---|
| CFD 求解 | SU2、OpenFOAM、Fluent、VSPAERO | SU2 8.5.0 | 调用官方 Windows OMP 可执行文件；不链接或修改求解器 | LGPL-2.1 | 已有成熟 Euler/RANS/INC_RANS/SST、回归算例和输出系统 |
| STEP 导入 | Gmsh OCC、pythonOCC、CAD Exchanger | Gmsh 4.15.2 OCC | `gmsh.model.occ.importShapes()`；复用 t20 | GPL-2.0-or-later + linking exception；闭源分发需单独审查 | 官方 OCC API 已解析 STEP，手写格式解析风险极高 |
| CAD 布尔运算 | Gmsh OCC、OpenCASCADE | Gmsh OCC | `cut` / `fragment` / `fuse`；复用官方 boolean 示例 | 同 Gmsh | 上游已处理 B-rep 和拓扑重建 |
| 网格生成 | Gmsh、TetGen、snappyHexMesh | Gmsh | 官方 Python API、size fields、3D 拓扑边界层示例 | 同 Gmsh | 三维网格和质量优化是专门领域，不应重写 |
| 网格转换 | Gmsh export、meshio | meshio 5.3.5，优先 VTU；SU2 写出设版本门禁 | 公共 `read` / `write` API；保留物理组，过滤非单元索引的 OCC 邻接元数据 | MIT | 已支持 Gmsh 2.2/4.x、SU2、VTK/VTU；禁止自写完整解析器 |
| SU2 配置 | SU2 `config_template.cfg`、TestCases、Jinja2 | 官方模板/算例 + 项目参数映射 | 只生成批准字段；保留模板来源 | SU2 LGPL-2.1；Jinja2 BSD-3-Clause | 官方字段语义和算例是事实源，项目只负责参数封装 |
| 求解器启动 | Python subprocess、Qt QProcess | 后端 subprocess + GUI QProcess | 参数数组、工作目录、环境、stdout/stderr、取消和退出码 | Python PSF；Qt LGPLv3/GPLv3/商业 | Windows 进程管理已有可靠标准 API |
| 收敛读取 | SU2 history CSV、pandas | SU2 自定义输出 + pandas | 请求明确 history 字段；增量读 CSV | SU2 LGPL-2.1；pandas BSD-3-Clause | 不解析控制台装饰文本；CSV 是稳定机器接口 |
| 三维可视化 | VTK、PyVista、ParaView | PyVista 0.48.4 / VTK 9.6.2 | `QtInteractor`、slice、clip、contour、screenshot、off-screen | MIT / BSD-3-Clause | 复用成熟 VTK 管线，禁止自建 OpenGL 引擎 |
| 网页三维场景 | PyVista `export_html`、Trame、VTK.js、ParaView Glance | PyVista `export_html` + Trame（首个切片）；VTK.js/常驻 Trame（后续评估） | 服务端从任务内真实 VTU 提取表面/切片/流线并导出独立交互 HTML | MIT / Apache-2.0 / BSD-3-Clause | 复用 VTK 的渲染和数据管线，禁止自研 WebGL 或在浏览器解析 SU2/VTU 全格式 |
| 流线生成 | VTK StreamTracer、PyVista | PyVista | `streamlines_from_source(max_length=...)` | MIT | 上游已有插值和积分器 |
| 图表 | Matplotlib、PyQtGraph | Matplotlib 3.11.1 | 收敛和气动力静态图；GUI 后续可评估 PyQtGraph | PSF-based | 成熟绘图、导出和测试生态 |
| HTML 报告 | Jinja2、pandas styling | Jinja2 3.1.6 | 本地模板、HTML escaping、相对资源或嵌入图片 | BSD-3-Clause | 模板引擎已处理转义和布局复用 |
| GUI | PySide6、PyQt6、wxPython | PySide6 6.11.1 | Qt Widgets、QProcess、signal/slot、中文资源 | wheel：LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only；Qt 商业许可另行取得 | 官方 Qt Python 绑定，线程/进程/可访问性成熟 |
| Windows 打包 | PyInstaller、pyside6-deploy、Nuitka | 首选 PyInstaller 6.21.0，保留 pyside6-deploy 备选 | 在 Windows CI/发布机打包；外部 SU2/Gmsh 许可证单独处理 | GPL-2.0 + bundling exception；少量文件 Apache-2.0 | 成熟 hook 和 Windows bootloader，不自研打包器 |
| 自动测试 | pytest、GitHub Actions、上游 TestCases | pytest + GitHub Actions + 本地集成测试 | 单元测试不依赖 SU2；Gmsh/SU2 在 Windows 本地门禁 | MIT | 成熟 fixture、参数化、报告和 CI 集成 |

## 官方上游审查

### SU2

- 官方仓库：https://github.com/su2code/SU2
- 官方下载：https://su2code.github.io/download.html
- Quick Start：https://su2code.github.io/docs/Quick-Start/
- 自定义输出/history：https://su2code.github.io/docs_v7/Custom-Output/
- Windows 指南：https://su2code.github.io/docs_v7/SU2-Windows/
- 审查 pin：tag `v8.5.0`，commit `12eb826f049ef7f67df974dfcb44cf36ee07c0f8`
- 已取证内容：`QuickStart/inv_NACA0012.cfg`、`QuickStart/mesh_NACA0012_inv.su2`、`TestCases/incomp_rans/naca0012/naca0012_SST_SUST.cfg`、`SU2_PY/parallel_computation.py`、`config_template.cfg`。
- 选择理由：官方 TestCases 和 config template 直接作为配置与回归事实源；history CSV 和 ParaView 输出作为机器接口。
- 当前状态：官方 `SU2-v8.5.0-win64-omp.zip` 已按 SHA-256 校验并安装；真实 `SU2_CFD.exe`、QuickStart 与 INC_RANS/SST 均已在本机通过。当前证据见 `artifacts/upstream_validation/su2_install/`、`su2_quickstart/` 与 `su2_inc_rans_sst/`。

### Gmsh

- 官方仓库：https://gitlab.onelab.info/gmsh/gmsh
- 4.15.2 手册：https://gmsh.info/doc/texinfo/gmsh.html
- 审查 pin：tag `gmsh_4_15_2`，commit `657c8e915f60405e6cad0c8ec7faf812bfff1a60`
- 官方 t20 STEP import 和官方 Python boolean 示例均已原样运行成功。
- 官方手册明确：`BoundaryLayer` field 只适用于 2D；三维边界层需采用官方 3D 示例所示的拓扑挤出等受支持路径，并对 example_model.STEP 做质量验证。不能把 2D field 宣称为三维机翼边界层方案。
- 许可证门禁：若最终闭源分发中集成或链接 Gmsh，必须在发布前完成许可证/商业许可评估；当前审计不是法律意见。

### PyVista / VTK / PyVistaQt

- PyVista：https://github.com/pyvista/pyvista
- 文档：https://docs.pyvista.org/
- 流线示例：https://docs.pyvista.org/examples/01-filter/streamlines.html
- PyVistaQt：https://github.com/pyvista/pyvistaqt
- 选择理由：直接复用 VTK 的 slice、clip、streamline、contour、screenshot 和 Qt 嵌入。
- 实测发现：PyVista 0.48.4 已不接受 `max_time`，必须用 `max_length`；Windows 下不要强制 `QT_QPA_PLATFORM=offscreen` 后再嵌入 VTK，否则本机 Win32 OpenGL 取 pixel format 失败。默认 Windows Qt 平台 + `QtInteractor(off_screen=True)` 已通过。

### meshio

- 官方仓库：https://github.com/nschloe/meshio
- 版本：5.3.5（2024-01-31）
- 支持列表包含 Gmsh、SU2、VTK、VTU；项目实测 Gmsh→VTU 成功。
- 实测已知 Issue：读取 Gmsh 4.1 后的 `gmsh:bounding_entities` 是带方向的 CAD 实体标签，不是单元索引；转换适配层必须排除该元数据但保留物理组。当前适配器按 `field_data=(tag, dimension)` 隔离跨维度重用 tag；物理组按“单元类型 + 连通关系”规范化成员。完整回环校验还会跨 cell block 分区比较每个单元的类型/连通关系，并以 `rtol=atol=1e-12` 比较点坐标。5.3.5 的 SU2 writer 在边界循环中错误解包 `CellBlock`，本机真实触发 `TypeError`。因此 SU2 写出不能在该版本被视为已验证，优先让 Gmsh 直接导出 SU2，或等待/验证修复后的 meshio 版本。

### PySide6

- 官方文档：https://doc.qt.io/qtforpython-6/
- QProcess：https://doc.qt.io/qtforpython-6/PySide6/QtCore/QProcess.html
- 许可证：https://doc.qt.io/qtforpython-6/licenses.html
- 复用重点：GUI 主线程只处理 UI；长任务用 QProcess/worker signal；读取 stdout/stderr 和 exit status，不阻塞事件循环。

### OpenVSP / VSPAERO

- 官方仓库：https://github.com/OpenVSP/OpenVSP
- 当前调研版本：3.50.5（2026-06-05）
- VSPAERO 是薄面、无黏、亚/超声速 VLM/面元类工具，可用于早期趋势和交叉检查；不得与黏性 RANS/SST 结果混称。
- 项目第一版标准 CFD 内核不变：SU2。

## 相似开源项目搜索

已检索组合：`SU2 Gmsh Python aircraft`、`SU2 GUI`、`SU2 PySide6`、`Gmsh STEP external aerodynamics`、`aircraft CFD automation SU2`、`PyVista Qt CFD viewer`、`automatic external flow mesh Gmsh`、`SU2 incompressible RANS SST`、`Gmsh SU2 mesh converter`。

Stars 是 2026-07-22 搜索时的辅助快照，不参与许可证或质量结论。

| 仓库 | 维护 / Stars | License | 适用功能 | 可复用内容 | 不能直接复用 / 已知问题 | Windows / 测试 / 版本 |
|---|---|---|---|---|---|---|
| [su2code/SU2](https://github.com/su2code/SU2) | 官方，v8.5.0，活跃 | LGPL-2.1 | 求解、配置、回归、Python 调度 | QuickStart、TestCases、SU2_PY、输出字段 | 不复制或修改求解器；官方 Windows OMP 二进制以外部工具方式安装 | 官方 Windows OMP 已实测；大型回归套件 |
| [su2code/su2gui](https://github.com/su2code/su2gui) | 官方；2026-02 有提交；约 15 | GPL-3.0 | SU2 配置 GUI | 字段组织、校验思路 | GPL 兼容性需审查；不是 PySide6 桌面模板 | 有 tests；无明确 Windows 发布流水线 |
| [cfsengineering/GMSH-Airfoil-2D](https://github.com/cfsengineering/GMSH-Airfoil-2D) | 2026-03 有提交；约 58 | Apache-2.0 | 2D 翼型 Gmsh/SU2 | physical groups、导出和测试模式 | 仅 2D，不能推导 3D STEP 外流场/边界层 | 有 tests 与 GitHub 配置；Python 项目 |
| [Mikekiely/wuFoil](https://github.com/Mikekiely/wuFoil) | 2025-06 有提交；约 51 | GPL-3.0 | 2D 翼型流程 | UX 和 2D 算例参考 | 仅 2D；无测试/CI；GPL 影响复制 | 未提供可靠 Windows 门禁；不作模板 |
| [AhmedMoustafaa/SU2-wizard](https://github.com/AhmedMoustafaa/SU2-wizard) | 2026-03 新项目；约 2 | MIT | SU2 配置映射 | 少量字段映射可对照 | 太新、无 tests/CI、仓库含 venv；不能作为基础 | Windows 证据不足；依赖状态不稳 |
| [Ujjawal179/su2gui](https://github.com/Ujjawal179/su2gui) | 2026-02 有提交 | GPL-3.0 | SU2 GUI 变体 | 可对照测试组织 | 与官方项目高度重叠，优先官方上游 | 有 tests；版本/分发需单独核验 |
| [EduardoMolina/su2gui](https://github.com/EduardoMolina/su2gui) | 2023 后不活跃 | GPL-3.0 | 旧 SU2 GUI | 历史参考 | 旧 fork、无 tests/CI，优先官方 | Windows/依赖现代性未证明 |
| [bommaritom/SU2_GUI](https://github.com/bommaritom/SU2_GUI) | 2018 后不活跃 | 未发现 | 旧 GUI | 无 | 无许可证、无 tests/CI；禁止纳入 | Windows/现代版本不明 |
| [sankarcse/SU2-Performance-Analyzer](https://github.com/sankarcse/SU2-Performance-Analyzer) | 2018 后不活跃 | 未发现 | 性能结果分析 | 概念参考 | 无许可证、无测试；禁止复制 | Windows/依赖过时风险高 |

搜索没有发现同时满足“3D aircraft STEP + Gmsh 外流场 + SU2 INC_RANS/SST + PySide6/PyVista + Windows 测试”的成熟项目。因此集成层需要自研，但底层算法全部复用官方库。

## 允许自研的胶水代码

仅限以下内容：

- 项目参数模型、单位和输入合法性检查；
- example_model.STEP 的固定坐标映射、几何尺度检查和边界命名策略；
- 用户参数到 Gmsh/SU2 官方字段的受控映射；
- 外部进程调度、取消、超时、日志和工程化错误提示；
- history CSV 增量读取、收敛状态规则；
- 升力/重量比较和结果汇总；
- 中文 GUI、HTML 报告和针对 example_model.STEP 的网格策略。

每个新增函数进入实现前必须在设计/PR 中回答：官方库是否已有、成熟项目是否已有、能否调用 API、自己实现是否更可靠、维护风险是什么。检索证据不足时不实施。

## 网页三维方案专项比较（2026-08-02）

| 方案 | 官方能力 | 实际优点 | 已知限制 | 决策 |
|---|---|---|---|---|
| PyVista `Plotter.export_html()` | 官方 API 将当前 VTK 场景导出为可交互 HTML | 与现有 Python/VTK 管线最贴近；无 Node 构建；文件天然按任务隔离；离线可打开 | 场景导出后状态固定；高级控件需重新导出或扩展 Trame；HTML 含运行时有固定体积 | **首个产品切片采用**。真实 44,260 B 表面结果导出 1,056,054 B HTML，0.391 s |
| 常驻 Trame Local/Remote View | 官方支持浏览器本地渲染、服务端远程渲染和状态同步 | 可做拖动切片、点选和实时控件，直接复用 VTK | 引入 WebSocket/第二套服务状态；RemoteView 依赖服务端渲染；部分交互需单独验证 | 第二阶段候选，仅在 standalone HTML 的交互边界明确后引入 |
| 直接 VTK.js | 官方 BSD-3-Clause WebGL/WebGPU 科学可视化，支持 PolyData/ImageData 和常用读取器/部件 | 前端自由度和本地交互最高 | 是 VTK/C++ 子集；需要 Node 构建、JS 数据转换、版本和浏览器兼容维护 | 暂不采用；需要复杂表面点选或客户端动态场景时再评估 |
| ParaView Glance | Kitware 的网页查看器，可复用 VTK.js 生态 | 通用查看能力成熟 | 产品工作流、参数来源、任务安全与中文诊断仍需额外集成；通用工具界面不等于本项目交互 | 作为行为参考，不嵌入完整应用 |

实测记录保存于 `artifacts/visualization_research/`。PyVista 0.48.4 的依赖元数据要求 `trame-vtk<2.11.9`，因此选择已实测的 2.11.8，而不是未经兼容验证的最新版。

## 上游验证结果

| 顺序 | 验证 | 最终退出码 | 状态 | 证据 |
|---:|---|---:|---|---|
| 1 | SU2 官方 QuickStart | 127 | BLOCKED：缺 `SU2_CFD.exe` | `artifacts/upstream_validation/01_su2_official_quickstart/` |
| 2 | SU2 官方 INC_RANS/SST | 127 | BLOCKED：缺 `SU2_CFD.exe` | `artifacts/upstream_validation/02_su2_official_inc_rans_sst/` |
| 2a | SU2 官方 Windows x64 OpenMP 安装/启动 | 1（usage） | PASS：asset/SHA/exe/PATH 均已取证；无参 usage 的非零退出符合该 CLI 行为 | `artifacts/upstream_validation/su2_install/` |
| 2b | 安装后 SU2 官方 QuickStart | 0 | PASS：生成非空 history 与 flow/restart/surface 输出 | `artifacts/upstream_validation/su2_quickstart/` |
| 2c | 安装后 SU2 官方 INC_RANS/SST | 0 | PASS：history 非空且无 NaN/Inf；保留首次 supervisor 超时 attempt | `artifacts/upstream_validation/su2_inc_rans_sst/` |
| 3 | Gmsh 官方 t20 STEP import | 0 | PASS | `artifacts/upstream_validation/03_gmsh_official_t20_step_import/` |
| 4 | Gmsh 官方 boolean subtraction | 0 | PASS | `artifacts/upstream_validation/04_gmsh_official_boolean_subtraction/` |
| 5 | meshio Gmsh→VTU | 0 | PASS；两次兼容问题留档 | `artifacts/upstream_validation/05_meshio_gmsh_conversion/` |
| 6 | PyVista 网格/流线/等值面/截图 | 0 | PASS | `artifacts/upstream_validation/06_pyvista_display_streamlines/` |
| 7 | PySide6 + PyVistaQt 最小嵌入 | 0 | PASS | `artifacts/upstream_validation/07_pyside6_pyvistaqt_embed/` |
| 8 | meshio 拓扑守恒补充门禁 | 0 | PASS：1,543 points / 9,293 cells 类型计数一致 | `artifacts/upstream_validation/08_meshio_topology_integrity/` |
| 9a | Gmsh 代表性 physical groups fixture | 0 | PASS：生成 `aircraft`、`farfield`、`fluid` 三组 | `artifacts/upstream_validation/09a_gmsh_grouped_fixture/` |
| 9b | meshio physical-group 成员守恒门禁 | 0 | PASS：转换前后逐组成员完全一致 | `artifacts/upstream_validation/09b_meshio_physical_group_integrity/` |

详细说明见 `artifacts/upstream_validation/README.md`。1、2 是不可改写的安装前历史 127 证据；2a–2c 是同一官方输入的安装后当前 PASS 证据。三个当前 `su2_*` 目录均含可由 `scripts/research/write_content_manifest.py --verify` 自验证的 `content-sha256.json`。阶段 -1 基础链路门禁已经满足，但本阶段没有据此启动 example_model.STEP、GUI 或计划 Task 1+。
