# 相似开源项目审查（2026-08-01）

GitHub 元数据通过官方 API 查询；Stars 只作辅助，不代表工程可信度。

| 项目 | 维护/License | 可借鉴 | 不直接复用原因 | 决定 |
|---|---|---|---|---|
| [su2code/SU2](https://github.com/su2code/SU2) | 官方、活跃；LGPL-2.1 | TestCases、SU2_PY、配置和输出约定 | 不改上游求解器 | 直接依赖官方二进制与示例结构 |
| [su2code/su2gui](https://github.com/su2code/su2gui) | 2026 有提交；GPL-3.0；15 stars；README 明示开发中 | GUI 的“载入—设置—运行—可视化”任务划分 | GPL 与项目分发策略需隔离，且其输入侧重现成 SU2 网格，不解决任意 STEP 自动外流场 | 仅借鉴操作流程，不复制代码 |
| [Mikekiely/wuFoil](https://github.com/Mikekiely/wuFoil) | 2025 有提交；GPL-3.0；51 stars | Gmsh+SU2/XFOIL 自动化、批量分析思路 | 仅二维翼型/C-grid；README 自述复杂黏性/跨声速网格局限；不是完整 STEP 飞机 | 不集成，仅作为工程经验 |
| [precise-simulation/cfdtool](https://github.com/precise-simulation/cfdtool) | 2026 有提交；GitHub API 为 NOASSERTION | 易用 CFD GUI 的流程 | 许可证元数据不明确，技术栈和输入流程不匹配 | 不复制、不依赖 |
| [OpenVSP/OpenVSP](https://github.com/OpenVSP/OpenVSP) | 活跃；NOSA 1.3；816 stars | VSPAERO、参数化飞机、V&V 脚本 | 官方定位是参数化飞机几何；官方导入教程不提供任意 STEP→可分析 VSP 组件的自动转换 | 首版不作为通用 STEP 快速求解器；未来对 VSP3 模型交叉检查 |
| [nschloe/meshio](https://github.com/nschloe/meshio) | MIT；成熟 | 网格格式转换 | 不负责 CAD/求解 | 继续直接依赖 |
| [pyvista/pyvista](https://github.com/pyvista/pyvista) | MIT；活跃 | VTK 数据、切片、流线、离屏渲染 | 不负责求解 | 继续直接依赖 |
| [fastapi/fastapi](https://github.com/fastapi/fastapi) | MIT；活跃 | 本机 API、文件上传、测试客户端 | 不应承担重计算可靠性 | 采用，外接独立任务服务 |

## 快速工具兼容性结论

- VSPAERO：基于 OpenVSP/DegenGeom 的势流工具，不是任意 STEP 的通用转换器。
- AVL：需要机翼/尾翼条带和截面参数化；完整 B-Rep STEP 无直接可靠映射。
- XFOIL：二维翼型工具，不能直接求解完整三维飞机。
- 因此首版两档都使用现有 SU2 管线；“快速”只改变经验证的网格/迭代策略，并明确较低可信度上限。

