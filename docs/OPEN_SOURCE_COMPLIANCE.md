# Open Source Compliance

Phoenix uses upstream APIs and does not copy or conceal third-party engines. The project is conservatively licensed under GPL-3.0-or-later because it directly integrates the Gmsh Python API (Gmsh is GPL-2.0-or-later). SU2 is LGPL-2.1-or-later; other dependencies retain their own licenses.

Before distribution:

- review [dependency matrix](legal/dependency-license-matrix.md) and [third-party notices](../THIRD_PARTY_NOTICES.md);
- ship `LICENSE`, `LICENSES/` and notices in source and wheel/sdist;
- do not bundle SU2/Gmsh binaries until binary-distribution obligations are rechecked;
- distribute official third-party download URLs, pinned versions and hashes;
- scan the public tree and reachable history for CAD, paths, logs, tokens and large runtime artifacts.

This repository documentation is an engineering compliance record, not legal advice.
