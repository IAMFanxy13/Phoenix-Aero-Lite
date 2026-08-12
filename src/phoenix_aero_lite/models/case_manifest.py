"""Atomic strict-JSON manifest for resumable CFD cases."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from phoenix_aero_lite.utilities.source_guard import sha256_file


class CaseManifestError(ValueError):
    """Stable manifest validation or publication failure."""


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    path: str
    sha256: str
    size: int

    @classmethod
    def from_path(cls, path: Path) -> "ArtifactRecord":
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise CaseManifestError("MANIFEST_ARTIFACT_INVALID")
        return cls(
            path=str(resolved),
            sha256=sha256_file(resolved),
            size=resolved.stat().st_size,
        )

    def is_valid(self) -> bool:
        path = Path(self.path)
        return (
            path.is_file()
            and path.stat().st_size == self.size
            and sha256_file(path) == self.sha256
        )


@dataclass(frozen=True, slots=True)
class StepRecord:
    status: str
    artifacts: tuple[ArtifactRecord, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    input_fingerprint: str | None = None
    producer_id: str | None = None

    def is_reusable(self, expected_fingerprint: str | None = None) -> bool:
        return (
            self.status == "complete"
            and bool(self.artifacts)
            and all(artifact.is_valid() for artifact in self.artifacts)
            and (
                expected_fingerprint is None
                or self.input_fingerprint == expected_fingerprint
            )
        )


@dataclass(slots=True)
class CaseManifest:
    schema_version: int
    fingerprint: str
    steps: dict[str, StepRecord]
    provenance: dict[str, object] = field(default_factory=dict)

    @classmethod
    def empty(
        cls,
        fingerprint: str,
        provenance: Mapping[str, object] | None = None,
    ) -> "CaseManifest":
        _validate_fingerprint(fingerprint)
        return cls(4, fingerprint.lower(), {}, dict(provenance or {}))

    @classmethod
    def load_or_new(
        cls,
        path: Path,
        fingerprint: str,
        provenance: Mapping[str, object] | None = None,
    ) -> "CaseManifest":
        _validate_fingerprint(fingerprint)
        if not path.is_file():
            return cls.empty(fingerprint, provenance)
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=_reject_constant,
            )
            manifest = cls(
                schema_version=int(payload["schema_version"]),
                fingerprint=str(payload["fingerprint"]),
                steps={
                    name: StepRecord(
                        status=record["status"],
                        artifacts=tuple(
                            ArtifactRecord(
                                path=item["path"],
                                sha256=item["sha256"],
                                size=int(item["size"]),
                            )
                            for item in record.get("artifacts", ())
                        ),
                        metadata=dict(record.get("metadata", {})),
                        input_fingerprint=record.get("input_fingerprint"),
                        producer_id=record.get("producer_id"),
                    )
                    for name, record in payload.get("steps", {}).items()
                },
                provenance=dict(payload.get("provenance", {})),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise CaseManifestError("MANIFEST_INVALID") from None
        if manifest.schema_version not in {1, 2, 3, 4}:
            raise CaseManifestError("MANIFEST_VERSION_UNSUPPORTED")
        if manifest.fingerprint.lower() != fingerprint.lower():
            return cls.empty(fingerprint, provenance)
        manifest.schema_version = 4
        if provenance is not None:
            manifest.provenance = dict(provenance)
        return manifest

    def save_atomic(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "fingerprint": self.fingerprint,
            "provenance": dict(self.provenance),
            "steps": {
                name: {
                    "status": record.status,
                    "artifacts": [
                        {
                            "path": artifact.path,
                            "sha256": artifact.sha256,
                            "size": artifact.size,
                        }
                        for artifact in record.artifacts
                    ],
                    "metadata": dict(record.metadata),
                    "input_fingerprint": record.input_fingerprint,
                    "producer_id": record.producer_id,
                }
                for name, record in sorted(self.steps.items())
            },
        }
        try:
            encoded = json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8")
        except (TypeError, ValueError):
            raise CaseManifestError("MANIFEST_DATA_INVALID") from None
        temporary = path.parent / f".{path.name}.tmp-{uuid4().hex}"
        try:
            with temporary.open("xb") as destination:
                destination.write(encoded)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary, path)
        except OSError:
            raise CaseManifestError("MANIFEST_WRITE_FAILED") from None


def _validate_fingerprint(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise CaseManifestError("MANIFEST_FINGERPRINT_INVALID")


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON")
