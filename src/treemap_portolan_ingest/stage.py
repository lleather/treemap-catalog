"""Guarded staging of selected TreeMap rasters into the catalog layout."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any


def load_inventory(path: Path) -> dict[str, Any]:
    """Load an inventory that is safe to use for staging."""
    inventory = json.loads(path.read_text(encoding="utf-8"))
    if inventory.get("schema_version") != 1:
        raise ValueError("unsupported inventory schema_version")
    issues = inventory.get("issues", [])
    if issues:
        raise ValueError(f"inventory contains {len(issues)} issue(s)")
    return inventory


def stage_plan(
    inventory: dict[str, Any],
    destination: Path,
    years: frozenset[int] | None = None,
    attributes: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic copy decisions without modifying the filesystem."""
    actions: list[dict[str, Any]] = []
    for asset in inventory["assets"]:
        year = int(asset["year"])
        attribute = str(asset["attribute"])
        if years is not None and year not in years:
            continue
        if attributes is not None and attribute not in attributes:
            continue
        target = destination / str(year) / f"TreeMap{year}_CONUS_{attribute}.tif"
        status = "copy"
        if target.exists():
            same_size = target.stat().st_size == asset["size_bytes"]
            if same_size:
                status = "skip"
            elif asset["cog_valid"]:
                status = "replace"
            else:
                status = "review-existing-conversion"
        actions.append(
            {
                "year": year,
                "attribute": attribute,
                "source": asset["source_path"],
                "target": str(target),
                "size_bytes": asset["size_bytes"],
                "source_cog_valid": bool(asset["cog_valid"]),
                "post_copy_action": (
                    "retain" if asset["cog_valid"] else "convert-staged-copy-to-cog"
                ),
                "status": status,
            }
        )
    return actions


def apply_stage_plan(actions: list[dict[str, Any]]) -> None:
    """Copy or replace selected files while never changing the source."""
    reviews = [
        action for action in actions if action["status"] == "review-existing-conversion"
    ]
    if reviews:
        targets = ", ".join(action["target"] for action in reviews)
        raise FileExistsError(
            "refusing to overwrite possible converted COGs; review: " + targets
        )
    for action in actions:
        if action["status"] == "skip":
            continue
        source = Path(action["source"])
        target = Path(action["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".partial")
        if temporary.exists():
            temporary.unlink()
        shutil.copy2(source, temporary)
        if temporary.stat().st_size != action["size_bytes"]:
            temporary.unlink()
            raise OSError(f"staged byte count differs for {source}")
        temporary.replace(target)
