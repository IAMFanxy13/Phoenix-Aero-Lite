# Architecture

Phoenix is an adapter-oriented local application:

`FastAPI/Jinja UI → persistent job service → resumable content-addressed workflow → Gmsh → SU2 → PyVista/VTK → HTML report`

Core boundaries:

- `models/`: immutable parameters, evidence and manifests;
- `geometry/` and `meshing/`: Gmsh/OpenCASCADE adapters;
- `solver/`: SU2 configuration, history, convergence, credibility and GCI;
- `postprocess/` and `visualization/`: meshio/PyVista/VTK result readers and scenes;
- `app/`: orchestration, cancellation, atomic checkpoints and stage fingerprints;
- `web/`: loopback API, persistent tasks and unified workbench.

Third-party engines remain unmodified. Process calls use argument arrays with `shell=False`. Manifest schema 3 stores each stage input fingerprint and artifact hashes; legacy schemas load conservatively.
