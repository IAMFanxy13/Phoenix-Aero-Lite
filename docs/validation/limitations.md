# Validation limitations

- The current public SU2/NASA comparison is not a pass. The official SU2 input uses SST sustaining while the cited NASA table reports standard SST; the continuation also failed SU2's residual criterion.
- The NASA published grid-family exercise validates the GCI implementation only. It does not validate Phoenix meshing, SU2 configuration, or force prediction.
- No experimental L4 validation has been completed.
- The official SU2 V1994m SST three-grid run is L3 numerical verification only. Its fine-grid GCI is 0.128% for CL, 1.772% for CD and 9.411% for L/D; the latter uncertainty is material and must not be hidden.
- No complete, iteratively converged, three-dimensional public-wing grid family has been run through Phoenix yet.
- NASA's downloadable 225×65 CGNS asset is legacy ADF. meshio's official CGNS backend requires HDF5, and the installed SU2 8.5.0 Windows binary exited with access-violation code `0xC0000005` during a one-iteration CGNS-format probe. Phoenix therefore does not claim CGNS/ADF support and does not ship a home-grown parser.
- example_model.STEP is private local evidence, not redistributable benchmark material. Its present solution is diagnostic-only: convergence stagnated and computed Y+ is unsuitable for a resolved-wall SST engineering conclusion.
- Lift exceeding weight at a single steady CFD condition never proves real take-off capability; thrust, ground roll, stability, controls, transient behavior and safety margins are outside this product's present scope.
- Gmsh near-wall design evidence is an estimate until actual prism/wedge topology and post-solve Y+ are measured. Missing evidence remains missing.
- Dependency and license inventory is an engineering aid, not legal advice. Distribution of Gmsh/PySide6/VTK binaries requires final license review.
