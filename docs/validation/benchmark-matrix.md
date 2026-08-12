# Benchmark matrix

Last updated: 2026-08-04

| Evidence | Physics/source | Actual result | Level | Allowed claim |
|---|---|---|---|---|
| SU2 v8.5.0 QuickStart | Official SU2 inviscid NACA0012 regression | Exit 0; CL 0.328486, CD 0.021481; differs from historical SU2 regression by 3.01% and 7.13% | L1 | Installation and software-regression evidence only |
| SU2 v8.5.0 `INC_RANS` SST sustaining | Official SU2/TestCases 897×257 input | Exit 0, but SU2 reports `Converged: No` at 2500 iterations; final CL -0.000002, CD 0.007106 | L1 | Solver path runs; no validation or engineering claim |
| NASA published SST grid family | NAS-2016-01 Table 7.5, alpha 10°, Re 6e6, M 0.15 | Dimension-aware GCI reproduced for published CL/CD/L/D. Fine-grid CD GCI 0.591%; CL asymptotic-range check fails | Algorithm verification | Phoenix GCI implementation handles a public 2D monotonic family; this is not a Phoenix solver result |
| Phoenix continuation of official sustaining-SST case | Official restart continued for another 2500 iterations | Exit 0; residual -9.153 versus required -10; CD 0.005722, 30.3% below NASA standard-SST 897×257 value | FAIL / L1 retained | No public benchmark pass; model variant and convergence do not match |
| Phoenix run of official SU2 SST grid family | SU2/TestCases v8.5.0 `rans/naca0012`, V1994m SST, M 0.15, alpha 10 deg, Re 6e6 | All three official grids converged independently. Fine grid: CL 1.083985, CD 0.0130319. Fine-grid GCI: CL 0.128%, CD 1.772%, L/D 9.411% | L3 numerical verification | Reproducible public solver/grid-family evidence; not experimental validation and not evidence for the 3D aircraft path |
| Private example_model.STEP | User CAD, not a public benchmark | Surface mesh warning repaired for preview; real solver evidence remains stagnated; computed Y+ P95 290.62 and 99.845% area outside resolved-wall target | Private diagnostic only | Preserve failure evidence; no engineering or take-off conclusion |

Primary sources:

- SU2 official tutorial: <https://su2code.github.io/tutorials/Inc_Turbulent_NACA0012/>
- NASA NAS-2016-01: <https://turbmodels.larc.nasa.gov/Papers/NAS_Technical_Report_NAS-2016-01.pdf>
- NASA TMR NACA0012 resource: <https://turbmodels.larc.nasa.gov/naca0012_val.html>
- SU2 v8.5.0 official SST configuration: <https://github.com/su2code/SU2/blob/v8.5.0/TestCases/rans/naca0012/turb_NACA0012_sst.cfg>
- SU2/TestCases v8.5.0 official grid family: <https://github.com/su2code/TestCases/tree/v8.5.0/rans/naca0012>

Machine-readable evidence is under `artifacts/validation_matrix/`. Public data and private user-model evidence are deliberately separated.
