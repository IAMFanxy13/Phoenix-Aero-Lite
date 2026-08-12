# Numerical verification

## Three-grid method

Phoenix uses Roache's three-grid Grid Convergence Index with safety factor 1.25. The effective refinement ratio is derived from cell count using the declared spatial dimension: square root for 2D and cube root for 3D. A study is blocked when grids are not increasingly refined, setup fingerprints differ, any member is not iteratively converged, refinement ratios are materially inconsistent, or the sequence is degenerate/oscillatory.

The implementation was exercised with NASA NAS-2016-01 Table 7.5 standard-SST values at alpha 10° on the 225×65, 449×129 and 897×257 grids. Exact inputs and provenance are in `artifacts/validation_matrix/nasa_published_sst_grid_family/`.

| Quantity | Observed order | Fine-grid GCI | Richardson extrapolation | Asymptotic check |
|---|---:|---:|---:|---|
| CL | 0.5998 | 1.2027% | 1.074293 | FAIL (ratio 0.4354) |
| CD | 2.4260 | 0.5913% | 0.0125631 | PASS |
| L/D | 2.6060 | 0.3787% | 86.1945 | PASS |

These numbers verify the calculation path against a published monotonic family. They do not demonstrate that Phoenix reproduced those NASA flow solutions. Runtime timings are `null` because Table 7.5 does not report them; zero was not substituted.

## Reproducible official SU2 SST grid-family run

Phoenix ran SU2 8.5.0 from scratch against the pinned official
`su2code/SU2` configuration and the 113x33, 225x65 and 449x129 meshes from
`su2code/TestCases`, all at tag `v8.5.0`. The official V1994m SST physics,
Mach 0.15, angle of attack 10 deg and Reynolds number 6e6 were preserved.
Only restart, mesh filename, iteration budget, output frequency and explicit
history fields were changed and recorded. Every member has the same audited
setup fingerprint.

| Grid | Nodes | Cells | Last iteration | CL | CD | L/D | Runtime |
|---|---:|---:|---:|---:|---:|---:|---:|
| Coarse 113x33 | 3,704 | 3,584 | 289 | 0.890976 | 0.0592433 | 15.0393 | 15.34 s |
| Medium 225x65 | 14,576 | 14,336 | 632 | 1.070413 | 0.0157748 | 67.8558 | 82.25 s |
| Fine 449x129 | 57,824 | 57,344 | 1,082 | 1.083985 | 0.0130319 | 83.1793 | 340.41 s |

All process exit codes were zero, but convergence was accepted separately by
the Phoenix benchmark policy (`TARGET_AND_FORCE_PLATEAU`). The monotonic study
uses effective refinement ratios 2.0 and passes the implemented asymptotic
ratio gate for all three quantities:

| Quantity | Observed order | Fine-grid GCI | Richardson extrapolation |
|---|---:|---:|---:|
| CL | 3.7247 | 0.1281% | 1.085096 |
| CD | 3.9862 | 1.7720% | 0.0128472 |
| L/D | 1.7852 | 9.4115% | 89.4420 |

Commands, official URLs, hashes, configurations, histories, logs and summaries
are under `artifacts/validation_matrix/su2_official_sst_grid_family_runtime/`.
Large official meshes and generated flow/restart fields remain reproducible
local artifacts and are intentionally ignored by Git.

This is L3 **numerical verification**, not L4 experimental validation. The
relatively large L/D GCI remains visible, and this 2D compressible benchmark
does not validate Phoenix's 3D incompressible aircraft workflow.

## Iterative convergence remains independent

GCI is not computed for a Phoenix study unless every grid member has passed the configured iterative-convergence policy. Process exit code 0 is never sufficient. The official sustaining-SST evidence is therefore retained at L1 even though SU2 exited normally.

## Three-dimensional requirement

The aircraft product path declares spatial dimension 3 and therefore uses cube-root effective ratios. A complete three-grid example_model.STEP engineering study remains blocked because the current real solution is stagnated and its computed wall Y+ is outside the resolved-wall target over nearly all surface area. The software reports that block instead of emitting a fabricated GCI.
