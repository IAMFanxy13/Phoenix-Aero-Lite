# Upstream Research Log

## 2026-08-04: official SU2 NACA0012 SST grid family

### Sources checked

- `su2code/SU2` tag `v8.5.0`, official configuration
  `TestCases/rans/naca0012/turb_NACA0012_sst.cfg`:
  <https://github.com/su2code/SU2/blob/v8.5.0/TestCases/rans/naca0012/turb_NACA0012_sst.cfg>
- `su2code/TestCases` tag `v8.5.0`, official meshes 113x33, 225x65 and
  449x129 under `rans/naca0012`:
  <https://github.com/su2code/TestCases/tree/v8.5.0/rans/naca0012>
- GitHub's official repository tree API was queried on 2026-08-04 to verify
  that the complete family belongs to the pinned upstream tag before download.

### Adopted and verified

- Reused the official V1994m SST configuration and official nested meshes;
  no CFD model, mesh parser or turbulence implementation was re-created.
- Downloads are restricted to `raw.githubusercontent.com/su2code/` and pinned
  to `v8.5.0`. URLs and SHA-256 values are captured in the evidence manifest.
- Changed only restart mode, mesh filename, maximum iteration budget, output
  frequency and explicit history fields. A common-setup fingerprint excludes
  only official mesh identity.
- All three cases were actually run with the official Windows SU2 8.5.0 binary.
  They independently passed Phoenix's residual and force-plateau convergence
  policy; process exit code alone was not accepted.
- The three monotonic results produced computable dimension-aware GCI for CL,
  CD and L/D. Raw histories, logs, configurations and summaries are retained
  under `artifacts/validation_matrix/su2_official_sst_grid_family_runtime/`.

### Scope and rejected claims

- This is reproducible L3 numerical verification, not L4 experimental
  validation and not direct validation of Phoenix's 3D incompressible aircraft
  workflow.
- The 9.411% fine-grid GCI for L/D is material and is reported, not hidden.
- NASA's published standard-SST table remains a separate provenance path; the
  project does not claim that a different turbulence-model variant is an exact
  reproduction merely because geometry and flow conditions look similar.
- Official solver and mesh artifacts remain governed by their upstream
  licenses; Phoenix records sources and calls public APIs rather than copying
  solver implementation code.

本日志记录重大技术决策采用的人类既有知识。社区内容可用于发现问题，但不单独作为科学判据。查询日期均按本地时区记录。

## 2026-08-04：求解后壁面 Y+

### 来源

- SU2 官方文档，History and Solution Output：`Y_PLUS` 是 `PRIMITIVE` 输出组中的壁面 Y-Plus；默认 `SURFACE_PARAVIEW` 可在表面结果中提供该字段。<https://su2code.github.io/docs_v7/Custom-Output/>
- SU2 官方仓库 `config_template.cfg`：壁函数配置与 `WALLMODEL_MINYPLUS` 的官方选项说明。<https://github.com/su2code/SU2/blob/master/config_template.cfg>
- NASA Glenn CFPOST User's Guide：给出 `y+ = y u_tau / nu_wall`、`u_tau = sqrt(tau_wall/rho_wall)` 的定义。<https://www.grc.nasa.gov/www/winddocs/cfpost/appc.html>
- NASA Glenn Turbulent Flat Plate Study #1：比较 y+=1、2、5、10、30，并报告近壁模型在超过约 5 后开始明显失真。<https://www.grc.nasa.gov/www/wind/valid/fpturb/fpturb01/fpturb01.html>

### 采用

- 直接读取 SU2 `surface_flow.vtu` 中的真实 `Y_Plus`，不自行重复求解器的壁面剪切应力实现。
- 区分目标范围、网格设计估计与求解后 computed 值。
- 输出 min/max/mean/median/P05/P95；三维面数据完整时使用 VTK/PyVista 的单元面积计算越界面积比例。
- 本项目当前 SST 无壁函数配置采用保守的 resolved-wall 目标范围 `0 < y+ <= 1`；这是产品门槛，不冒充外部验证结论。
- 字段缺失、非有限或二维线数据缺少面积时保持 missing/partial，不伪造面积结论。

### 未采用

- 不把首层高度设计值当作求解后 Y+。
- 不从任意博客复制经验公式替代 SU2 输出。
- 不把“存在 Y+ 字段”自动解释为网格合格；仍需检查分布和面积覆盖。
- 不为通过 example_model.STEP 而放宽目标阈值。

### 适用范围、风险与许可证

