from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from osgeo import gdal, osr

from treemap_portolan_ingest.cli import main
from treemap_portolan_ingest.delivery import (
    _assert_same_raster,
    creation_options,
    delivery_plan,
    prepare_cogs,
    raster_facts,
    validate_cog,
)

gdal.UseExceptions()


def _write_raster(path: Path, *, cog: bool, value_offset: int = 0) -> None:
    source = path if not cog else path.with_suffix(".source.tif")
    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(str(source), 32, 24, 1, gdal.GDT_Byte)
    spatial_ref = osr.SpatialReference()
    spatial_ref.ImportFromEPSG(5070)
    dataset.SetProjection(spatial_ref.ExportToWkt())
    dataset.SetGeoTransform((-2362845.0, 30.0, 0.0, 3180555.0, 0.0, -30.0))
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(255)
    pixels = bytes((index + value_offset) % 251 for index in range(32 * 24))
    band.WriteRaster(0, 0, 32, 24, pixels)
    dataset = None
    if cog:
        result = gdal.Translate(
            str(path),
            str(source),
            format="COG",
            creationOptions=["COMPRESS=DEFLATE", "BLOCKSIZE=512"],
        )
        result = None
        source.unlink()


def _asset(path: Path, *, year: int, attribute: str, cog_valid: bool) -> dict:
    facts = raster_facts(path)
    return {
        "year": year,
        "attribute": attribute,
        "source_attribute": attribute,
        "source_path": str(path),
        "cog_valid": cog_valid,
        **facts,
    }


def _inventory(*assets: dict) -> dict:
    return {
        "schema_version": 1,
        "issues": [],
        "assets": list(assets),
    }


