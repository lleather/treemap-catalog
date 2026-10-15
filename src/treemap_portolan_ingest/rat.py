"""Prepare year-specific TreeMap Raster Attribute Tables."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq


_ARROW_TYPES: dict[str, pa.DataType] = {
    "float64": pa.float64(),
    "int64": pa.int64(),
    "string": pa.string(),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _columns(config: dict[str, Any]) -> list[dict[str, Any]]:
    columns = config.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ValueError("RAT configuration must define columns")
    return columns


def _read_csv(path: Path, config: dict[str, Any]) -> pa.Table:
    columns = _columns(config)
    column_types = {
        column["name"]: _ARROW_TYPES[column["type"]]
        for column in columns
    }
    table = pacsv.read_csv(
        path,
        read_options=pacsv.ReadOptions(use_threads=False),
        convert_options=pacsv.ConvertOptions(
            column_types=column_types,
            null_values=["NA"],
            strings_can_be_null=True,
        ),
    )
    expected_names = [column["name"] for column in columns]
    if table.column_names != expected_names:
        raise ValueError(
            f"RAT columns differ for {path}: "
            f"expected {expected_names}, found {table.column_names}"
        )
    return table.combine_chunks()


def _validate_table(
    table: pa.Table,
    config: dict[str, Any],
    source: Path,
) -> None:
    expected_rows = int(config["expected_rows"])
    if table.num_rows != expected_rows:
        raise ValueError(
            f"RAT row count differs for {source}: "
            f"expected {expected_rows}, found {table.num_rows}"
        )
    for column_config, field in zip(
        _columns(config),
        table.schema,
        strict=True,
    ):
        expected_type = _ARROW_TYPES[column_config["type"]]
        if field.type != expected_type:
            raise ValueError(
                f"RAT type differs for {source}: "
                f"{field.name} expected {expected_type}, found {field.type}"
            )
    for key in (config["join"]["raster_key"], config["join"]["fia_key"]):
        values = table[key]
        if values.null_count:
            raise ValueError(f"RAT join key contains nulls: {key}")
        if len(set(values.to_pylist())) != table.num_rows:
            raise ValueError(f"RAT join key is not unique: {key}")


def _read_and_validate_csv(path: Path, config: dict[str, Any]) -> pa.Table:
    table = _read_csv(path, config)
    _validate_table(table, config, path)
    return table


def _validate_source(path: Path, config: dict[str, Any]) -> tuple[int, str]:
    if not path.is_file():
        raise FileNotFoundError(f"RAT source does not exist: {path}")
    size = path.stat().st_size
    checksum = _sha256(path)
    if size != int(config["expected_size"]):
        raise ValueError(
            f"RAT source size differs: expected {config['expected_size']}, found {size}"
        )
    if checksum != config["expected_sha256"]:
        raise ValueError(
            "RAT source SHA-256 differs: "
            f"expected {config['expected_sha256']}, found {checksum}"
        )
    return size, checksum


def _target_status(
    path: Path,
    expected_table: pa.Table,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> str:
    if not path.exists():
        return "create"
    if expected_size is not None and expected_sha256 is not None:
        if path.stat().st_size == expected_size and _sha256(path) == expected_sha256:
            return "verified-existing"
        return "refuse-existing"
    try:
        actual = pq.read_table(path).combine_chunks()
    except (OSError, pa.ArrowException):
        return "refuse-existing"
    return "verified-existing" if actual.equals(expected_table) else "refuse-existing"


def _safe_name(value: str) -> str:
    if Path(value).name != value:
        raise ValueError(f"RAT output name must be a file name: {value}")
    return value


def _load_metadata(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_rats(
    metadata_path: Path,
    destination: Path,
    years: frozenset[int] | None = None,
    confirm: bool = False,
) -> list[dict[str, Any]]:
    """Validate, preview, and optionally prepare configured RAT assets."""
    metadata = _load_metadata(metadata_path)
    configured = metadata.get("raster_attribute_tables", {})
    selected = [
        (int(year_text), config)
        for year_text, config in configured.items()
        if years is None or int(year_text) in years
    ]
    if not selected:
        raise ValueError("no Raster Attribute Tables selected")

    prepared: list[tuple[dict[str, Any], dict[str, Any], pa.Table]] = []
    for year, config in selected:
        source = Path(config["source"])
        source_size, source_sha256 = _validate_source(source, config)
        table = _read_and_validate_csv(source, config)
        item_directory = destination / str(year)
        csv_target = item_directory / _safe_name(config["csv_name"])
        parquet_target = item_directory / _safe_name(config["parquet_name"])
        action = {
            "year": year,
            "source": str(source),
            "source_size": source_size,
            "source_sha256": source_sha256,
            "row_count": table.num_rows,
            "csv": {
                "target": str(csv_target),
                "status": _target_status(
                    csv_target,
                    table,
                    expected_size=source_size,
                    expected_sha256=source_sha256,
                ),
            },
            "parquet": {
                "target": str(parquet_target),
                "status": _target_status(parquet_target, table),
            },
        }
        prepared.append((action, config, table))

    conflicts = [
        details["target"]
        for action, _, _ in prepared
        for details in (action["csv"], action["parquet"])
        if details["status"] == "refuse-existing"
    ]
    if conflicts:
        raise FileExistsError(
            "refusing to overwrite existing RAT outputs: " + ", ".join(conflicts)
        )

    if confirm:
        for action, _, table in prepared:
            csv_details = action["csv"]
            csv_target = Path(csv_details["target"])
            if csv_details["status"] == "create":
                csv_target.parent.mkdir(parents=True, exist_ok=True)
                temporary = csv_target.with_suffix(csv_target.suffix + ".partial")
                if temporary.exists():
                    temporary.unlink()
                try:
                    shutil.copyfile(action["source"], temporary)
                    if (
                        temporary.stat().st_size != action["source_size"]
                        or _sha256(temporary) != action["source_sha256"]
                    ):
                        raise OSError(f"staged RAT CSV differs: {temporary}")
                    temporary.replace(csv_target)
                    csv_details["status"] = "created"
                finally:
                    if temporary.exists():
                        temporary.unlink()

            parquet_details = action["parquet"]
            parquet_target = Path(parquet_details["target"])
            if parquet_details["status"] == "create":
                parquet_target.parent.mkdir(parents=True, exist_ok=True)
                temporary = parquet_target.with_suffix(
                    parquet_target.suffix + ".partial"
                )
                if temporary.exists():
                    temporary.unlink()
                try:
                    pq.write_table(
                        table,
                        temporary,
                        compression="zstd",
                        use_dictionary=True,
                        row_group_size=150_000,
                        version="2.6",
                    )
                    written = pq.read_table(temporary).combine_chunks()
                    if not written.equals(table):
                        raise OSError(f"prepared RAT Parquet differs: {temporary}")
                    temporary.replace(parquet_target)
                    parquet_details["status"] = "created"
                finally:
                    if temporary.exists():
                        temporary.unlink()

    return [action for action, _, _ in prepared]


def validate_rat_outputs(
    config: dict[str, Any],
    item_directory: Path,
) -> dict[str, Any]:
    """Validate staged CSV and Parquet assets before STAC registration."""
    csv_path = item_directory / _safe_name(config["csv_name"])
    parquet_path = item_directory / _safe_name(config["parquet_name"])
    csv_size, csv_checksum = _validate_source(csv_path, config)
    csv_table = _read_and_validate_csv(csv_path, config)
    if not parquet_path.is_file():
        raise FileNotFoundError(f"RAT Parquet does not exist: {parquet_path}")
    parquet_table = pq.read_table(parquet_path).combine_chunks()
    if not parquet_table.equals(csv_table):
        raise ValueError(f"RAT Parquet values differ from CSV: {parquet_path}")
    return {
        "row_count": csv_table.num_rows,
        "csv": {
            "path": csv_path,
            "size": csv_size,
            "sha256": csv_checksum,
        },
        "parquet": {
            "path": parquet_path,
            "size": parquet_path.stat().st_size,
            "sha256": _sha256(parquet_path),
        },
    }
