"""Read-only inventory of TreeMap delivery rasters."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any


_FILENAME = re.compile(
    r"^TreeMap(?P<year>\d{4})(?:_CONUS)?_(?P<attribute>.+)\.tiff?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IngestConfig:
    """Checked-in rules that select source rasters."""

    source_root: Path
    collection_id: str
    years: tuple[int, ...]
    source_directories: dict[int, Path]
    common_attributes: tuple[str, ...]
    year_attributes: dict[int, tuple[str, ...]]
    source_aliases: dict[int, dict[str, str]]
    ignored_name_suffixes: tuple[str, ...]

    def expected_attributes(self, year: int) -> frozenset[str]:
        """Return the expected publication asset keys for one year."""
        return frozenset(self.common_attributes + self.year_attributes[year])


@dataclass(frozen=True)
class SourceRaster:
    """A selected source raster and its normalized publication key."""

    year: int
    source_attribute: str
    attribute: str
    path: Path


def load_config(path: Path) -> IngestConfig:
    """Load and validate an ingest configuration file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    years = tuple(int(year) for year in raw["years"])
    year_attributes = {
        int(year): tuple(attributes)
        for year, attributes in raw["year_attributes"].items()
    }
    missing_years = set(years) - set(year_attributes)
    if missing_years:
        raise ValueError(f"year_attributes missing years: {sorted(missing_years)}")
    source_directories = {
        int(year): Path(directory)
        for year, directory in raw.get("source_directories", {}).items()
    }
    missing_source_directories = set(years) - set(source_directories)
    if missing_source_directories:
        raise ValueError(
            "source_directories missing years: "
            f"{sorted(missing_source_directories)}"
        )
    return IngestConfig(
        source_root=Path(raw["source_root"]),
        collection_id=str(raw["collection_id"]),
        years=years,
        source_directories=source_directories,
        common_attributes=tuple(raw["common_attributes"]),
        year_attributes=year_attributes,
        source_aliases={
            int(year): {str(key): str(value) for key, value in aliases.items()}
            for year, aliases in raw.get("source_aliases", {}).items()
        },
        ignored_name_suffixes=tuple(raw.get("ignored_name_suffixes", [])),
    )


def parse_source_name(path: Path, config: IngestConfig) -> tuple[int, str, str]:
    """Parse a source filename into year, source attribute, and public key."""
    match = _FILENAME.match(path.name)
    if match is None:
        raise ValueError(f"unrecognized TreeMap TIFF name: {path.name}")
    year = int(match.group("year"))
    source_attribute = match.group("attribute")
    for suffix in config.ignored_name_suffixes:
        if source_attribute.lower().endswith(suffix.lower()):
            source_attribute = source_attribute[: -len(suffix)]
            break
    source_attribute = source_attribute.upper()
    aliased_attribute = config.source_aliases.get(year, {}).get(
        source_attribute, source_attribute
    )
    canonical_attributes = {
        attribute.casefold(): attribute for attribute in config.expected_attributes(year)
    }
    attribute = canonical_attributes.get(
        aliased_attribute.casefold(), aliased_attribute
    )
    return year, source_attribute, attribute


