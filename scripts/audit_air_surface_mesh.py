"""Reproducible, non-mutating Gmsh audit for imported STEP surface warnings."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

import gmsh


VARIANTS = (
    {"name": "baseline", "size": 0.0625, "algorithm": 6},
    {"name": "delaunay", "size": 0.0625, "algorithm": 5},
    {"name": "frontal_fine", "size": 0.04, "algorithm": 6},
    {"name": "frontal_finer", "size": 0.025, "algorithm": 6},
    {"name": "curvature", "size": 0.0625, "algorithm": 6, "curvature": 20},
    {"name": "deduplicate", "size": 0.04, "algorithm": 6, "deduplicate": True},
    {"name": "heal_1e-8", "size": 0.04, "algorithm": 6, "heal": 1e-8},
    {"name": "heal_1e-6", "size": 0.04, "algorithm": 6, "heal": 1e-6},
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.step.resolve(strict=True)
    output = args.output.resolve(strict=False)
    output.mkdir(parents=True, exist_ok=True)
    results = []
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setString("Geometry.OCCTargetUnit", "M")
        for variant in VARIANTS:
            results.append(run_variant(source, variant))
    finally:
        gmsh.finalize()
    payload = {
        "source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "gmsh_version": gmsh.__version__,
        "method": "Official Gmsh Python API: OpenCASCADE import/heal/removeAllDuplicates and 2D meshing algorithms",
        "variants": results,
    }
    (output / "surface_mesh_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


def run_variant(source: Path, variant: dict[str, object]) -> dict[str, object]:
    model_name = f"air-audit-{variant['name']}"
    gmsh.model.add(model_name)
    record: dict[str, object] = dict(variant)
    gmsh.logger.start()
    try:
        gmsh.model.occ.importShapes(str(source))
        gmsh.model.occ.synchronize()
        before = topology()
        if variant.get("deduplicate"):
            gmsh.model.occ.removeAllDuplicates()
            gmsh.model.occ.synchronize()
        if "heal" in variant:
            gmsh.model.occ.healShapes(
                gmsh.model.getEntities(),
                tolerance=float(variant["heal"]),
                fixDegenerated=True,
                fixSmallEdges=True,
                fixSmallFaces=True,
                sewFaces=True,
                makeSolids=True,
            )
            gmsh.model.occ.synchronize()
        after = topology()
        gmsh.option.setNumber("Mesh.Algorithm", float(variant["algorithm"]))
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", float(variant.get("curvature", 0)))
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
        gmsh.model.mesh.setSize(gmsh.model.getEntities(0), float(variant["size"]))
        gmsh.model.mesh.generate(2)
        messages = tuple(gmsh.logger.get())
        nodes, _, _ = gmsh.model.mesh.getNodes()
        _types, element_tags, _nodes = gmsh.model.mesh.getElements(2)
        invalid = [message for message in messages if "remain invalid" in message]
        warning_surfaces = sorted(
            {int(value) for message in invalid for value in re.findall(r"surface (\d+)", message)}
        )
        record.update(
            status="completed",
            topology_before=before,
            topology_after=after,
            node_count=len(nodes),
            surface_element_count=sum(len(tags) for tags in element_tags),
            invalid_warnings=invalid,
            warning_surface_tags=warning_surfaces,
        )
    except Exception as error:
        record.update(status="failed", error=f"{type(error).__name__}: {error}")
    finally:
        try:
            gmsh.logger.stop()
        finally:
            gmsh.model.setCurrent(model_name)
            gmsh.model.remove()
    return record


def topology() -> dict[str, object]:
    volumes = gmsh.model.getEntities(3)
    surfaces = gmsh.model.getEntities(2)
    return {
        "volume_count": len(volumes),
        "surface_count": len(surfaces),
        "volume_m3": sum(float(gmsh.model.occ.getMass(3, tag)) for _, tag in volumes),
        "surface_area_m2": sum(float(gmsh.model.occ.getMass(2, tag)) for _, tag in surfaces),
    }


if __name__ == "__main__":
    raise SystemExit(main())
