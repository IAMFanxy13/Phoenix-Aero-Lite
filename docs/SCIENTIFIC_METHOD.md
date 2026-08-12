# Scientific Method

Phoenix separates execution status, iterative convergence, quantity evidence and validation level.

- Gmsh/OpenCASCADE imports CAD, builds the external domain and generates the mesh.
- SU2 8.5.0 runs incompressible RANS/SST. Phoenix does not implement a CFD solver.
- Convergence requires process integrity, complete history, residual reduction and stable coefficients.
- Near-wall design values are labelled **estimated**. Only values read or computed from solved wall data are **computed**.
- CL, CD, L/D, loads, pressure, velocity, streamlines and Y+ each carry source and permission flags.
- GCI is emitted only for three compatible, converged grids with valid refinement and sequence behaviour.
- A benchmark result never transfers validation to unrelated user geometry.

Implementation evidence is described in [Numerical verification](validation/numerical-verification.md) and [limitations](validation/limitations.md).
