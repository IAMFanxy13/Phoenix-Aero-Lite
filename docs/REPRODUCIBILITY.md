# Reproducibility

Each task manifest records source and derived SHA-256 hashes, Phoenix/Git/Python/OS versions, dependency and tool versions, user inputs, automatic values, overrides, parameter sources, mesh and solver settings, commands, exit state, evidence, parent task and artifact hashes.

Manifest schema 4 also stores a fingerprint and producer identity for each stage. A stage is reused only when its input fingerprint and every artifact hash match. Parameter invalidation follows physical dependencies: display-only changes do not solve again; mass changes reporting; flow/reference changes invalidate mesh or solver stages as required; geometry changes invalidate mesh and downstream work.

Absolute local paths are excluded from public reports and exports. Public benchmark sources, conditions and limitations are recorded under `docs/validation/`.
