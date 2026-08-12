# ADR: GitHub Actions release preparation

- Date: 2026-08-04
- Status: accepted for dry-run; no online publication authorized

## Decision

Use GitHub-owned Actions for checkout, Python setup, CodeQL and artifact upload. Run public Python tests on Linux and Windows, build wheel/sdist on Windows, and keep release verification manual-only. Grant read-only repository permission except CodeQL's required security-event write permission.

## Rationale

This follows current GitHub documentation, avoids unreviewed third-party release actions and ensures that pull requests cannot publish software or access private CAD. Public CI proves the open tree; local SU2 and example_model.STEP evidence remains a separate private validation layer.

## Consequences

The repository is GitHub-ready but not released. Windows CI does not claim an official SU2 solve until a separately audited official binary bootstrap is added. Artifact attestations and online release steps remain disabled pending owner configuration and license review.