class DeliveryTests(unittest.TestCase):
    def test_plan_is_preview_only_and_uses_metadata_resampling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.tif"
            _write_raster(source, cog=False)
            destination = root / "delivery"
            manifest = root / "delivery.json"
            inventory = _inventory(
                _asset(
                    source,
                    year=2016,
                    attribute="TM_ID",
                    cog_valid=False,
                )
            )

            actions = prepare_cogs(
                inventory,
                root / "inventory.json",
                {"TM_ID": "identifier"},
                root / "metadata.json",
                destination,
                manifest,
            )

            self.assertEqual(actions[0]["operation"], "convert")
            self.assertEqual(actions[0]["overview_resampling"], "NEAREST")
            self.assertIn("RESAMPLING=NEAREST", actions[0]["creation_options"])
            self.assertFalse(destination.exists())
            self.assertFalse(manifest.exists())

    def test_plan_filters_years_and_attributes(self) -> None:
        inventory = {
            "assets": [
                {
                    "year": 2022,
                    "attribute": "TM_ID",
                    "source_path": "a.tif",
                    "size_bytes": 1,
                    "cog_valid": True,
                },
                {
                    "year": 2023,
                    "attribute": "BALIVE",
                    "source_path": "b.tif",
                    "size_bytes": 2,
                    "cog_valid": True,
                },
            ]
        }

        actions = delivery_plan(
            inventory,
            {"TM_ID": "identifier", "BALIVE": "continuous"},
            Path("delivery"),
            years=frozenset({2023}),
            attributes=frozenset({"BALIVE"}),
        )

        self.assertEqual([(action["year"], action["attribute"]) for action in actions], [(2023, "BALIVE")])

    def test_compliant_cog_is_copied_byte_for_byte_via_partial(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source-cog.tif"
            _write_raster(source, cog=True)
            inventory = _inventory(
                _asset(source, year=2023, attribute="BALIVE", cog_valid=True)
            )
            destination = root / "delivery"
            manifest_path = root / "delivery-manifest.json"

            records = prepare_cogs(
                inventory,
                root / "inventory.json",
                {"BALIVE": "continuous"},
                root / "metadata.json",
                destination,
                manifest_path,
                confirm=True,
            )

            target = destination / "2023" / "TreeMap2023_CONUS_BALIVE.tif"
            self.assertEqual(source.read_bytes(), target.read_bytes())
            self.assertEqual(records[0]["operation"], "copy")
            self.assertEqual(records[0]["creation_options"], [])
            self.assertEqual(records[0]["status"], "delivered")
            self.assertTrue(records[0]["output"]["cog"]["valid"])
            self.assertEqual(list(target.parent.glob("*.partial")), [])

    def test_noncompliant_raster_is_converted_and_all_pixels_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.tif"
            _write_raster(source, cog=False)
            source_bytes = source.read_bytes()
            inventory = _inventory(
                _asset(source, year=2016, attribute="TM_ID", cog_valid=False)
            )
            destination = root / "delivery"
            manifest_path = root / "delivery-manifest.json"

            records = prepare_cogs(
                inventory,
                root / "inventory.json",
                {"TM_ID": "identifier"},
                root / "metadata.json",
                destination,
                manifest_path,
                confirm=True,
            )

            target = destination / "2016" / "TreeMap2016_CONUS_TM_ID.tif"
            self.assertTrue(validate_cog(target)["valid"])
            self.assertTrue(records[0]["pixel_validation"]["equal"])
            self.assertEqual(
                records[0]["pixel_validation"]["source_pixel_sha256"],
                records[0]["pixel_validation"]["output_pixel_sha256"],
            )
            self.assertIn("RESAMPLING=NEAREST", records[0]["creation_options"])
            self.assertEqual(raster_facts(source)["projection_sha256"], raster_facts(target)["projection_sha256"])
            self.assertEqual(source.read_bytes(), source_bytes)

    def test_pixel_validator_rejects_changed_full_resolution_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.tif"
            output = root / "output.tif"
            _write_raster(source, cog=False)
            _write_raster(output, cog=False, value_offset=1)

            with self.assertRaisesRegex(ValueError, "pixel values differ"):
                _assert_same_raster(source, output)

    def test_existing_target_requires_manifest_then_resumes_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source-cog.tif"
            _write_raster(source, cog=True)
            inventory = _inventory(
                _asset(source, year=2022, attribute="ALSTK", cog_valid=True)
            )
            destination = root / "delivery"
            target = destination / "2022" / "TreeMap2022_CONUS_ALSTK.tif"
            target.parent.mkdir(parents=True)
            target.write_bytes(source.read_bytes())
            manifest_path = root / "delivery-manifest.json"
            arguments = (
                inventory,
                root / "inventory.json",
                {"ALSTK": "continuous"},
                root / "metadata.json",
                destination,
                manifest_path,
            )

            with self.assertRaisesRegex(FileExistsError, "matching manifest"):
                prepare_cogs(*arguments, confirm=True)

            target.unlink()
            manifest_path.unlink()
            prepare_cogs(*arguments, confirm=True)
            resumed = prepare_cogs(*arguments, confirm=True)

            self.assertEqual(resumed[0]["status"], "verified-existing")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["assets"]), 1)
            self.assertEqual(manifest["assets"][0]["status"], "verified-existing")

    def test_existing_target_with_changed_bytes_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source-cog.tif"
            _write_raster(source, cog=True)
            inventory = _inventory(
                _asset(source, year=2020, attribute="CANOPYPCT", cog_valid=True)
            )
            destination = root / "delivery"
            manifest_path = root / "delivery-manifest.json"
            arguments = (
                inventory,
                root / "inventory.json",
                {"CANOPYPCT": "continuous"},
                root / "metadata.json",
                destination,
                manifest_path,
            )
            prepare_cogs(*arguments, confirm=True)
            target = destination / "2020" / "TreeMap2020_CONUS_CANOPYPCT.tif"
            with target.open("ab") as stream:
                stream.write(b"changed")

            with self.assertRaisesRegex(FileExistsError, "failed manifest validation"):
                prepare_cogs(*arguments, confirm=True)

    def test_cli_preview_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source-cog.tif"
            _write_raster(source, cog=True)
            inventory_path = root / "inventory.json"
            inventory_path.write_text(
                json.dumps(_inventory(_asset(source, year=2023, attribute="ALSTK", cog_valid=True))),
                encoding="utf-8",
            )
            metadata_path = root / "metadata.json"
            metadata_path.write_text(
                json.dumps({"attributes": {"ALSTK": {"kind": "continuous"}}}),
                encoding="utf-8",
            )
            destination = root / "delivery"
            manifest_path = root / "delivery-manifest.json"

            result = main(
                [
                    "prepare-cogs",
                    "--inventory",
                    str(inventory_path),
                    "--metadata",
                    str(metadata_path),
                    "--destination",
                    str(destination),
                    "--delivery-manifest",
                    str(manifest_path),
                    "--year",
                    "2023",
                    "--attribute",
                    "ALSTK",
                ]
            )

            self.assertEqual(result, 0)
            self.assertFalse(destination.exists())
            self.assertFalse(manifest_path.exists())

    def test_creation_options_use_mode_and_average_by_kind(self) -> None:
        self.assertIn("RESAMPLING=MODE", creation_options("categorical"))
        self.assertIn("RESAMPLING=AVERAGE", creation_options("continuous"))


if __name__ == "__main__":
    unittest.main()