def discover_sources(config: IngestConfig) -> tuple[list[SourceRaster], list[str]]:
    """Select top-level annual TIFFs without descending into legacy subfolders."""
    selected: list[SourceRaster] = []
    issues: list[str] = []
    for year in config.years:
        year_dir = config.source_root / config.source_directories[year]
        if not year_dir.is_dir():
            issues.append(f"missing year directory: {year_dir}")
            continue
        by_attribute: dict[str, list[SourceRaster]] = {}
        for path in sorted(year_dir.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() not in {".tif", ".tiff"}:
                continue
            try:
                parsed_year, source_attribute, attribute = parse_source_name(path, config)
            except ValueError as error:
                issues.append(str(error))
                continue
            if parsed_year != year:
                issues.append(
                    f"filename year {parsed_year} does not match directory {year}: {path}"
                )
                continue
            raster = SourceRaster(year, source_attribute, attribute, path)
            by_attribute.setdefault(attribute, []).append(raster)

        expected = config.expected_attributes(year)
        actual = set(by_attribute)
        for attribute in sorted(expected - actual):
            issues.append(f"{year}: missing expected attribute {attribute}")
        for attribute in sorted(actual - expected):
            issues.append(f"{year}: unexpected attribute {attribute}")
        for attribute, candidates in sorted(by_attribute.items()):
            if len(candidates) > 1:
                paths = ", ".join(str(candidate.path) for candidate in candidates)
                issues.append(f"{year}: duplicate attribute {attribute}: {paths}")
            elif attribute in expected:
                selected.append(candidates[0])
    return selected, issues


def _projection_id(dataset: Any) -> tuple[str | None, str]:
    projection = dataset.GetProjectionRef() or ""
    digest = hashlib.sha256(projection.encode("utf-8")).hexdigest()
    if not projection:
        return None, digest
    from osgeo import osr

    spatial_ref = osr.SpatialReference(wkt=projection)
    try:
        spatial_ref.AutoIdentifyEPSG()
    except RuntimeError:
        # Some valid custom WKT definitions have no EPSG authority match.
        pass
    authority_name = spatial_ref.GetAuthorityName(None)
    authority_code = spatial_ref.GetAuthorityCode(None)
    identifier = (
        f"{authority_name}:{authority_code}"
        if authority_name is not None and authority_code is not None
        else spatial_ref.GetName()
    )
    return identifier, digest


def inspect_raster(source: SourceRaster) -> dict[str, Any]:
    """Read raster headers and return JSON-serializable facts without pixels."""
    try:
        from osgeo import gdal
    except ImportError as error:  # pragma: no cover - environment failure
        raise RuntimeError(
            "GDAL Python bindings are required for raster inspection"
        ) from error

    gdal.UseExceptions()
    dataset = gdal.OpenEx(str(source.path), gdal.OF_RASTER | gdal.OF_READONLY)
    if dataset is None:
        raise RuntimeError(f"GDAL could not open {source.path}")
    try:
        band = dataset.GetRasterBand(1)
        if band is None:
            raise RuntimeError(f"raster has no band 1: {source.path}")
        stat = source.path.stat()
        image_structure = dataset.GetMetadata("IMAGE_STRUCTURE") or {}
        band_structure = band.GetMetadata("IMAGE_STRUCTURE") or {}
        block_size = list(band.GetBlockSize())
        overview_sizes = [
            [overview.XSize, overview.YSize]
            for index in range(band.GetOverviewCount())
            if (overview := band.GetOverview(index)) is not None
        ]
        projection, projection_sha256 = _projection_id(dataset)
        layout = image_structure.get("LAYOUT")
        tiled = block_size[0] < dataset.RasterXSize or block_size[1] < dataset.RasterYSize
        cog_valid = layout == "COG" and tiled and bool(overview_sizes)
        return {
            "year": source.year,
            "source_attribute": source.source_attribute,
            "attribute": source.attribute,
            "source_path": str(source.path),
            "source_relative_path": str(source.path.relative_to(source.path.parents[1])),
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
            "projection": projection,
            "projection_sha256": projection_sha256,
            "block_size": block_size,
            "overview_sizes": overview_sizes,
            "compression": band_structure.get("COMPRESSION")
            or image_structure.get("COMPRESSION"),
            "layout": layout,
            "cog_valid": cog_valid,
        }
    finally:
        dataset = None


def _grid_signature(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record["width"],
        record["height"],
        tuple(record["transform"]),
        record["projection_sha256"],
    )


def build_inventory(config: IngestConfig, workers: int = 1) -> dict[str, Any]:
    """Discover and inspect configured sources, then summarize validation issues."""
    sources, issues = discover_sources(config)
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if workers == 1:
        records = [inspect_raster(source) for source in sources]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            records = list(executor.map(inspect_raster, sources))
    records.sort(key=lambda record: (record["year"], record["attribute"]))

    for year in config.years:
        annual = [record for record in records if record["year"] == year]
        signatures = {_grid_signature(record) for record in annual}
        if len(signatures) > 1:
            issues.append(f"{year}: selected rasters do not share one grid")
        if len(annual) != len(config.expected_attributes(year)):
            issues.append(
                f"{year}: selected {len(annual)} assets; expected "
                f"{len(config.expected_attributes(year))}"
            )

    return {
        "schema_version": 1,
        "created_utc": datetime.now(tz=timezone.utc).isoformat(),
        "source_root": str(config.source_root),
        "collection_id": config.collection_id,
        "years": list(config.years),
        "summary": {
            "asset_count": len(records),
            "total_bytes": sum(record["size_bytes"] for record in records),
            "cog_count": sum(bool(record["cog_valid"]) for record in records),
            "issue_count": len(issues),
        },
        "issues": sorted(set(issues)),
        "assets": records,
    }


def write_manifest(inventory: dict[str, Any], path: Path) -> None:
    """Write a stable, human-readable inventory manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
