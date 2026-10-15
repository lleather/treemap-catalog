"""Prepare and read the TreeMap attribute data dictionary."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
import hashlib
from io import StringIO
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REFERENCE = re.compile(r"(?P<column>[A-Z]+)\d+")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_source(path: Path, config: dict[str, Any]) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"data dictionary source does not exist: {path}")
    size = path.stat().st_size
    if size != int(config["expected_size"]):
        raise ValueError(
            "data dictionary source size differs: "
            f"expected {config['expected_size']}, found {size}"
        )
    checksum = _sha256(path)
    if checksum != config["expected_sha256"]:
        raise ValueError(
            "data dictionary source SHA-256 differs: "
            f"expected {config['expected_sha256']}, found {checksum}"
        )


def _column_index(reference: str) -> int:
    match = _CELL_REFERENCE.fullmatch(reference)
    if match is None:
        raise ValueError(f"invalid spreadsheet cell reference: {reference}")
    result = 0
    for character in match.group("column"):
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def _worksheet_path(archive: ZipFile, worksheet_name: str) -> str:
    namespace = {"m": _MAIN_NS, "r": _REL_NS}
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationship_id: str | None = None
    for sheet in workbook.findall("m:sheets/m:sheet", namespace):
        if sheet.attrib["name"] == worksheet_name:
            relationship_id = sheet.attrib[f"{{{_REL_NS}}}id"]
            break
    if relationship_id is None:
        raise ValueError(f"data dictionary worksheet does not exist: {worksheet_name}")

    relationships = ElementTree.fromstring(
        archive.read("xl/_rels/workbook.xml.rels")
    )
    target: str | None = None
    for relationship in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
        if relationship.attrib["Id"] == relationship_id:
            target = relationship.attrib["Target"]
            break
    if target is None:
        raise ValueError(f"worksheet relationship does not exist: {worksheet_name}")
    parts = PurePosixPath("xl", target).parts
    normalized: list[str] = []
    for part in parts:
        if part == "..":
            normalized.pop()
        elif part != ".":
            normalized.append(part)
    return "/".join(normalized)


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    namespace = {"m": _MAIN_NS}
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.findall(".//m:t", namespace))
        for item in root.findall("m:si", namespace)
    ]


def _cell_value(
    cell: ElementTree.Element,
    shared_strings: list[str],
) -> str:
    namespace = {"m": _MAIN_NS}
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(
            node.text or "" for node in cell.findall(".//m:t", namespace)
        )
    value = cell.find("m:v", namespace)
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        return shared_strings[int(value.text)]
    return value.text


def _normalize_rows(rows: list[list[str]]) -> list[list[str]]:
    normalized = [
        [value.strip().replace("\r\n", "\n").replace("\r", "\n") for value in row]
        for row in rows
    ]
    for row in normalized:
        while row and not row[-1]:
            row.pop()
    if (
        normalized
        and len(normalized[0]) >= 2
        and normalized[0][0].casefold() == "date reviewed"
        and normalized[0][1].replace(".", "", 1).isdigit()
    ):
        reviewed = datetime(1899, 12, 30) + timedelta(
            days=float(normalized[0][1])
        )
        normalized[0][1] = reviewed.date().isoformat()
    return normalized


def read_xlsx_rows(path: Path, worksheet_name: str) -> list[list[str]]:
    """Read values from one XLSX worksheet using the standard library."""
    namespace = {"m": _MAIN_NS}
    with ZipFile(path) as archive:
        shared_strings = _shared_strings(archive)
        worksheet = ElementTree.fromstring(
            archive.read(_worksheet_path(archive, worksheet_name))
        )
        rows: list[list[str]] = []
        for row in worksheet.findall(".//m:sheetData/m:row", namespace):
            values: list[str] = []
            for cell in row.findall("m:c", namespace):
                index = _column_index(cell.attrib["r"])
                values.extend("" for _ in range(index + 1 - len(values)))
                values[index] = _cell_value(cell, shared_strings)
            rows.append(values)
    return _normalize_rows(rows)


def _csv_bytes(rows: list[list[str]]) -> bytes:
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _safe_name(value: str) -> str:
    if Path(value).name != value:
        raise ValueError(f"data dictionary output name must be a file name: {value}")
    return value


def prepare_attribute_dictionary(
    metadata_path: Path,
    destination: Path,
    confirm: bool = False,
) -> dict[str, Any]:
    """Validate, preview, and optionally write the public data dictionary CSV."""
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    config = metadata["attribute_dictionary"]
    source = Path(config["source"])
    _validate_source(source, config)
    rows = read_xlsx_rows(source, config["worksheet"])
    output = _csv_bytes(rows)
    target = destination / _safe_name(config["csv_name"])
    status = "create"
    if target.exists():
        status = (
            "verified-existing"
            if target.read_bytes() == output
            else "refuse-existing"
        )
    if status == "refuse-existing":
        raise FileExistsError(
            f"refusing to overwrite existing data dictionary: {target}"
        )
    if confirm and status == "create":
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".partial")
        try:
            temporary.write_bytes(output)
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()
        status = "created"
    return {
        "source": str(source),
        "target": str(target),
        "status": status,
        "row_count": len(rows),
        "size": len(output),
        "sha256": _sha256_bytes(output),
    }


def _dictionary_records(rows: list[list[str]]) -> list[dict[str, str]]:
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if row and row[0].casefold() == "column name"
        ),
        None,
    )
    if header_index is None:
        raise ValueError("data dictionary CSV has no Column name header")
    headers = rows[header_index]
    records: list[dict[str, str]] = []
    for row in rows[header_index + 1 :]:
        values = row + [""] * (len(headers) - len(row))
        record = dict(zip(headers, values, strict=True))
        if record["Column name"]:
            records.append(record)
    return records


def load_attribute_dictionary(
    config: dict[str, Any],
    collection_directory: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """Load prepared attribute metadata and return keyed raster records."""
    path = collection_directory / _safe_name(config["csv_name"])
    if not path.is_file():
        raise FileNotFoundError(f"prepared data dictionary does not exist: {path}")
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = [[value.strip() for value in row] for row in csv.reader(stream)]
    aliases = config.get("column_aliases", {})
    records: dict[str, dict[str, str]] = {}
    for record in _dictionary_records(rows):
        source_name = record["Column name"]
        raster_name = aliases.get(source_name, source_name)
        records[raster_name] = record
    return records, {
        "path": path,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "row_count": len(rows),
    }
