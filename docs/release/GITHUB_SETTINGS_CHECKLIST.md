# GitHub Settings Checklist

After the owner creates or chooses the public repository, manually enable:

- Issues and Discussions;
- Dependabot alerts and security updates;
- secret scanning and push protection;
- CodeQL code scanning;
- a `main` branch ruleset with pull requests and review required;
- required checks for CI, license audit, package dry-run and CodeQL;
- blocked force-push and deletion on the protected branch;
- release notes and immutable releases as appropriate;
- least-privilege workflow token permissions.

Do not upload private CAD, local validation artifacts or the development repository history until the sanitization report passes.
