# Privacy and local data

Phoenix Aero Lite is a local application. By default its web server binds only to `127.0.0.1`; it does not upload CAD, meshes or CFD results to a cloud service.

Local data include uploaded STEP/STP copies, derived meshes, SU2 inputs and outputs, screenshots, reports, job state and logs. They are stored under the configured project data root (`web-data/` and user-selected case directories). Users must treat these files as design data and remove them using normal filesystem tools when no longer needed.

The public source tree must never contain private CAD, job directories, tokens, browser profiles, local absolute paths or private screenshots. `example_model.STEP`, `example_model.SLDPRT`, local tool configuration, `web-data/`, case outputs and large solver artifacts are excluded by `.gitignore` and by the public-release scan.

Phoenix invokes local SU2 and Gmsh processes. Their own telemetry and privacy behavior is governed by the installed upstream versions; the approved workflow uses official local binaries and does not configure remote submission.

Security reports should follow `SECURITY.md`. Do not attach proprietary CAD to a public issue.
