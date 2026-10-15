"""Command-line interface for the TreeMap ingest workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .delivery import (
    DEFAULT_COG_DESTINATION,
    load_metadata,
    prepare_cogs,
)
from .catalog import enrich_catalog
from .dictionary import prepare_attribute_dictionary
from .inventory import build_inventory, load_config, write_manifest
from .rat import prepare_rats
from .stage import (
    apply_stage_plan,
    load_delivery_manifest,
    load_inventory,
    stage_plan,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="treemap-ingest",
        description="Inventory TreeMap delivery rasters without modifying the source.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory", help="Inspect configured TIFFs")
    inventory.add_argument(
        "--config", type=Path, default=Path("config/ingest.json")
    )
    inventory.add_argument("--workers", type=int, default=1)
    inventory.add_argument(
        "--write-manifest",
        type=Path,
        help="Write the manifest. Without this option, the command is read-only.",
    )
    inventory.add_argument(
        "--json", action="store_true", help="Print the full inventory as JSON"
    )
    stage = subparsers.add_parser(
        "stage", help="Copy validated delivery COGs into the catalog item layout"
    )
    stage.add_argument(
        "--manifest", type=Path, default=Path("work/delivery-manifest.json")
    )
    stage.add_argument("--destination", type=Path, default=Path("treemap"))
    stage.add_argument("--year", type=int, action="append", dest="years")
    stage.add_argument("--attribute", action="append", dest="attributes")
    stage.add_argument(
        "--confirm",
        action="store_true",
        help="Apply the plan. Without this flag, no files are copied.",
    )
    stage.add_argument("--json", action="store_true")
    prepare = subparsers.add_parser(
        "prepare-cogs",
        help="Copy or convert inventoried rasters into validated delivery COGs",
    )
    prepare.add_argument(
        "--inventory", type=Path, default=Path("work/inventory.json")
    )
    prepare.add_argument(
        "--metadata", type=Path, default=Path("config/metadata.json")
    )
    prepare.add_argument(
        "--destination", type=Path, default=DEFAULT_COG_DESTINATION
    )
    prepare.add_argument("--year", type=int, action="append", dest="years")
    prepare.add_argument("--attribute", action="append", dest="attributes")
    prepare.add_argument(
        "--delivery-manifest",
        type=Path,
        default=Path("work/delivery-manifest.json"),
        help="Record source, output, validation, and resume facts",
    )
    prepare.add_argument(
        "--confirm",
        action="store_true",
        help="Write outputs and the delivery manifest. The default is preview only.",
    )
    prepare.add_argument("--json", action="store_true")
    enrich = subparsers.add_parser(
        "enrich", help="Enrich generated TreeMap STAC items from metadata"
    )
    enrich.add_argument("--catalog", type=Path, default=Path("."))
    enrich.add_argument("--metadata", type=Path, default=Path("config/metadata.json"))
    enrich.add_argument("--year", type=int, action="append", dest="years")
    enrich.add_argument("--json", action="store_true")
    rat = subparsers.add_parser(
        "prepare-rat",
        help="Validate and prepare year-specific Raster Attribute Tables",
    )
    rat.add_argument("--metadata", type=Path, default=Path("config/metadata.json"))
    rat.add_argument("--destination", type=Path, default=Path("treemap"))
    rat.add_argument("--year", type=int, action="append", dest="years")
    rat.add_argument(
        "--confirm",
        action="store_true",
        help="Write CSV and Parquet outputs. The default is preview only.",
    )
    rat.add_argument("--json", action="store_true")
    dictionary = subparsers.add_parser(
        "prepare-data-dictionary",
        help="Validate and prepare the TreeMap attribute data dictionary CSV",
    )
    dictionary.add_argument(
        "--metadata", type=Path, default=Path("config/metadata.json")
    )
    dictionary.add_argument("--destination", type=Path, default=Path("treemap"))
    dictionary.add_argument(
        "--confirm",
        action="store_true",
        help="Write the CSV. The default is preview only.",
    )
    dictionary.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the selected ingest command."""
    args = _parser().parse_args(argv)
    if args.command == "inventory":
        config = load_config(args.config)
        inventory = build_inventory(config, workers=args.workers)
        if args.write_manifest is not None:
            write_manifest(inventory, args.write_manifest)
        if args.json:
            print(json.dumps(inventory, indent=2, sort_keys=True, ensure_ascii=False))
        else:
            summary = inventory["summary"]
            print(f"Source: {inventory['source_root']}")
            print(f"Assets: {summary['asset_count']}")
            print(f"Bytes: {summary['total_bytes']}")
            print(f"COGs: {summary['cog_count']}")
            print(f"Issues: {summary['issue_count']}")
            for issue in inventory["issues"]:
                print(f"- {issue}")
            if args.write_manifest is None:
                print("Preview only: no manifest or source files were written.")
            else:
                print(f"Manifest: {args.write_manifest}")
        return 1 if inventory["issues"] else 0

    if args.command == "stage":
        manifest = load_delivery_manifest(args.manifest)
        actions = stage_plan(
            manifest,
            args.destination,
            frozenset(args.years) if args.years else None,
            frozenset(args.attributes) if args.attributes else None,
        )
        if args.confirm:
            apply_stage_plan(actions)
        if args.json:
            print(json.dumps(actions, indent=2, sort_keys=True))
        else:
            total_bytes = sum(
                action["size_bytes"]
                for action in actions
                if action["status"] != "skip"
            )
            conversion_count = sum(
                action["post_copy_action"] != "retain"
                for action in actions
            )
            print(f"Assets: {len(actions)}")
            print(f"Bytes to copy or replace: {total_bytes}")
            print(f"Assets requiring COG conversion: {conversion_count}")
            print("Applied." if args.confirm else "Preview only: no files were copied.")
        return 0

    if args.command == "enrich":
        result = enrich_catalog(
            args.catalog,
            args.metadata,
            frozenset(args.years) if args.years else None,
        )
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(f"Items enriched: {result['items']}")
            print(f"Assets enriched: {result['assets']}")
        return 0

    if args.command == "prepare-rat":
        actions = prepare_rats(
            args.metadata,
            args.destination,
            frozenset(args.years) if args.years else None,
            confirm=args.confirm,
        )
        if args.json:
            print(json.dumps(actions, indent=2, sort_keys=True))
        else:
            print(f"Raster Attribute Tables: {len(actions)}")
            for action in actions:
                print(
                    f"{action['year']}: CSV {action['csv']['status']}; "
                    f"Parquet {action['parquet']['status']}; "
                    f"rows {action['row_count']}"
                )
            print("Applied." if args.confirm else "Preview only: no files were written.")
        return 0

    if args.command == "prepare-data-dictionary":
        action = prepare_attribute_dictionary(
            args.metadata,
            args.destination,
            confirm=args.confirm,
        )
        if args.json:
            print(json.dumps(action, indent=2, sort_keys=True))
        else:
            print(f"Data dictionary: {action['status']}")
            print(f"Rows: {action['row_count']}")
            print(f"Target: {action['target']}")
            print("Applied." if args.confirm else "Preview only: no file was written.")
        return 0

    if args.command == "prepare-cogs":
        inventory = load_inventory(args.inventory)
        metadata_kinds = load_metadata(args.metadata)
        actions = prepare_cogs(
            inventory=inventory,
            inventory_path=args.inventory,
            metadata_kinds=metadata_kinds,
            metadata_path=args.metadata,
            destination=args.destination,
            delivery_manifest_path=args.delivery_manifest,
            years=frozenset(args.years) if args.years else None,
            attributes=frozenset(args.attributes) if args.attributes else None,
            confirm=args.confirm,
        )
        if args.json:
            print(json.dumps(actions, indent=2, sort_keys=True, ensure_ascii=False))
        else:
            copy_count = sum(action["operation"] == "copy" for action in actions)
            conversion_count = sum(
                action["operation"] == "convert" for action in actions
            )
            print(f"Assets: {len(actions)}")
            print(f"Copy unchanged: {copy_count}")
            print(f"Convert locally: {conversion_count}")
            print(f"Destination: {args.destination}")
            if args.confirm:
                skipped = sum(
                    action["status"] == "verified-existing" for action in actions
                )
                print(f"Verified existing: {skipped}")
                print(f"Delivery manifest: {args.delivery_manifest}")
            else:
                print("Preview only: no files or manifest were written.")
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
