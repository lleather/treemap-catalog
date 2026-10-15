"""Enrich generated TreeMap STAC metadata from the checked-in registry."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any

from .dictionary import load_attribute_dictionary
from .rat import validate_rat_outputs


CLASSIFICATION_EXTENSION = (
    "https://stac-extensions.github.io/classification/v2.0.0/schema.json"
)
SCIENTIFIC_EXTENSION = "https://stac-extensions.github.io/scientific/v1.0.0/schema.json"
TABLE_EXTENSION = "https://stac-extensions.github.io/table/v1.2.0/schema.json"
_ASSET_NAME = re.compile(r"^TreeMap(?P<year>\d{4})_CONUS_(?P<attribute>.+)\.tif$")
_GDAL_DATA_TYPES = {
    "byte": "uint8",
}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        for attempt in range(10):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.2)
    finally:
        if temporary.exists():
            temporary.unlink()


def _classes(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    names = raw["class_names"]
    values = raw["class_values"]
    colors = raw.get("class_palette", [None] * len(values))
    if not (len(names) == len(values) == len(colors)):
        raise ValueError(f"class definition arrays differ in length: {path}")
    classes = []
    for value, name, color in zip(values, names, colors, strict=True):
        entry: dict[str, Any] = {"value": int(value), "name": str(name)}
        if color is not None:
            entry["color_hint"] = str(color).lstrip("#")
        classes.append(entry)
    return classes


def _class_source(repository_root: Path, configured_path: str) -> Path:
    return (repository_root / configured_path).resolve()


def _ensure_extension(stac: dict[str, Any], extension: str) -> None:
    extensions = stac.setdefault("stac_extensions", [])
    if extension not in extensions:
        extensions.append(extension)


def _ensure_table_extension(stac: dict[str, Any]) -> None:
    extensions = stac.setdefault("stac_extensions", [])
    extensions[:] = [
        extension
        for extension in extensions
        if not extension.startswith("https://stac-extensions.github.io/table/")
    ]
    extensions.append(TABLE_EXTENSION)


def _raster_band(path: Path) -> dict[str, Any]:
    """Read embedded band metadata without computing statistics."""
    from osgeo import gdal

    gdal.UseExceptions()
    dataset = gdal.OpenEx(str(path), gdal.OF_RASTER | gdal.OF_READONLY)
    if dataset is None:
        raise RuntimeError(f"GDAL could not open {path}")
    try:
        if dataset.RasterCount != 1:
            raise ValueError(f"expected one raster band: {path}")
        band = dataset.GetRasterBand(1)
        result: dict[str, Any] = {
            "data_type": _GDAL_DATA_TYPES.get(
                gdal.GetDataTypeName(band.DataType).lower(),
                gdal.GetDataTypeName(band.DataType).lower(),
            ),
        }
        nodata = band.GetNoDataValue()
        if nodata is not None:
            result["nodata"] = nodata
        statistics = band.GetStatistics(False, False)
        if statistics is not None:
            minimum, maximum, mean, stddev = statistics
            result["statistics"] = {
                "minimum": minimum,
                "maximum": maximum,
                "mean": mean,
                "stddev": stddev,
            }
        return result
    finally:
        dataset = None


def _register_rat_assets(
    item: dict[str, Any],
    item_directory: Path,
    config: dict[str, Any],
) -> int:
    facts = validate_rat_outputs(config, item_directory)
    year = item["id"]
    columns = [
        {
            key: value
            for key, value in column.items()
            if key in {"name", "type", "description", "unit"}
        }
        for column in config["columns"]
    ]
    assets = item.setdefault("assets", {})
    assets["raster-attribute-table-csv"] = {
        "href": f"./{config['csv_name']}",
        "type": "text/csv",
        "title": f"TreeMap {year} Raster Attribute Table source CSV",
        "description": (
            "Original TreeMap 2023 Raster Attribute Table. "
            "Join TM_ID to FIA PLT_CN."
        ),
        "roles": ["metadata", "source"],
        "file:size": facts["csv"]["size"],
        "file:checksum": f"1220{facts['csv']['sha256']}",
        "table:row_count": facts["row_count"],
        "table:columns": columns,
    }
    assets["raster-attribute-table-parquet"] = {
        "href": f"./{config['parquet_name']}",
        "type": "application/vnd.apache.parquet",
        "title": f"TreeMap {year} Raster Attribute Table",
        "description": (
            "Query-optimized copy of the TreeMap 2023 Raster Attribute Table. "
            "Join TM_ID to FIA PLT_CN."
        ),
        "roles": ["metadata"],
        "file:size": facts["parquet"]["size"],
        "file:checksum": f"1220{facts['parquet']['sha256']}",
        "table:row_count": facts["row_count"],
        "table:columns": columns,
    }
    _ensure_table_extension(item)
    return 2


def enrich_catalog(
    catalog_root: Path,
    metadata_path: Path,
    years: frozenset[int] | None = None,
) -> dict[str, int]:
    """Enrich selected annual items and their collection from registry metadata."""
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    repository_root = metadata_path.resolve().parent.parent
    collection_path = catalog_root / "treemap" / "collection.json"
    collection = json.loads(collection_path.read_text(encoding="utf-8"))
    collection["title"] = metadata["catalog"]["title"]
    dictionary_config = metadata.get("attribute_dictionary")
    attribute_dictionary: dict[str, dict[str, str]] = {}
    dictionary_facts: dict[str, Any] | None = None
    if dictionary_config is not None:
        attribute_dictionary, dictionary_facts = load_attribute_dictionary(
            dictionary_config,
            collection_path.parent,
        )
    selected_years = [
        int(year_text)
        for year_text in metadata["years"]
        if years is None or int(year_text) in years
    ]
    if not selected_years:
        raise ValueError("no metadata years selected")
    year_list = ", ".join(str(year) for year in selected_years)
    rat_years = [
        year
        for year in selected_years
        if str(year) in metadata.get("raster_attribute_tables", {})
    ]
    collection["description"] = (
        "TreeMap 30-meter forest attribute rasters for the conterminous "
        f"United States. This publication contains the {year_list} vintage"
        f"{'s' if len(selected_years) != 1 else ''}."
    )
    if rat_years:
        rat_year_list = ", ".join(str(year) for year in rat_years)
        collection["description"] += (
            f" The {rat_year_list} item"
            f"{'s' if len(rat_years) != 1 else ''} include"
            f"{'' if len(rat_years) != 1 else 's'} a Raster Attribute Table "
            "in CSV and Parquet."
        )
    if dictionary_config is not None:
        collection["description"] += (
            " A collection-level CSV provides the attribute data dictionary."
        )
    collection["extent"]["spatial"]["bbox"] = [metadata["catalog"]["spatial_extent"]]
    collection["extent"]["temporal"]["interval"] = [
        [
            f"{min(selected_years)}-01-01T00:00:00Z",
            f"{max(selected_years)}-12-31T23:59:59Z",
        ]
    ]
    collection["updated"] = datetime.now(timezone.utc).isoformat()

    item_count = 0
    asset_count = 0
    collection_thumbnail_source: Path | None = None
    for year_text, year_metadata in metadata["years"].items():
        year = int(year_text)
        if years is not None and year not in years:
            continue
        item_path = catalog_root / "treemap" / year_text / f"{year_text}.json"
        item = json.loads(item_path.read_text(encoding="utf-8"))
        item["title"] = f"TreeMap {year}"
        properties = item["properties"]
        properties.pop("title", None)
        properties["datetime"] = None
        properties["start_datetime"] = f"{year}-01-01T00:00:00Z"
        properties["end_datetime"] = f"{year}-12-31T23:59:59Z"
        for key, value in year_metadata.items():
            if key != "doi":
                properties[f"treemap:{key}"] = value
        doi = year_metadata["doi"]
        properties["sci:doi"] = doi.removeprefix("https://doi.org/")
        properties["sci:citation"] = f"USDA Forest Service. TreeMap {year}. {doi}"
        _ensure_extension(item, SCIENTIFIC_EXTENSION)
        links = item.setdefault("links", [])
        if not any(link.get("rel") == "cite-as" for link in links):
            links.append(
                {
                    "rel": "cite-as",
                    "href": doi,
                    "type": "text/html",
                    "title": f"TreeMap {year} data publication",
                }
            )

        for asset in item["assets"].values():
            if (
                collection_thumbnail_source is None
                and "thumbnail" in asset.get("roles", [])
            ):
                candidate = item_path.parent / asset["href"]
                if candidate.exists():
                    collection_thumbnail_source = candidate
            match = _ASSET_NAME.match(Path(asset["href"]).name)
            if match is None or int(match.group("year")) != year:
                continue
            attribute = match.group("attribute")
            attribute_metadata = metadata["attributes"][attribute]
            asset["title"] = attribute_metadata["title"]
            dictionary_record = attribute_dictionary.get(attribute)
            if dictionary_record is not None:
                short_description = dictionary_record.get("Short description", "")
                if short_description:
                    asset["description"] = short_description
            bands = asset.setdefault("bands", [{}])
            if len(bands) != 1:
                raise ValueError(f"expected one band for {item_path}: {attribute}")
            band = bands[0]
            asset_path = item_path.parent / asset["href"]
            if asset_path.exists():
                band.update(_raster_band(asset_path))
            band["name"] = attribute
            if dictionary_record is None:
                band["description"] = attribute_metadata["title"]
            else:
                band["description"] = (
                    dictionary_record.get("Long Description")
                    or dictionary_record.get("Short description")
                    or attribute_metadata["title"]
                )
                source = dictionary_record.get(
                    "Source (table/column/query); Sec = FIADB manual section"
                )
                if source:
                    band["treemap:source"] = source
            unit = attribute_metadata.get("unit")
            if unit is not None:
                band["unit"] = unit
            classes_source = attribute_metadata.get("classes_source")
            if classes_source:
                band["classification:classes"] = _classes(
                    _class_source(repository_root, classes_source)
                )
                _ensure_extension(item, CLASSIFICATION_EXTENSION)
            asset_count += 1
        rat_config = metadata.get("raster_attribute_tables", {}).get(year_text)
        if rat_config is not None:
            asset_count += _register_rat_assets(item, item_path.parent, rat_config)
        _write_json(item_path, item)
        item_count += 1

    if dictionary_config is not None and dictionary_facts is not None:
        collection.setdefault("assets", {})["attribute-data-dictionary"] = {
            "href": f"./{dictionary_config['csv_name']}",
            "type": "text/csv",
            "title": dictionary_config["title"],
            "description": dictionary_config["description"],
            "roles": ["metadata"],
            "file:size": dictionary_facts["size"],
            "file:checksum": f"1220{dictionary_facts['sha256']}",
        }

    if collection_thumbnail_source is not None:
        thumbnail_path = collection_path.parent / "thumbnail.jpg"
        shutil.copyfile(collection_thumbnail_source, thumbnail_path)
        checksum = hashlib.sha256(thumbnail_path.read_bytes()).hexdigest()
        collection.setdefault("assets", {})["thumbnail"] = {
            "href": "./thumbnail.jpg",
            "type": "image/jpeg",
            "title": f"TreeMap {max(selected_years)} preview",
            "roles": ["thumbnail"],
            "file:size": thumbnail_path.stat().st_size,
            "file:checksum": f"1220{checksum}",
        }
    _write_json(collection_path, collection)
    root_catalog_path = catalog_root / "catalog.json"
    if root_catalog_path.exists():
        root_catalog = json.loads(root_catalog_path.read_text(encoding="utf-8"))
        root_catalog["title"] = metadata["catalog"]["title"]
        root_catalog["description"] = collection["description"]
        root_catalog["updated"] = collection["updated"]
        _write_json(root_catalog_path, root_catalog)
    return {"items": item_count, "assets": asset_count}
