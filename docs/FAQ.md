# FAQ

**Is Phoenix a new CFD solver?** No. It automates official Gmsh, SU2, meshio, PyVista and VTK capabilities.

**Does “completed” mean correct?** No. Execution and convergence are independent. Evidence gates decide permitted use.

**Can I view fields after a failed convergence check?** Often yes for diagnosis, with a persistent warning. Coefficients and engineering conclusions remain blocked.

**Why select the main wing?** STEP does not contain aerodynamic semantics. Real surface selection provides auditable reference geometry.

**Why three grids?** One grid cannot quantify discretization sensitivity. Phoenix only computes GCI when the formal prerequisites hold.

**Why can lift exceed weight without proving take-off?** Stability, trim, drag, propulsion, controls, stall margin, ground effects and transient behaviour are not established by that one comparison.

**Does Phoenix upload my model?** No. The server binds to loopback and processing is local.
