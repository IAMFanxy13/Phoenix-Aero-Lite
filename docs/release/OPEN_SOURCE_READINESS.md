# Open-source readiness

## Ready now

- History-free source export generated only from tracked files.
- Private CAD, real job directories, solver caches, local tool configuration, absolute paths, usernames, model hashes and private history fixtures are excluded.
- Public export has a manifest and sanitization report and can run its public test suite without a Git repository.
- Project metadata uses `GPL-3.0-or-later`, modern PEP 517 build configuration, SPDX license expression and `license-files`.
- Required community, security, citation, contribution, issue/PR template and GitHub workflow files are present.
- CI/dry-run workflows do not publish and do not use private models.

## License decision

GPL-3.0-or-later is the conservative project license because Phoenix directly imports and calls the Gmsh Python API, whose upstream license is GPL-2.0-or-later with a linking exception. SU2 is invoked as a replaceable external LGPL-2.1-or-later executable. PyVista, VTK, Trame, meshio, FastAPI and the other direct dependencies are recorded in the dependency matrix and notices. This is an engineering compatibility assessment, not legal advice.

## Important history rule

The development repository has contained private local validation fixture material. Deleting a working-tree file would not remove it from Git history. Therefore do not publish the development repository or its history. Initialize a new repository from the history-free public export, inspect the sanitization report, then create the first public commit there.

## Binary distribution gate

The internal PyInstaller build is technically smoke-tested but is not approved as a public binary. Before distributing it, collect authoritative license and NOTICE texts for every bundled wheel/native library, confirm Qt/Gmsh obligations for the exact artifact and reproduce the build on a clean Windows runner. Source, wheel and sdist remain the recommended first release form.

## Maintainer-only actions

GitHub repository creation, visibility, owner, branch rules, security features, Release signing, tags and any package-index upload require manual maintainer decisions. No credentials or remote mutations were used during preparation.
