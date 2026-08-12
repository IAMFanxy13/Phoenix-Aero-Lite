# Quick Start / 快速开始

Phoenix Aero Lite is a local Windows application. It does not upload CAD or CFD data.

1. Install Python 3.12 and the pinned project dependencies.
2. Install the official SU2 8.5.0 Windows OpenMP release and record its absolute `SU2_CFD.exe` path in ignored `config/local_tools.json`.
3. Double-click `Start_Phoenix_Aero_Lite.cmd`.
4. Open the environment-check panel; resolve every blocker.
5. Upload a `.step` or `.stp`, inspect dimensions, then pick the nose, upper side and real wing surfaces in 3D.
6. Enter speed, angle of attack and mass. Start with **Initial trend**; use **Standard analysis** only after geometry is clean.
7. Read the evidence verdict before reading CL/CD. “Completed” does not mean “converged.”

The service binds only to `127.0.0.1`. See [User Guide](USER_GUIDE.md) and [Troubleshooting](TROUBLESHOOTING.md).
