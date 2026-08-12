# Release Checklist

- [x] Working tree and intended release commit identified
- [x] Full unit/integration/E2E suite passes with saved logs
- [x] Public benchmark and GCI evidence classification reviewed
- [x] Private example_model.STEP status is not represented as a public benchmark
- [x] Wheel and sdist build; clean Python 3.12 installation smoke passes
- [x] License audit, dependency check and high-severity security scan pass
- [x] `LICENSE`, `LICENSES/` and `THIRD_PARTY_NOTICES.md` are in source artifacts
- [x] History-free public export contains no CAD, local paths, user names, secrets, logs or caches
- [x] Windows source launcher and internal PyInstaller headless smoke pass on loopback
- [x] Known limitations and changelog are current
- [ ] Tag and release notes reviewed manually
- [x] No automatic push, public repository creation, PyPI upload or online release performed

Tag and release-note approval remains a maintainer action; no network publication is performed by the project scripts.
