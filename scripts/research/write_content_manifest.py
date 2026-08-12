"""Write or verify a deterministic SHA-256 manifest for an evidence directory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


MANIFEST_NAME = "content-sha256.json"
HASH_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path, output: Path) -> dict[str, object]:
    files = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if not path.is_file() or path.resolve() == output.resolve():
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema_version": 1,
        "algorithm": "sha256",
        "files": files,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("directory", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.directory.resolve()
    if not root.is_dir():
        print(f"evidence directory does not exist: {root}", file=sys.stderr)
        return 2

    output = root / MANIFEST_NAME
    actual = build_manifest(root, output)
    if args.verify:
        if not output.is_file():
            print(f"manifest does not exist: {output}", file=sys.stderr)
            return 2
        try:
            expected = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"manifest cannot be read: {error}", file=sys.stderr)
            return 2
        if expected != actual:
            print(f"manifest verification failed: {output}", file=sys.stderr)
            return 1
        print(f"manifest verified: {output}")
        return 0

    output.write_text(
        json.dumps(actual, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"manifest written: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
