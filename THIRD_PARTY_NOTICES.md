# Third-Party Notices

Phoenix Aero Lite is a pre-release engineering application. No upstream source code has been modified or vendored into the tracked source tree. Official examples were executed from local, ignored upstream checkouts or copied into ignored validation work directories; project code calls documented public APIs and preserves provenance in the research and validation records.

This file is an engineering inventory, not legal advice. Full license texts and attribution files for every dependency actually shipped must be collected during the release-license gate.

| Component | Version reviewed/tested | License | Official source | Intended use | Upstream modified? |
|---|---:|---|---|---|---|
| SU2 | 8.5.0 | LGPL-2.1 | https://github.com/su2code/SU2 | External CFD executable and official cases | No |
| Gmsh | 4.15.2 | GPL-2.0-or-later with linking exception | https://gitlab.onelab.info/gmsh/gmsh | STEP/OCC and meshing through Python API | No |
| meshio | 5.3.5 | MIT | https://github.com/nschloe/meshio | Mesh conversion | No |
| PyVista | 0.48.4 | MIT | https://github.com/pyvista/pyvista | Visualization API | No |
| VTK | 9.6.2 | BSD-3-Clause | https://gitlab.kitware.com/vtk/vtk | Visualization kernel | No |
| PyVistaQt | 0.12.0 | MIT | https://github.com/pyvista/pyvistaqt | Qt/VTK integration | No |
| PySide6 / Shiboken6 | 6.11.1 | Wheel metadata: `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`; Qt commercial licensing is a separate option | https://doc.qt.io/qtforpython-6/ | Desktop UI and process integration | No |
| pandas | 3.0.3 | BSD-3-Clause | https://github.com/pandas-dev/pandas | CSV and tables | No |
| Matplotlib | 3.11.1 | PSF-based | https://github.com/matplotlib/matplotlib | Charts | No |
| Jinja2 | 3.1.6 | BSD-3-Clause | https://github.com/pallets/jinja | HTML reports | No |
| FastAPI | 0.141.1 | MIT | https://github.com/fastapi/fastapi | Local Web API and HTML application | No |
| Uvicorn | 0.52.0 | BSD-3-Clause | https://github.com/Kludex/uvicorn | Loopback-only ASGI server | No |
| python-multipart | 0.0.32 | Apache-2.0 | https://github.com/Kludex/python-multipart | STEP upload form parsing | No |
| Starlette | 1.3.1 | BSD-3-Clause | https://github.com/Kludex/starlette | FastAPI web runtime | No |
| Pydantic | 2.13.4 | MIT | https://github.com/pydantic/pydantic | API parameter and state validation | No |
| HTTPX | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx | Web API integration tests only | No |
| pytest | 9.1.1 | MIT | https://github.com/pytest-dev/pytest | Tests | No |
| build | 1.5.0 | MIT | https://github.com/pypa/build | PEP 517 distribution build verification | No |
| Ruff | 0.16.1 | MIT | https://github.com/astral-sh/ruff | Static lint checks in development and CI | No |
| mypy | 2.3.0 | MIT | https://github.com/python/mypy | Core scientific-module type checks | No |
| Bandit | 1.9.4 | Apache-2.0 | https://github.com/PyCQA/bandit | High-severity Python security scan | No |
| pip-audit | 2.10.1 | Apache-2.0 | https://github.com/pypa/pip-audit | Published Python dependency vulnerability audit | No |
| Playwright for Python | 1.62.0 | Apache-2.0 | https://github.com/microsoft/playwright-python | Headless browser acceptance tests | No |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil | CPU/RAM and process diagnostics | No |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging | Version/specifier checks | No |
| PyInstaller | 6.21.0 tested | GPL-2.0 with bundling exception; selected files Apache-2.0 | https://pyinstaller.org/en/stable/license.html | Windows internal-validation packaging | No |
| OpenVSP / VSPAERO | 3.50.5 candidate | NASA Open Source Agreement 1.3 | https://github.com/OpenVSP/OpenVSP | Future inviscid cross-check only | No |
| Trame | 3.13.2 tested | Apache-2.0 | https://github.com/Kitware/trame | PyVista browser-scene export/runtime | No |
| trame-vtk | 2.11.8 tested | Apache-2.0 | https://github.com/Kitware/trame-vtk | VTK scene serialization for browser viewing | No |
| trame-vuetify | 3.2.5 tested | MIT | https://github.com/Kitware/trame-vuetify | Trame UI/runtime dependency | No |
| nest-asyncio2 | 1.7.2 tested | BSD-2-Clause | https://github.com/erdewit/nest_asyncio | Supported synchronous PyVista Trame launch path | No |
| VTK.js | 36.1.1 reviewed, not shipped | BSD-3-Clause | https://github.com/Kitware/vtk-js | Future client-side rendering candidate | No |

## Distribution gates

- The source project is GPL-3.0-or-later, selected conservatively for direct Gmsh Python API integration.
- Do not publish the internal PyInstaller directory until authoritative license/NOTICE texts for every bundled native library have been collected and reviewed.
- Meet PySide6/Qt LGPLv3 requirements or use an appropriate commercial license.
- Preserve copyright, license and NOTICE material for every shipped wheel and binary.
- Do not copy code from repositories with missing or unknown licenses.
- Do not claim VSPAERO results are viscous RANS results.
- Re-run license scanning against the final frozen dependency graph before every release.

The complete installed Python environment metadata, including transitive packages and the license fields published by each wheel, is captured in `artifacts/upstream_validation/environment_python_packages/stdout.txt`. An earlier GBK encoding failure is retained in its `attempt-1/` directory. Metadata is evidence for review, not a substitute for collecting authoritative license texts before distribution.
