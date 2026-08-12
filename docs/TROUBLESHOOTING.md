# Troubleshooting

| Symptom | Meaning | Action |
|---|---|---|
| Environment blocker | Required runtime, package, permission or port is unavailable | Open the environment panel and follow its per-item Chinese remediation |
| STEP inspection fails | CAD is unreadable, open, malformed or unsupported | Re-export as STEP AP214/AP242; repair in the CAD system; keep the original |
| Mesh invalid-surface warning | Small/sliver/duplicate geometry or unsuitable size | Use geometry check; inspect the identified surface; do not ignore an engineering blocker |
| Solver missing DLL | Official SU2 cannot start | Install supported VC++ runtime or re-extract the official OpenMP release |
| Stagnated/oscillating convergence | Later iterations did not stabilize | Inspect mesh and boundary conditions; use the one-time conservative retry if offered |
| Y+ missing or outside target | Near-wall evidence is absent or unsuitable | Use Standard analysis, inspect prism coverage and solved wall Y+ |
| Streamlines fail | Real volume field or usable seed path is missing | Read the shown cause; no fake streamline is substituted |
| Port occupied | Another process already owns the local port | Close the old Phoenix process or choose another port |

Raw logs and artifacts remain under the local task directory. Do not publish private CAD or task histories.