- 适用于 SU2 产生且保留壁面 `Y_PLUS` 数组的 VTK/VTU 表面结果。
- 二维边界是线而非面，无法形成三维面积比例；此时只报告分布。
- 点值转单元值用于面积分类会产生局部平均，报告中明确记录方法。
- SU2 文档/代码用于接口依据，未复制求解器实现；SU2 为 LGPL-2.1-or-later。PyVista/VTK 仅通过公开 API 使用，许可证影响进入依赖矩阵统一审计。

### 首层高度设计补充

- NASA TMR 三维网格生成说明公开使用 `Cf=0.026/Re^(1/7)` 与目标 Y+ 推导首点高度。<https://turbmodels.larc.nasa.gov/Onerawingnumerics_grids/hcf-grid-generator_description_v4.pdf>
- Phoenix 复用该公开方法计算 Re、Cf、摩阻速度和首层高度，并把方法、湍流模型、是否使用壁函数、层数、增长率及总厚度写入网格证据。
- 该计算严格标记为 `estimated`；它用于设计网格，不会覆盖求解后 `Y_Plus` 的 `computed` 状态。
- 该平板关联式存在几何、压力梯度和转捩假设限制；低于已审计 Re 范围时阻断，不外推成万能公式。

## 2026-08-04：三档网格与 GCI 门禁

### 来源

- NASA/NPARC Examining Spatial (Grid) Convergence：使用 Richardson 外推、有效网格细化比，并强调先验证迭代收敛。<https://www.grc.nasa.gov/www/wind/valid/tutorial/spatconv.html>
- NASA/TM-2000-209946：建议用三档网格估计观测阶并检查渐近区；三档及以上采用安全系数 1.25。<https://ntrs.nasa.gov/api/citations/20000054672/downloads/20000054672.pdf>
- NASA TMR Bump-in-channel 结果：振荡收敛明确报告 GCI 为 N/A，而非填入数值。<https://turbmodels.larc.nasa.gov/bump_sarcqcr.html>

### 采用

- 三维非结构网格以单元数计算有效尺度比 `r=(N_fine/N_coarse)^(1/3)`。
- coarse/medium/fine 必须全部通过迭代收敛并共享同一设置指纹。
- 对 CL、CD、L/D 分别判断；一个量可计算不代表其他量也可计算。
- 只有等效细化比一致且单调序列才计算观测阶、Richardson 外推和 GCI；安全系数为 1.25。
- 振荡、退化、未收敛、设置不一致或细化比不一致时输出原因并将 GCI 留空。

### 未采用、范围与风险

- 当前首版不对明显不等比网格求解 Celik 隐式阶方程，避免数值根选择造成伪精确；先保守阻断。
- “三档结果完全相同”不能证明零离散误差，归类为退化序列。
- GCI 是离散误差估计，不替代湍流模型、几何、工况或实验验证。
- 公式依据为公开 NASA 文档；实现为本项目胶水代码，不复制第三方程序源码。

## 2026-08-04：GitHub Actions 与发布前门禁

### 来源

- GitHub 官方“Building and testing Python”：推荐 `setup-python`、pip 缓存、测试与 artifact。<https://docs.github.com/en/actions/tutorials/build-and-test-code/python>
- GitHub 官方 CodeQL advanced setup：Python 可使用无编译分析，当前官方示例使用 CodeQL action v4。<https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/configure-code-scanning/configuring-advanced-setup-for-code-scanning>
- GitHub 官方 Actions 安全概念：最小化 `GITHUB_TOKEN` 权限，防范脚本注入与供应链风险。<https://docs.github.com/en/actions/concepts/security>
- GitHub 官方 artifact attestations：可为未来正式构建建立来源证明，但写入权限和公开仓库条件需由仓库所有者确认。<https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations>

### 采用

- Linux/Windows Python 3.12 分层 CI，固定项目依赖，pip 缓存、超时、并发取消与失败日志保留。
- workflow 默认 `contents: read`；CodeQL 仅增加 `security-events: write`。
- package 和 release dry-run 只构建/上传 Actions 临时 artifact，不发布 PyPI、GitHub Release 或第三方二进制。
- 所有公开 workflow 排除 `local_su2` 私有模型测试，并扫描被跟踪的 CAD/运行时产物模式。

### 未采用、范围与风险

- 未自动下载或捆绑 SU2/Gmsh 二进制；官方 Release asset 的版本、哈希和许可义务需要独立审查。
- 未启用 artifact attestation，因为仓库尚未由所有者公开并配置相应写权限。
- 未使用第三方发布 action、浮动 `main` 引用、`pull_request_target` 或自动 PyPI 发布。
- GitHub 设置（ruleset、secret scanning、CodeQL 可用性）必须在未来仓库页面由所有者手动确认。
