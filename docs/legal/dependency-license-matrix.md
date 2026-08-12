# Dependency license matrix

This engineering matrix is not legal advice. Versions reflect the pinned Python environment and SU2 8.5.0 validation.

| Component | SPDX / upstream terms | Use | Distributed by current source package | Modified | Main obligation/risk |
|---|---|---|---|---|---|
| Phoenix Aero Lite | GPL-3.0-or-later | Application glue and UI | Yes | N/A | Preserve license/source and notices |
| Gmsh 4.15.2 | GPL-2.0-or-later with linking exception | Python API for OCC and meshing | Dependency declaration only; the Phoenix wheel does not bundle the Gmsh wheel or DLL | No | Direct API integration makes GPL-compatible project license the conservative choice; frozen binary packaging needs separate review |
| SU2 8.5.0 | LGPL-2.1-or-later | External executable | No; installed separately from official release | No | Preserve license/notices; allow replacement; do not imply endorsement |
| PyVista 0.48.4 | MIT | Visualization API | Dependency | No | Copyright and license notice |
| VTK 9.6.2 | BSD-3-Clause | Rendering kernel | Transitive dependency | No | Copyright and BSD notice |
| Trame 3.13.2 / trame-vtk | Apache-2.0 | Browser scene serialization | Dependency | No | License/NOTICE where applicable |
| meshio 5.3.5 | MIT | Mesh conversion | Dependency | No | Copyright and license notice |
| PySide6 6.11.1 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only (wheel metadata) | Desktop UI | Dependency | No | Relinking/replacement and Qt notices; commercial option separate |
| FastAPI 0.141.1 | MIT | Loopback API | Dependency | No | Copyright and license notice |
| Uvicorn 0.52.0 | BSD-3-Clause | Loopback ASGI server | Dependency | No | Copyright and BSD notice |
| Jinja2 3.1.6 | BSD-3-Clause | Reports/templates | Dependency | No | Copyright and BSD notice |
| NASA TMR data | U.S. Government source; asset-specific terms must be checked | Public verification references | Only small derived numeric tables/provenance presently tracked | No | Cite exact page/report; do not imply experimental truth |
| PyInstaller | GPL-2.0 with bootloader exception | Internal Windows packaging candidate | Not in source package | No | Review bundled binary notices before release |

Full direct dependency inventory is in `THIRD_PARTY_NOTICES.md`. Before binary distribution, collect authoritative license texts for every shipped wheel and native library into `LICENSES/` and rerun the final dependency graph audit.
