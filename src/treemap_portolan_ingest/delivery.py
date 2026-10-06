"""Prepare validated Cloud Optimized GeoTIFFs for TreeMap delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4


DEFAULT_COG_DESTINATION = Path(
    r"\\afssxgtacnas104\TreeMap\08_Data_Delivery\06_COGs"
)
_BASE_CREATION_OPTIONS = (
    "COMPRESS=DEFLATE",
    "LEVEL=6",
    "PREDICTOR=YES",
    "OVERVIEW_COMPRESS=DEFLATE",
    "OVERVIEW_PREDICTOR=YES",
    "BLOCKSIZE=512",
    "BIGTIFF=IF_SAFER",
    "NUM_THREADS=ALL_CPUS",
    "OVERVIEWS=IGNORE_EXISTING",
)


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def load_metadata(path: Path) -> dict[str, str]:
    """Load the checked-in attribute kinds used to choose overview resampling."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    kinds = {
        str(attribute): str(values["kind"])
        for attribute, values in raw["attributes"].items()
    }
    unsupported = set(kinds.values()) - {"categorical", "continuous", "identifier"}
    if unsupported:
        raise ValueError(f"unsupported attribute kinds: {sorted(unsupported)}")
    return kinds


def overview_resampling(kind: str) -> str:
    """Return a GDAL overview resampling method for one metadata kind."""
    return {
        "categorical": "MODE",
        "continuous": "AVERAGE",
        "identifier": "NEAREST",
    }[kind]


def creation_options(kind: str) -> list[str]:
    """Return the exact lossless GDAL COG creation options for an attribute."""
    return [*_BASE_CREATION_OPTIONS, f"RESAMPLING={overview_resampling(kind)}"]


def _projection_sha256(projection: str) -> str:
    return hashlib.sha256(projection.encode("utf-8")).hexdigest()


