# 验证依据与分层验收

## 官方/论文基线

1. [SU2 不可压缩湍流 NACA0012 教程](https://su2code.github.io/tutorials/Inc_Turbulent_NACA0012/)：Re=6e6、M≈0.15，提供官方 cfg/网格。
2. [SU2 incompressible solver 论文 AIAA-2018-3111](https://su2code.github.io/documents/AIAA-2018-3111.pdf)：将 SU2 NACA0012 与 Gregory 实验和 NASA CFL3D 对比；属于论文结论，不自动外推到完整飞机。
3. [NASA Turbulence Modeling Resource](https://turbmodels.larc.nasa.gov/)：SST 等湍流模型的网格收敛和验证资料。
4. [SimScale 外流场工作流](https://www.simscale.com/docs/tutorials/aerodynamic-simulation-vehicle/)：CAD→流体域→网格→求解→后处理；作为产品流程参考，不作为数值基准。

## 验收层级

| 层级 | 对象 | 通过条件 |
|---|---|---|
| L0 软件 | 单元/API/路径/取消 | 测试全通过；禁止目录穿越；状态机确定性 |
| L1 上游 | SU2/Gmsh/PyVista 官方示例 | 返回码、stdout/stderr、真实输出均保存 |
| L2 标准 CFD | NACA0012 官方算例 | 与官方 history/气动力趋势一致；记录网格和版本 |
| L3 简单三维机翼 | 公开有限翼或 ONERA M6 等合适低速案例 | CL/CD 趋势、网格独立性和流场结构可解释 |
| L4 用户 STEP | `example_model.STEP`/`example_model.STEP` 代表工况 | 链路成功只是最低条件；必须达到可信度门槛并做至少三档网格比较 |
| L5 Fluent 对照 | 用户提供合法基线后 | 同几何/工况/参考值/湍流近似；CL 目标 ±10–15%，CD ±20–30%，并披露误差来源 |

当前没有经批准的 Fluent 数据，因此不得声称与 Fluent 一致。当前 `example_model.STEP` 500 迭代为 `stagnated`，只证明软件链路，不是工程验证结果。

