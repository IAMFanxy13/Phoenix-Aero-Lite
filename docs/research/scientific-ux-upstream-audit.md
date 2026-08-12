# Phoenix Aero Lite 科学与交互上游来源审计

日期：2026-08-03
用途：为 P0–P3 的技术和产品决策提供可追溯来源。本文只采用方法、API 和交互原则，不复制第三方界面或大段代码。

## 1. 证据分级与采用原则

来源优先级：官方软件文档/官方测试 → 政府或标准组织 V&V → 同行评审方法 → 成熟开源实现 → 产品文档 → 工程社区经验 → 营销材料。

每条来源区分：

- **规范/官方能力**：可决定 API、配置或验证流程；仍需在本项目版本上实测。
- **公开科学依据**：可用于建立方法和门槛；必须保留适用范围。
- **工程经验**：用于发现失败模式和 UX 痛点，不能单独决定物理结论。
- **营销/产品表达**：只能借鉴用户流程，不作为准确性证据。

## 2. 核心上游清单

| 来源 | 类型 | 本项目采用内容 | 适用边界 | 许可/发布影响 |
|---|---|---|---|---|
| [SU2 官方仓库](https://github.com/su2code/SU2) / [v8.5.0](https://github.com/su2code/SU2/releases/tag/v8.5.0) | 官方代码/Release | `SU2_CFD`、官方 cfg/TestCases、history/volume/surface 输出约定 | 官方算例通过只验证该版本链路，不验证任意 CAD | LGPL-2.1 及仓库附加说明；当前作为未修改外部程序调用，发行时保留许可证与 notices |
| [SU2 Solver Setup](https://su2code.github.io/docs_v7/Solver-Setup/) | 官方文档 | residual 与 coefficient Cauchy 收敛准则；`INC_RANS` 能力 | 项目不能只照抄一个全局阈值；应按 physics preset 版本化 | 文档仅引用/转述；不复制大段内容 |
| [SU2 Custom Output](https://su2code.github.io/docs_v7/Custom-Output/) | 官方文档 | `HISTORY_OUTPUT`、`OUTPUT_FILES`、surface/volume 结果字段 | 可用字段依赖 solver；应 dry-run/实测确认 | 同上 |
| [SU2 QuickStart/TestCases](https://github.com/su2code/SU2/tree/v8.5.0/QuickStart) | 官方回归 | 固定版本回归、cfg/mesh 哈希和命令证据 | NACA0012 inviscid 回归不是风洞验证，也不是 3D RANS 验证 | 测试资产随 SU2 许可证；若再分发需保留来源/许可 |
| [Gmsh 4.15.2 Reference Manual](https://gmsh.info/doc/texinfo/gmsh.html) | 官方 API 文档 | OpenCASCADE STEP、boolean、Distance/Threshold/Box fields、`geo.extrudeBoundaryLayer`、质量 API | Gmsh `BoundaryLayer` size field 主要面向 2D；3D 层状体网格必须走受支持的 extrusion/topology 路径并实测复杂 CAD | Gmsh GPL-2.0-or-later/商业双许可；Python 包分发和链接方式发布前必须复核，保留许可证 |
| [Gmsh t20 STEP 教程](https://gitlab.onelab.info/gmsh/gmsh/-/blob/master/tutorials/python/t20.py) | 官方示例 | OCC 导入、实体操作和同步的结构 | 仅借鉴 API 调用结构；不把教程当外流场方案 | 保留来源；不无来源复制 |
| [meshio 5.3.5](https://github.com/nschloe/meshio) | 成熟开源库 | Gmsh/SU2/VTK/VTU 读写与转换 | physical groups 和 element types 必须做转换后完整性测试 | MIT；可随项目依赖，保留 notice |
| [PyVista 0.48.4 picking](https://docs.pyvista.org/api/plotting/_autosummary/pyvista.plotting.picking.pickingcomponent.enable_cell_picking) | 官方 API 文档 | 可见表面 cell picking、callback、高亮 | Web 场景需要验证事件到 OCC tag 的映射；不能依赖固定 cell id | MIT；当前复用 API，无上游源码修改 |
| [PyVista 项目](https://github.com/pyvista/pyvista) | 成熟开源库 | VTK 数据结构、slice、streamlines、off-screen | 结果只能来自真实 flow/surface 数据；失败不生成伪流线 | MIT |
| [VTK](https://github.com/Kitware/VTK) | 成熟可视化内核 | picking、filters、rendering、scene serialization | 浏览器传输大小和 GPU 兼容需单独测试 | BSD-3-Clause |
| [Trame](https://github.com/Kitware/trame) | 成熟 Web 桥接 | 服务器/客户端 VTK 交互与状态同步 | websocket 大对象、断线和版本兼容需 E2E | Apache-2.0 体系；保留 NOTICE 要求 |
| [ParaView color mapping](https://docs.paraview.org/en/v5.11.0/ReferenceManual/colorMapping.html) | 官方产品文档 | 自动/手动色标范围、恢复数据范围、opacity、可见范围 | 借鉴交互，不复制 UI；色标不能制造跨任务的假可比性 | 仅采用模式；发布不包含 ParaView 代码 |
| [NASA NPARC Grid Convergence](https://www.grc.nasa.gov/www/wind/valid/tutorial/spatconv.html) | 政府 V&V 教程 | Richardson、GCI、effective refinement ratio、三网格 safety factor、asymptotic range 检查 | GCI 是数值离散误差估计，不是实验验证；三档必须分别迭代收敛且网格生成参数一致 | 美国政府网页；公式实现需注明来源，数据资产仍逐项检查 |
| [NASA Turbulence Modeling Resource](https://turbmodels.larc.nasa.gov/) | 政府 benchmark | NACA0012 等公开 RANS 网格/参考结果、湍流模型定义 | 必须匹配 Mach/Re/AoA/Tref、转捩、远场、模型变体和网格族，不能只比较 CL/CD | 数据和论文逐项记录来源/使用条款；不把网页重打包 |
| [NASA Comprehensive V&V approach](https://ntrs.nasa.gov/api/citations/20120013081/downloads/20120013081.pdf) | 政府技术报告 | code verification、solution verification、validation 分层和数值不确定度 | 不能把 regression test 称 validation | 引用报告，不复制全文 |
| [ASME V&V 20](https://www.asme.org/codes-standards/find-codes-standards/standard-for-verification-and-validation-in-computational-fluid-dynamics-and-heat-transfer) | 标准 | 在指定 validation variable/point 比较模拟与数据并量化不确定度 | 标准是受版权保护的付费材料；本项目只采用公开概述，不宣称认证合规 | 不分发标准正文；若对外宣称遵循需购买并做正式差距审查 |
| [OpenVSP/VSPAERO](https://openvsp.org/docs.shtml) | NASA 开源工具/文档 | 未来可作几何语义和快速气动独立交叉检查 | VSPAERO 是薄面无黏亚/超声速方法，不是黏性 RANS 替代 | NOSA 1.3；引入/分发前单独审查，与 SU2 结果明确分栏 |
| [SimScale result control](https://www.simscale.com/docs/simulation-setup/result-control/) | 成熟产品文档 | 将 forces/coefficients 和 residual 同时作为 convergence 观察量 | 产品采用 OpenFOAM/专有组件，不能照搬其求解默认值 | 只借鉴流程和信息架构 |
| [SimScale mesh sensitivity](https://www.simscale.com/knowledge-base/mesh-sensitivity-cfd/) | 产品知识库 | 三档同工况比较、GCI 作为可选严谨方法 | 属产品教育材料，最终科学规则仍以 NASA/论文为主 | 只转述方法，不复制内容 |
| [AirShaper 产品页](https://airshaper.com/product) | 营销/产品表达 | “上传—计算—交互场—指标”的低门槛路线和部件化结果表达 | 不采用其“易用/可靠”营销主张作为证据；其内部方法不可审计 | 只借鉴抽象交互，不复制品牌/UI/资产 |

## 3. 当前版本与本机证据

| 组件 | 当前版本/标识 | 本轮验证 |
|---|---|---|
| Phoenix Aero Lite | `0.1.0.dev0`, commit `bdd8a86` | 完整 pytest 通过 |
| Python | 3.12.13 x64 | 项目虚拟环境实际导入 |
| SU2 | 8.5.0 “Harrier” OMP | `SU2_CFD --help` 可启动；官方 QuickStart 产物存在 |
| Gmsh | 4.15.2 | 项目环境实际导入；真实 example_model.STEP 网格产物存在 |
| meshio | 5.3.5 | 项目环境实际导入 |
| PyVista | 0.48.4 | 项目环境实际导入；off-screen/scene 测试通过 |
| FastAPI | 0.141.1 | 项目环境实际导入；API 测试通过 |
| pytest | 9.1.1 | 277 passed, 2 skipped |

固定版本是可复现条件，不代表版本本身已经通过所有用户场景。512 条依赖弃用警告显示未来升级需要独立兼容性工作。

## 4. 方法决策与边界

### 4.1 收敛

采用 SU2 官方支持的 residual 和 coefficient Cauchy 思路，并在项目后处理中增加连续窗口状态分类。理由：SU2 自身支持 residual threshold 与 coefficient Cauchy；社区也反复指出 residual 不能单独决定结果。

边界：

- 稳态 RANS 的有界周期振荡可能意味着物理非稳态或数值问题，不能用最后一行当稳态答案。
- `SU2 exit code 0` 只表明程序正常退出，不表明方程或工程量已收敛。
- `likely_converged` 只能作为降级状态，不能被 UI 绿色徽章等同“可靠”。

### 4.2 近壁层和 Y+

采用 Gmsh 官方三维 extrusion API，而不是自己实现棱柱层算法。首层高度设计由目标 Y+、自由来流、特征长度、黏度和有来源的平板摩阻估算推导，保存公式和假设。求解后实际 Y+ 优先取 SU2 壁面输出或由壁面剪切量计算。

边界：

- 首层高度计算只是设计估计，不是实际 Y+。
- SST 的目标 Y+ 与是否使用 wall function 必须和 SU2 配置一致；不能给所有模型一个固定默认值。
- 复杂 CAD 的 concave junction、尖后缘和小间隙可能使 extrusion 失败；失败时要阻断阻力结论。

### 4.3 三档网格与 GCI

采用 NASA NPARC 的成熟流程：保持几何、工况、物理模型、边界条件和网格生成策略一致；对 unstructured 3D 网格用有效 refinement ratio；三个解都先达到迭代收敛，再判断单调、振荡或发散收敛；条件满足才做 Richardson/GCI。

关键边界：

- NASA 页面建议 refinement ratio 至少约 `1.1`，三网格可用 safety factor `1.25`；但这不是把任意三个 cell count 代入公式的许可。
- 网格变化若同时改变近壁拓扑、远场尺度或边界层目标，结果包含多种变化源，不能称纯 grid convergence。
- GCI 估计数值离散误差，不替代湍流模型误差、几何误差、边界条件误差或实验验证。

### 4.4 benchmark

保留现有 SU2 8.5.0 QuickStart 作为 L1 软件回归。P0 新增 NASA TMR NACA0012 RANS benchmark 作为候选 L2/L4，但只有工况、模型变体、网格族、远场、转捩和参考量匹配时才量化比较。

现有 QuickStart 得到 `CL=0.328486, CD=0.021481`，与一份旧版 SU2 官方回归材料的差异约 3.01%/7.13%。该对照是跨版本数值回归，不是风洞误差，不能提升用户 example_model.STEP 的验证等级。

## 5. 成熟交互模式的采用

| 模式 | 来源启发 | Phoenix 采用方式 | 不采用部分 |
|---|---|---|---|
| 单一工作台 + 步骤路线 | SimScale/AirShaper/OpenVSP 教程 | 四任务路线、每步显示状态/成功标准/下一步 | 不复制布局、图标或品牌资产 |
| 结果控制与收敛并列 | SU2GUI/SimScale | residual、CL、CD、退出状态并列健康检查 | 不用单曲线绿色表示成功 |
| 自动/手动色标 + reset | ParaView | 默认数据范围、用户范围、恢复自动、单位和越界提示 | 不让不同任务自动范围看起来可直接比较 |
| 可见表面 picking | PyVista/VTK | OCC tag 映射、高亮、撤销、重置和选择证据 | 不写自研 picking engine |
| 复杂度渐进披露 | 多数成熟 CAE 产品 | 必要输入常显，高级物理折叠但可审计 | 不拆两套互不一致模式 |
| 失败可行动 | SU2GUI logs、SimScale CAD/mesh 错误 | 人话原因、影响、下一步、专业码和原始日志 | 不吞掉原始错误，不自动无限重试 |

## 6. 社区与真实用户反馈的使用方式

详细国内外平台记录已经存在于 `docs/research/06_social_media_and_user_experience.md`。本轮只提取与科学设计直接相关、且能被官方资料交叉验证的结论：

1. Reddit/CFD 社区反复出现“残差是否足够”“网格三档是否等于验证”“Gmsh 边界层为何不生效”等问题。采用价值是发现易错点，不是采用帖子里的具体默认值。
2. Gmsh 3D 边界层社区案例显示 Field 与 extrusion 容易混淆；这与 Gmsh 官方 API 范围相符，因此产品必须显示实际生成的 prism 数，而不是显示配置里写了几层。
3. 初学者常把漂亮云图当可信结论。该问题与 NASA/ASME V&V 原则一致，因此未收敛场可查看但警告必须永久显示。
4. 工程师常要求三档网格、局部/整体指标和 GCI；该经验已由 NASA NPARC 方法交叉验证，因而进入 P0。

社区线索的原始链接、作者/平台、时间、评论问题和验证状态继续由现有 `06_social_media_and_user_experience.md` 维护，避免在本文件重复抄录。

## 7. 许可证与发布行动

### 可直接作为依赖/外部工具继续使用

- PyVista (MIT)、meshio (MIT)、VTK (BSD-3-Clause)、Trame Apache-2.0 组件：保留版本和 notices，不改上游源码。
- SU2：继续以官方未修改 Windows OMP 二进制作为外部进程；配置和官方 test assets 标注来源。

### 发布前必须专项复核

- Gmsh Python 模块的 GPL/商业双许可对打包分发方式的影响；当前技术审计不能替代法律意见。
- SU2 仓库中不同文件/外部依赖的许可证边界。
- OpenVSP 的 NOSA 1.3：在实际集成前单独做兼容性审查；当前不引入代码。
- NASA/论文 benchmark 网格和实验数据的逐资产条款与引用格式。
- ASME V&V 20：不随软件分发标准正文，不使用“ASME 认证”表述。

## 8. 明确拒绝的复用方式

- 不复制 SU2GUI、SimScale、AirShaper、ParaView 或 OpenVSP 的完整界面和项目模板。
- 不从论坛帖复制未知许可证脚本来计算 Y+ 或 GCI。
- 不把 GitHub stars 当科学可靠性。
- 不把营销截图、视频演示或用户评论当 benchmark。
- 不修改本机 SU2/Gmsh/PyVista 源码；适配放在 Phoenix 代码中。
- 不在数据缺失时插入演示 CL/CD、假流线、假 Y+ 或“近似成功”。

## 9. 采用决定

1. CFD 内核继续唯一使用 SU2 RANS 管线；VSPAERO 只保留未来独立交叉检查可能性。
2. CAD/网格继续使用 Gmsh/OpenCASCADE；三维边界层只走官方 extrusion/API 能力并严格验证。
3. 格式转换继续使用 meshio；每次转换验证 marker 和 topology。
4. 三维交互继续使用 PyVista/VTK/Trame；不开发自有渲染/拾取引擎。
5. 科学门槛以 SU2 官方 convergence 能力、NASA grid convergence/V&V 和公开 benchmark 为主；产品文档和社区只补充 UX。
6. 当前最优实现路径是现有架构内渐进增强，不进行技术栈重写。

## 10. 后续更新规则

每次升级上游版本时更新本文件并执行：官方最小算例、INC_RANS/SST、Gmsh STEP/boolean、meshio marker integrity、PyVista off-screen/streamline、Web picking/E2E、example_model.STEP 回归。任何来源失效、许可证变化或 API 变更都必须先更新审计，再修改正式实现。
