# Known limitations

1. **No universal CAD guarantee.** STEP files with open shells, multiple bodies, degenerate edges or unsupported scale are blocked or warned; automated repair is deliberately conservative and non-destructive.
2. **Private aircraft result is diagnostic-only.** Its representative run stagnated and its computed Y+ is outside the resolved-wall SST target over nearly all surface area.
3. **Validation ceiling is L3.** The completed public study is numerical grid verification. There is no approved, physics-matched wind-tunnel/Fluent baseline for L4/L5 validation.
4. **Velocity changes remesh intentionally.** The near-wall first-layer design depends on Reynolds inputs, so changing velocity/density/viscosity invalidates the mesh as a conservative scientific exception to the desired “solver-only” shortcut. AoA and reference area changes reuse the mesh; chord changes remesh.
5. **Cache keeps one current stage record per model/tool identity.** It reuses hash-valid stages across consecutive jobs and has a 20 GiB oldest-run-first cap. Cross-process leases prevent eviction of active runs; if active runs alone exceed the cap, the requesting task is stopped instead of silently claiming the cap was enforced. Returning from parameter set B to an older set A may recompute instead of retaining an unlimited multi-variant cache.
6. **Public CI cannot prove the local SU2 installation.** Tests that require the official external executable skip when `config/local_tools.json` is absent; official SU2 evidence is retained as separate private/local validation.
7. **Browser field E2E uses synthetic public arrays.** It proves real interactive rendering, picking and permission gates, not aerodynamic correctness.
8. **Public frozen binary is gated.** The PyInstaller build is for internal evaluation until bundled native license texts and clean-runner reproduction are complete.
9. **Local service only.** The FastAPI server binds to `127.0.0.1` and has no multi-user authentication. Exposing it to a network is unsupported.
10. **Heuristics require confirmation.** Nose/up/wing candidates carry confidence and rationale; unusual aircraft layouts can remain unresolved and must be corrected by the user.
11. **No certification or flight envelope.** Lift greater than weight is not proof of take-off; thrust, ground run, stability, controls, structural margins and transient behavior are outside scope.
