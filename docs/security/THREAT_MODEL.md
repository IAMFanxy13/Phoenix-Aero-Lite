# Threat model

## Trust boundary

Phoenix is a single-user local application. Uploaded CAD and all generated solver artifacts are untrusted input. SU2, Gmsh and the browser are separate processes. The API must remain loopback-only by default.

## Controls

- Uploads are size limited and restricted to `.step`/`.stp`; content is copied into a generated model/job directory.
- Job/model identifiers are generated, not user paths.
- Artifact downloads are allow-listed from persisted job metadata and must resolve beneath the owning directory.
- External commands use argument arrays with `shell=False`; user text is never interpolated into a shell command.
- HTML reports escape user-controlled text. Interactive scenes contain generated VTK data and are served only from registered artifact paths.
- Processes have cancellation and timeout handling; state and manifests use atomic replacement.
- The launcher binds `127.0.0.1`, checks port ownership and hides the backend window.

## Principal threats and residual risk

| Threat | Mitigation | Residual risk |
|---|---|---|
| Path traversal / arbitrary download | Resolve and require artifact path beneath job/model root | Symlink/reparse-point behavior requires Windows regression tests |
| Oversized or malicious CAD | Upload limit, OCC import boundary, process/resource limits | Native Gmsh/OCC parser defects remain upstream risk |
| Command injection | No `shell=True`; fixed executable and validated arguments | Compromised local executable/config remains user-environment risk |
| LAN exposure | Server rejects non-loopback host values | Other local processes can call the loopback API; no authentication in single-user alpha |
| Stored HTML/script injection | Jinja autoescape; controlled scene generation | VTK/Trame generated HTML inherits upstream browser security surface |
| Sensitive-data disclosure | Public export scan and ignored local roots | Maintainer must inspect Git history and archives before publication |
| Resource exhaustion | Size/cell/memory ceilings, timeout and cancellation | Large valid CAD can still consume substantial CPU/RAM |

Do not expose the current server through a reverse proxy or public interface. Multi-user/network deployment requires authentication, authorization, CSRF/session design, sandboxing and a separate security review.
