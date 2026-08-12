# 已采用决定

| 决定 | 采用理由 | 明确不做 |
|---|---|---|
| 原项目内渐进增加 `web` 包 | 复用现有 pipeline/CLI/模型/报告 | 不另起 Demo，不复制核心流程 |
| FastAPI + Jinja2 + 原生 CSS/JS | 小型本地应用、可测试、无 Node 构建链 | 首版不引入 React/Vue/Celery/Redis |
| 本机 `127.0.0.1:8000` | 不暴露公网，减少认证/部署复杂度 | 不监听 `0.0.0.0` 默认地址 |
| 单进程、单重任务队列 | Gmsh/SU2 本机资源重，状态简单 | 首版不做多用户、多机调度 |
| Web 任务服务调用 `PhoenixCasePipeline` | 核心与界面解耦、复用测试 | 不在路由里实现 CFD |
| `execution_status` 与 `credibility` 分离 | 修复“完成=成功”错误 | `stagnated/max_iterations` 不显示绿色成功 |
| 可信/谨慎/无效三档 | 对应工程语义，允许保留诊断产物 | 无效结果不显示为可用于设计的 CL/CD |
| 快速/精细均走 SU2 | 任意 STEP 的兼容性最真实 | 不把 XFOIL/AVL/VSPAERO 包装成通用 STEP 求解器 |
| 首版结果图复用 PyVista 离屏产物 | 稳定、已有测试、无需浏览器 VTK 栈 | 交互三维方向确认作为后续阶段 |
| 先给手动重试入口 | 无已验证自动调参基线 | 当前不盲目自动改 CFL/松弛 |

## 2026-08-02 产品化增量决策

| 决定 | 证据与实测 | 明确边界 |
|---|---|---|
| 首个浏览器三维切片采用 PyVista `export_html()` | 直接复用现有 PyVista/VTK；在真实 `surface_flow.vtu`（356 点、708 单元、44,260 B）上成功生成 1,056,054 B 的独立交互 HTML，用时 0.391 s | 第一阶段场景在服务端生成；切片位置、色标范围等动态控制可通过重生成场景实现，后续再评估常驻 Trame |
| 固定 PyVista 兼容的 Trame 版本 | PyVista 0.48.4 的 `jupyter` extra 明确要求 `trame-vtk<2.11.9` 并排除 2.11.0–2.11.6；实测 `trame-vtk==2.11.8` 可导出 | 不直接采用当时最新的 2.11.15；版本升级必须重新做导出与浏览器回归 |
| 暂不直接编写 VTK.js 前端 | VTK.js 是成熟 BSD-3-Clause 渲染器，但官方说明它是 VTK/C++ 子集，主要支持 PolyData/ImageData 和常用 reader；会引入 Node 构建与前端数据管线 | 若 standalone HTML 无法满足点选、拖动切片或大文件性能，再以官方 VTK.js/Trame 能力扩展，禁止自研 WebGL |
| 浏览器只接收表面与派生数据 | VTK.js Issue #668 的维护者建议对大型非结构网格提取表面并使用 VTP；真实求解已经产生 `surface_flow.vtu` | 体网格保留为可下载的专业产物，不默认加载到浏览器 |
| 表面显示 Cp/Pressure，速度显示切片/流线 | SU2 官方输出字段、成熟产品后处理和社区反复解释均一致；真实文件同时含 `Pressure_Coefficient`、`Pressure`、`Velocity` | 不把 Cp 标成 Pa，不把无滑移壁面的零速度做成“速度表面云图” |
| 统一工作台与渐进披露 | SimScale/ParaView/AirShaper 操作流程和国内外新手反馈共同支持 | 不划分“新手/专业”两个割裂模式；高级诊断仍可完整展开 |

## 方案比较

1. **FastAPI + 原生前端（采用）**：依赖少、可复用 Jinja2、HTTP API 易测。
2. PySide6 内嵌浏览器：仍受桌面线程/打包复杂性影响，且不能实现真正浏览器工作流。
3. Electron/React + Python 后端：界面能力强，但首版引入 Node、IPC、双重打包和更大维护面，违反 YAGNI。
