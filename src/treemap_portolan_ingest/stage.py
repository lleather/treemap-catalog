"""Guarded staging of validated TreeMap COGs into the catalog layout."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any


def load_inventory(path: Path) -> dict[str, Any]:
    """Load an inventory that is safe to use for COG delivery."""
    inventory = json.loads(path.read_text(encoding="utf-8"))
    if inventory.get("schema_version") != 1:
        raise ValueError("unsupported inventory schema_version")
    issues = inventory.get("issues", [])
    if issues:
        raise ValueError(f"inventory contains {len(issues)} issue(s)")
    return inventory


def load_delivery_manifest(path: Path) -> dict[str, Any]:
    """Load a complete delivery manifest that is safe to stage."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported delivery manifest schema_version")
    records = manifest.get("assets", [])
    incomplete = [
        f"{record.get('year')}/{record.get('attribute')}"
        for record in records
        if record.get("status") not in {"delivered", "verified-existing"}
        or record.get("pixel_validation", {}).get("equal") is not True
        or record.get("output", {}).get("cog", {}).get("valid") is not True
    ]
    if incomplete:
        raise ValueError(
            "delivery manifest contains incomplete or invalid assets: "
            + ", ".join(incomplete)
        )
    return manifest


def stage_plan(
    manifest: dict[str, Any],
    destination: Path,
    years: frozenset[int] | None = None,
    attributes: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic copy decisions without modifying the filesystem."""
    actions: list[dict[str, Any]] = []
    for record in manifest["assets"]:
        year = int(record["year"])
        attribute = str(record["attribute"])
        if years is not None and year not in years:
            continue
        if attributes is not None and attribute not in attributes:
            continue
        source = Path(record["target"])
        expected_size = int(record["output"]["facts"]["size_bytes"])
        expected_sha256 = str(record["output"]["sha256"])
        target = destination / str(year) / f"TreeMap{year}_CONUS_{attribute}.tif"
        status = "copy"
        if target.exists():
            same_size = target.stat().st_size == expected_size
            if same_size:
                status = "skip"
            else:
                status = "refuse-existing"
        actions.append(
            {
                "year": year,
                "attribute": attribute,
                "source": str(source),
                "target": str(target),
                "size_bytes": expected_size,
                "sha256": expected_sha256,
                "post_copy_action": "retain",
                "status": status,
            }
        )
    return actions


def apply_stage_plan(actions: list[dict[str, Any]]) -> None:
    """Copy validated COGs and verify each staged copy against its manifest."""
    conflicts = [action for action in actions if action["status"] == "refuse-existing"]
    if conflicts:
        targets = ", ".join(action["target"] for action in conflicts)
        raise FileExistsError(f"refusing to overwrite existing targets: {targets}")
    for action in actions:
        if action["status"] == "skip":
            continue
        source = Path(action["source"])
        target = Path(action["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".partial")
        if temporary.exists():
            temporary.unlink()
        digest = hashlib.sha256()
        try:
            with source.open("rb") as source_stream, temporary.open("xb") as target_stream:
                while chunk := source_stream.read(8 * 1024 * 1024):
                    target_stream.write(chunk)
                    digest.update(chunk)
            if temporary.stat().st_size != action["size_bytes"]:
                raise OSError(f"staged byte count differs for {source}")
            if digest.hexdigest() != action["sha256"]:
                raise OSError(f"staged SHA-256 differs for {source}")
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()
