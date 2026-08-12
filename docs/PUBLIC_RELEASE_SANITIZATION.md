# Public release sanitization

Create public source only from a backed-up development repository. Do not rewrite or delete the private development history merely to produce a public tree.

Required checks:

1. Export tracked files from the intended commit into a new directory.
2. Search filenames and contents for `example_model.STEP`, `example_model.SLDPRT`, `C:\\Users`, the local Windows username, email addresses, tokens, API keys and project-local tool paths.
3. Exclude `web-data/`, `cases/`, local configs, solver results, screenshots from private models, caches and logs.
4. Include only public benchmark inputs whose source and redistribution terms are recorded.
5. Run tests, license audit, build, clean-environment install and the release dry-run on the exported tree.
6. Review `git ls-files`, archive contents and wheel/sdist contents manually.
7. Push or publish only after the owner explicitly approves the sanitized export.

The development branch may retain private local evidence outside Git. A clean public export must never depend on that evidence to pass its tests.