def _same_nodata(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return left == right or (math.isnan(left) and math.isnan(right))


def raster_facts(path: Path) -> dict[str, Any]:
    """Read delivery-relevant raster and file facts."""
    from osgeo import gdal

    gdal.UseExceptions()
    dataset = gdal.OpenEx(str(path), gdal.OF_RASTER | gdal.OF_READONLY)
    if dataset is None:
        raise RuntimeError(f"GDAL could not open {path}")
    try:
        projection = dataset.GetProjectionRef() or ""
        band = dataset.GetRasterBand(1)
        if band is None:
            raise RuntimeError(f"raster has no band 1: {path}")
        stat = path.stat()
        image_structure = dataset.GetMetadata("IMAGE_STRUCTURE") or {}
        band_structure = band.GetMetadata("IMAGE_STRUCTURE") or {}
        return {
            "size_bytes": stat.st_size,
            "modified_utc": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
            "driver": dataset.GetDriver().ShortName,
            "width": dataset.RasterXSize,
            "height": dataset.RasterYSize,
            "band_count": dataset.RasterCount,
            "dtype": gdal.GetDataTypeName(band.DataType),
            "nodata": band.GetNoDataValue(),
            "transform": list(dataset.GetGeoTransform()),
            "projection_sha256": _projection_sha256(projection),
            "block_size": list(band.GetBlockSize()),
            "overview_sizes": [
                [overview.XSize, overview.YSize]
                for index in range(band.GetOverviewCount())
                if (overview := band.GetOverview(index)) is not None
            ],
            "compression": band_structure.get("COMPRESSION")
            or image_structure.get("COMPRESSION"),
            "layout": image_structure.get("LAYOUT"),
        }
    finally:
        dataset = None


def validate_cog(path: Path) -> dict[str, Any]:
    """Validate GeoTIFF structure with GDAL's reference COG validator."""
    from osgeo import gdal
    from osgeo_utils.samples.validate_cloud_optimized_geotiff import validate

    gdal.UseExceptions()
    dataset = gdal.OpenEx(str(path), gdal.OF_RASTER | gdal.OF_READONLY)
    if dataset is None:
        raise RuntimeError(f"GDAL could not open {path}")
    try:
        warnings, errors, details = validate(
            dataset, check_tiled=True, full_check=False
        )
        band = dataset.GetRasterBand(1)
        image_structure = dataset.GetMetadata("IMAGE_STRUCTURE") or {}
        if image_structure.get("LAYOUT") != "COG":
            errors.append("IMAGE_STRUCTURE LAYOUT is not COG")
        if band is not None and (dataset.RasterXSize > 512 or dataset.RasterYSize > 512):
            if band.GetOverviewCount() == 0:
                errors.append("large raster has no internal overviews")
        return {
            "valid": not errors,
            "errors": list(errors),
            "warnings": list(warnings),
            "details": details,
            "validator": "GDAL validate_cloud_optimized_geotiff",
            "full_check": False,
        }
    finally:
        dataset = None


def _assert_inventory_matches(asset: dict[str, Any], facts: dict[str, Any]) -> None:
    keys = (
        "size_bytes",
        "modified_utc",
        "width",
        "height",
        "band_count",
        "dtype",
        "transform",
        "projection_sha256",
        "block_size",
        "overview_sizes",
        "compression",
        "layout",
    )
    mismatches = [key for key in keys if asset.get(key) != facts.get(key)]
    if not _same_nodata(asset.get("nodata"), facts.get("nodata")):
        mismatches.append("nodata")
    if mismatches:
        raise ValueError(
            f"source differs from inventory for {asset['source_path']}: "
            + ", ".join(mismatches)
        )


def _assert_same_raster(source: Path, output: Path) -> dict[str, Any]:
    """Require identical CRS, grid, band types, nodata, and decoded pixel bytes."""
    from osgeo import gdal
    from osgeo import osr

    gdal.UseExceptions()
    source_ds = gdal.OpenEx(str(source), gdal.OF_RASTER | gdal.OF_READONLY)
    output_ds = gdal.OpenEx(str(output), gdal.OF_RASTER | gdal.OF_READONLY)
    if source_ds is None or output_ds is None:
        raise RuntimeError("GDAL could not open a raster for pixel validation")
    try:
        if (
            source_ds.RasterXSize,
            source_ds.RasterYSize,
            source_ds.RasterCount,
            tuple(source_ds.GetGeoTransform()),
        ) != (
            output_ds.RasterXSize,
            output_ds.RasterYSize,
            output_ds.RasterCount,
            tuple(output_ds.GetGeoTransform()),
        ):
            raise ValueError("converted raster grid differs from source")
        source_srs = osr.SpatialReference(wkt=source_ds.GetProjectionRef() or "")
        output_srs = osr.SpatialReference(wkt=output_ds.GetProjectionRef() or "")
        if not bool(source_srs.IsSame(output_srs)):
            raise ValueError("converted raster CRS differs from source")

        source_digest = hashlib.sha256()
        output_digest = hashlib.sha256()
        blocks_checked = 0
        for band_index in range(1, source_ds.RasterCount + 1):
            source_band = source_ds.GetRasterBand(band_index)
            output_band = output_ds.GetRasterBand(band_index)
            if source_band.DataType != output_band.DataType:
                raise ValueError(f"band {band_index} dtype differs from source")
            if not _same_nodata(source_band.GetNoDataValue(), output_band.GetNoDataValue()):
                raise ValueError(f"band {band_index} nodata differs from source")
            block_width, block_height = output_band.GetBlockSize()
            for y_offset in range(0, source_ds.RasterYSize, block_height):
                height = min(block_height, source_ds.RasterYSize - y_offset)
                for x_offset in range(0, source_ds.RasterXSize, block_width):
                    width = min(block_width, source_ds.RasterXSize - x_offset)
                    source_pixels = source_band.ReadRaster(
                        x_offset,
                        y_offset,
                        width,
                        height,
                        buf_xsize=width,
                        buf_ysize=height,
                        buf_type=source_band.DataType,
                    )
                    output_pixels = output_band.ReadRaster(
                        x_offset,
                        y_offset,
                        width,
                        height,
                        buf_xsize=width,
                        buf_ysize=height,
                        buf_type=output_band.DataType,
                    )
                    if source_pixels != output_pixels:
                        raise ValueError(
                            "converted pixel values differ at "
                            f"band {band_index}, x {x_offset}, y {y_offset}"
                        )
                    source_digest.update(source_pixels)
                    output_digest.update(output_pixels)
                    blocks_checked += 1
        return {
            "method": "blockwise decoded-byte equality with SHA-256",
            "blocks_checked": blocks_checked,
            "source_pixel_sha256": source_digest.hexdigest(),
            "output_pixel_sha256": output_digest.hexdigest(),
            "equal": True,
        }
    finally:
        source_ds = None
        output_ds = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_with_sha256(source: Path, target: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as source_stream, target.open("xb") as target_stream:
        while chunk := source_stream.read(8 * 1024 * 1024):
            target_stream.write(chunk)
            digest.update(chunk)
        target_stream.flush()
        os.fsync(target_stream.fileno())
    return digest.hexdigest()


def _partial_path(target: Path) -> Path:
    return target.with_name(f".{target.name}.{uuid4().hex}.partial")


def _copy_validate_rename(source: Path, target: Path) -> dict[str, Any]:
    """Copy bytes to a partial name, validate them, then publish the final name."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_path(target)
    try:
        copied_sha256 = _copy_with_sha256(source, partial)
        if partial.stat().st_size != source.stat().st_size:
            raise OSError(f"copied byte count differs for {source}")
        partial_sha256 = _sha256_file(partial)
        if partial_sha256 != copied_sha256:
            raise OSError(f"copied bytes differ for {source}")
        cog = validate_cog(partial)
        if not cog["valid"]:
            raise ValueError(f"partial destination is not a valid COG: {cog['errors']}")
        if target.exists():
            raise FileExistsError(f"refusing to overwrite existing target: {target}")
        partial.rename(target)
        return {
            "sha256": partial_sha256,
            "byte_validation": "source and partial destination SHA-256 match",
            "cog": cog,
        }
    finally:
        if partial.exists():
            partial.unlink()


def _source_fingerprint(asset: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source_path",
        "size_bytes",
        "modified_utc",
        "width",
        "height",
        "band_count",
        "dtype",
        "nodata",
        "transform",
        "projection_sha256",
        "cog_valid",
    )
    return {key: asset.get(key) for key in keys}


def _load_delivery_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported delivery manifest schema_version")
    return manifest


def _write_delivery_manifest(manifest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def delivery_plan(
    inventory: dict[str, Any],
    metadata_kinds: dict[str, str],
    destination: Path,
    years: frozenset[int] | None = None,
    attributes: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Build a deterministic COG delivery plan without writing files."""
    actions: list[dict[str, Any]] = []
    for asset in inventory["assets"]:
        year = int(asset["year"])
        attribute = str(asset["attribute"])
        if years is not None and year not in years:
            continue
        if attributes is not None and attribute not in attributes:
            continue
        if attribute not in metadata_kinds:
            raise ValueError(f"metadata missing attribute {attribute}")
        kind = metadata_kinds[attribute]
        target = destination / str(year) / f"TreeMap{year}_CONUS_{attribute}.tif"
        actions.append(
            {
                "year": year,
                "attribute": attribute,
                "kind": kind,
                "source": str(asset["source_path"]),
                "target": str(target),
                "operation": "copy" if asset["cog_valid"] else "convert",
                "overview_resampling": overview_resampling(kind),
                "creation_options": (
                    [] if asset["cog_valid"] else creation_options(kind)
                ),
                "size_bytes": int(asset["size_bytes"]),
                "status": "verify-existing" if target.exists() else "planned",
            }
        )
    return actions


def _verified_existing(
    target: Path,
    prior: dict[str, Any] | None,
    asset: dict[str, Any],
) -> dict[str, Any]:
    completed_statuses = {"delivered", "verified-existing"}
    if (
        prior is None
        or prior.get("status") not in completed_statuses
        or prior.get("pixel_validation", {}).get("equal") is not True
        or prior.get("source", {}).get("inventory_fingerprint")
        != _source_fingerprint(asset)
    ):
        raise FileExistsError(
            f"refusing existing target without a matching manifest record: {target}"
        )
    facts = raster_facts(target)
    cog = validate_cog(target)
    expected_sha256 = prior.get("output", {}).get("sha256")
    actual_sha256 = _sha256_file(target)
    if not cog["valid"] or not expected_sha256 or actual_sha256 != expected_sha256:
        raise FileExistsError(f"existing target failed manifest validation: {target}")
    return {"facts": facts, "cog": cog, "sha256": actual_sha256}


def prepare_cogs(
    inventory: dict[str, Any],
    inventory_path: Path,
    metadata_kinds: dict[str, str],
    metadata_path: Path,
    destination: Path,
    delivery_manifest_path: Path,
    years: frozenset[int] | None = None,
    attributes: frozenset[str] | None = None,
    confirm: bool = False,
) -> list[dict[str, Any]]:
    """Preview or execute guarded, resumable COG delivery."""
    actions = delivery_plan(
        inventory, metadata_kinds, destination, years=years, attributes=attributes
    )
    if not confirm:
        return actions

    from osgeo import gdal

    if gdal.GetDriverByName("COG") is None:
        raise RuntimeError("GDAL COG driver is unavailable")
    prior_manifest = _load_delivery_manifest(delivery_manifest_path)
    if prior_manifest is not None and Path(prior_manifest["destination"]) != destination:
        raise ValueError("delivery manifest destination does not match --destination")
    manifest = prior_manifest or {
        "schema_version": 1,
        "created_utc": _utc_now(),
        "assets": [],
    }
    manifest.update(
        {
            "updated_utc": _utc_now(),
            "inventory_path": str(inventory_path),
            "metadata_path": str(metadata_path),
            "destination": str(destination),
            "gdal_version": gdal.VersionInfo("--version"),
        }
    )
    prior_records = {
        (record["year"], record["attribute"]): record
        for record in manifest.get("assets", [])
    }
    records = dict(prior_records)

    for action in actions:
        year = action["year"]
        attribute = action["attribute"]
        asset = next(
            item
            for item in inventory["assets"]
            if int(item["year"]) == year and item["attribute"] == attribute
        )
        source = Path(action["source"])
        target = Path(action["target"])
        record: dict[str, Any] = {
            **action,
            "source": {
                "inventory_fingerprint": _source_fingerprint(asset),
            },
            "status": "in-progress",
            "started_utc": _utc_now(),
        }
        records[(year, attribute)] = record
        manifest["assets"] = [records[key] for key in sorted(records)]
        _write_delivery_manifest(manifest, delivery_manifest_path)
        try:
            source_facts = raster_facts(source)
            _assert_inventory_matches(asset, source_facts)
            source_cog = validate_cog(source)
            record["source"].update({"facts": source_facts, "cog": source_cog})

            if target.exists():
                verified = _verified_existing(
                    target, prior_records.get((year, attribute)), asset
                )
                record.update(
                    {
                        "operation": prior_records[(year, attribute)]["operation"],
                        "creation_options": prior_records[(year, attribute)].get(
                            "creation_options", []
                        ),
                        "pixel_validation": prior_records[(year, attribute)][
                            "pixel_validation"
                        ],
                        "output": verified,
                        "status": "verified-existing",
                        "completed_utc": _utc_now(),
                    }
                )
            else:
                operation = "copy" if source_cog["valid"] else "convert"
                record["operation"] = operation
                if operation == "copy":
                    record["creation_options"] = []
                    transfer = _copy_validate_rename(source, target)
                    record["pixel_validation"] = {
                        "method": "whole-file SHA-256 equality",
                        "equal": True,
                    }
                else:
                    options = creation_options(action["kind"])
                    record["creation_options"] = options
                    with tempfile.TemporaryDirectory(
                        prefix="treemap-cog-"
                    ) as temporary_directory:
                        local_cog = Path(temporary_directory) / target.name
                        result = gdal.Translate(
                            str(local_cog),
                            str(source),
                            format="COG",
                            creationOptions=options,
                        )
                        if result is None:
                            raise RuntimeError(f"GDAL COG conversion failed for {source}")
                        result = None
                        local_cog_validation = validate_cog(local_cog)
                        if not local_cog_validation["valid"]:
                            raise ValueError(
                                "local converted file is not a valid COG: "
                                f"{local_cog_validation['errors']}"
                            )
                        pixel_validation = _assert_same_raster(source, local_cog)
                        transfer = _copy_validate_rename(local_cog, target)
                        record["local_cog_validation"] = local_cog_validation
                        record["pixel_validation"] = pixel_validation
                record.update(
                    {
                        "output": {
                            "facts": raster_facts(target),
                            "cog": transfer["cog"],
                            "sha256": transfer["sha256"],
                            "byte_validation": transfer["byte_validation"],
                        },
                        "status": "delivered",
                        "completed_utc": _utc_now(),
                    }
                )
        except Exception as error:
            record.update(
                {
                    "status": "failed",
                    "error": f"{type(error).__name__}: {error}",
                    "completed_utc": _utc_now(),
                }
            )
            manifest["updated_utc"] = _utc_now()
            manifest["assets"] = [records[key] for key in sorted(records)]
            _write_delivery_manifest(manifest, delivery_manifest_path)
            raise
        manifest["updated_utc"] = _utc_now()
        manifest["assets"] = [records[key] for key in sorted(records)]
        _write_delivery_manifest(manifest, delivery_manifest_path)
    return [records[(action["year"], action["attribute"])] for action in actions]
