# 官方工具事实审计（2026-08-01）

## 结论

Phoenix Aero Lite 继续采用官方库/API作为边界：Gmsh/OpenCASCADE 负责 STEP 与网格，SU2 负责不可压缩 RANS/SST，meshio 负责格式转换，PyVista/VTK 负责后处理，FastAPI/Starlette 负责本机 HTTP 层。网页代码不得实现 CAD、网格、求解器或 VTK 解析器。

| 工具 | 官方事实与来源 | 采用内容 | 许可证/边界 |
|---|---|---|---|
| SU2 8.5.0 | [SU2 官方仓库](https://github.com/su2code/SU2)、[不可压缩 NACA0012 教程](https://su2code.github.io/tutorials/Inc_Turbulent_NACA0012/)、[History/Volume Output](https://su2code.github.io/docs_v7/Custom-Output/) | `INC_RANS`、SST、官方 history/VTU 输出；残差和 CL/CD 联合判定 | LGPL-2.1；仅启动官方二进制并生成 cfg，不修改/内嵌求解器 |
| Gmsh 4.15.2 | [官方手册](https://gmsh.info/doc/texinfo/) 的 t20、OpenCASCADE、`HealShapes`、布尔运算、BoundaryLayer | STEP 导入、OCC 修复、外流场布尔差、物理组、网格场和质量查询 | GPL-2.0-or-later；作为独立依赖/API使用，保留许可证和版本记录 |
| OpenCASCADE | 由 Gmsh OCC 后端调用；Gmsh 官方文档说明 STEP 默认经 OpenCASCADE 导入 | 缝合、小边/小面修复、实体检查 | 不直接复制 OCCT 源码；修复失败必须停止 |
| meshio 5.3.5 | [官方仓库](https://github.com/nschloe/meshio) | Gmsh/SU2/VTU 转换与拓扑检查 | MIT；不自写格式解析器 |
| PyVista 0.48.4 / VTK 9.6.2 | [离屏截图](https://docs.pyvista.org/examples/02-plot/screenshot.html)、[HTML 导出](https://docs.pyvista.org/api/plotting/_autosummary/pyvista.plotter.export_html) | 离屏压力图、速度切片、流线和截图；首版网页用生成图片，避免新增 trame | MIT / BSD-3-Clause |
| FastAPI | [官方特性](https://fastapi.tiangolo.com/features/)、[后台任务说明](https://fastapi.tiangolo.com/tutorial/background-tasks/) | API、上传、静态文件、TestClient；重计算由本地线程任务管理器调度 | MIT；官方明确提醒重计算不宜直接依赖简单 BackgroundTasks |

## 约束

- 速度 5–50 m/s 且 Mach < 0.3，首版固定为不可压缩空气外流场。
- SU2 进程必须保留命令、版本、返回码、stdout、stderr；进程退出 0 只表示程序执行完，不表示工程结果可信。
- `HealShapes` 是尝试性修复，不是“任意 CAD 自动修好”的承诺；修复后仍需实体数、闭合性和布尔运算检查。
- PyVista 网页结果首版复用离屏 PNG/现有 HTML 报告，不增加完整浏览器端 VTK 引擎。

