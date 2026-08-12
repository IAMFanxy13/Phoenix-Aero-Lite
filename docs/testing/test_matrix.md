# 测试矩阵与验证边界

| 层级 | 覆盖内容 | 当前状态 |
|---|---|---|
| 单元测试 | 参数、坐标、网格语义、SU2 配置、历史解析、载荷、报告、状态机、运行时诊断 | PASS |
| 集成测试 | Gmsh/meshio 转换、SU2 单迭代、PyVista 离屏渲染、Qt/VTK 交互 | PASS；部分平台能力按条件跳过 |
| 官方上游 | SU2 QuickStart、INC_RANS/SST，Gmsh STEP/布尔，meshio，PyVista，PySide6 嵌入 | PASS，证据见 `artifacts/upstream_validation` |
| 真实 CAD | `example_model.STEP` Preview 八阶段可恢复管线 | PASS；单迭代链路烟雾测试 |
| Windows 打包 | PyInstaller 配方、构建门禁、运行时发现、冻结程序启动 | PASS；PyInstaller 6.21.0 生成的内部验证包持续运行 15 秒且无早退 |
| Fluent 对照 | 相同边界条件的独立基线 | NOT RUN；没有获准且可追溯的 Fluent 基线输入/结果 |
| 网格无关性 | Preview/Standard/Fine 工程对照 | NOT VALIDATED；需要确认参考面积、弦长、质量与收敛预算 |

## 发布解释

“软件链路通过”不等于“当前模型获得工程有效气动结论”。真实模型验证使用 `S_ref=1 m²`、`c_ref=1 m`、`mass=1 kg` 和单迭代，仅用于证明端到端执行与恢复机制。报告中的该次升阻系数是原始追踪值，不能用于设计签字。

SU2 是唯一标准 CFD 内核。没有配置 SU2 时程序会报错，绝不回退至 Fluent、VSPAERO 或其他方法。任何未来的 Fluent/VSPAERO 对照必须保留工具版本、输入、网格、边界条件与原始输出，且明确区分黏性 RANS 与快速面元法。
