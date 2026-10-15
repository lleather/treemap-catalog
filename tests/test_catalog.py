from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from treemap_portolan_ingest.catalog import enrich_catalog
from treemap_portolan_ingest.rat import prepare_rats


class CatalogTests(unittest.TestCase):
    def test_enriches_temporal_version_and_band_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path = root / "config" / "metadata.json"
            classes_path = root / "classes.json"
            item_path = root / "catalog" / "treemap" / "2020" / "2020.json"
            collection_path = root / "catalog" / "treemap" / "collection.json"
            metadata_path.parent.mkdir()
            item_path.parent.mkdir(parents=True)
            classes_path.write_text(
                json.dumps(
                    {
                        "class_names": ["A"],
                        "class_values": [1],
                        "class_palette": ["FFFFFF"],
                    }
                ),
                encoding="utf-8",
            )
            metadata_path.write_text(
                json.dumps(
                    {
                        "catalog": {
                            "title": "TreeMap",
                            "spatial_extent": [-1, -2, 3, 4],
                            "temporal_extent": [
                                "2020-01-01T00:00:00Z",
                                "2020-12-31T23:59:59Z",
                            ],
                        },
                        "years": {
                            "2020": {
                                "tm_data_ver": "x",
                                "doi": "https://doi.org/example",
                            }
                        },
                        "attributes": {
                            "TYPE": {
                                "title": "Type",
                                "unit": None,
                                "classes_source": "classes.json",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            collection_path.write_text(
                json.dumps(
                    {
                        "extent": {
                            "spatial": {"bbox": [[0, 0, 0, 0]]},
                            "temporal": {"interval": [[None, None]]},
                        }
                    }
                ),
                encoding="utf-8",
            )
            item_path.write_text(
                json.dumps(
                    {
                        "properties": {"datetime": "2020-01-01T00:00:00Z"},
                        "assets": {
                            "type": {
                                "href": "TreeMap2020_CONUS_TYPE.tif",
                                "bands": [{"data_type": "uint8"}],
                            }
                        },
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )

            result = enrich_catalog(
                root / "catalog", metadata_path, years=frozenset({2020})
            )

            item = json.loads(item_path.read_text(encoding="utf-8"))
            self.assertEqual(result, {"items": 1, "assets": 1})
            self.assertIsNone(item["properties"]["datetime"])
            self.assertEqual(item["properties"]["treemap:tm_data_ver"], "x")
            self.assertEqual(
                item["assets"]["type"]["bands"][0]["classification:classes"][0][
                    "name"
                ],
                "A",
            )

    def test_attaches_dictionary_metadata_and_registers_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path = root / "config" / "metadata.json"
            catalog_root = root / "catalog"
            collection_path = catalog_root / "treemap" / "collection.json"
            item_path = catalog_root / "treemap" / "2023" / "2023.json"
            dictionary_path = catalog_root / "treemap" / "dictionary.csv"
            metadata_path.parent.mkdir()
            item_path.parent.mkdir(parents=True)
            dictionary_path.write_text(
                "Date reviewed,2026-02-25\n"
                "FIA User Guide version,9.4\n"
                "\n"
                "Column name,Attribute name,Units,Display name for attribute layer,"
                "Short description,Long Description,"
                "Source (table/column/query); Sec = FIADB manual section\n"
                "ALSTK,All-live tree stocking,percent,,Short text,Long text,"
                "From COND.ALSTK\n",
                encoding="utf-8",
            )
            metadata_path.write_text(
                json.dumps(
                    {
                        "catalog": {
                            "title": "TreeMap",
                            "spatial_extent": [-1, -2, 3, 4],
                        },
                        "years": {
                            "2023": {
                                "tm_data_ver": "x",
                                "doi": "https://doi.org/example",
                            }
                        },
                        "attributes": {
                            "ALSTK": {
                                "title": "All-live-tree stocking",
                                "unit": "percent",
                            }
                        },
                        "attribute_dictionary": {
                            "csv_name": "dictionary.csv",
                            "title": "TreeMap attribute data dictionary",
                            "description": "Published definitions.",
                        },
                    }
                ),
                encoding="utf-8",
            )
            collection_path.write_text(
                json.dumps(
                    {
                        "extent": {
                            "spatial": {"bbox": [[0, 0, 0, 0]]},
                            "temporal": {"interval": [[None, None]]},
                        }
                    }
                ),
                encoding="utf-8",
            )
            item_path.write_text(
                json.dumps(
                    {
                        "id": "2023",
                        "properties": {"datetime": "2023-01-01T00:00:00Z"},
                        "assets": {
                            "data": {
                                "href": "TreeMap2023_CONUS_ALSTK.tif",
                                "bands": [{}],
                            }
                        },
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )

            enrich_catalog(
                catalog_root,
                metadata_path,
                years=frozenset({2023}),
            )

            item = json.loads(item_path.read_text(encoding="utf-8"))
            asset = item["assets"]["data"]
            self.assertEqual(asset["description"], "Short text")
            self.assertEqual(asset["bands"][0]["description"], "Long text")
            self.assertEqual(
                asset["bands"][0]["treemap:source"],
                "From COND.ALSTK",
            )
            collection = json.loads(collection_path.read_text(encoding="utf-8"))
            dictionary_asset = collection["assets"]["attribute-data-dictionary"]
            self.assertEqual(dictionary_asset["roles"], ["metadata"])
            self.assertEqual(dictionary_asset["href"], "./dictionary.csv")

    def test_registers_prepared_rat_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            source.write_text(
                "PLT_CN,TM_ID\n100,1\n101,2\n",
                encoding="utf-8",
            )
            metadata_path = root / "config" / "metadata.json"
            metadata_path.parent.mkdir()
            metadata_path.write_text(
                json.dumps(
                    {
                        "catalog": {
                            "title": "TreeMap",
                            "spatial_extent": [-1, -2, 3, 4],
                        },
                        "years": {
                            "2023": {
                                "tm_data_ver": "x",
                                "doi": "https://doi.org/example",
                            }
                        },
                        "attributes": {},
                        "raster_attribute_tables": {
                            "2023": {
                                "source": str(source),
                                "expected_size": source.stat().st_size,
                                "expected_sha256": hashlib.sha256(
                                    source.read_bytes()
                                ).hexdigest(),
                                "expected_rows": 2,
                                "csv_name": "rat.csv",
                                "parquet_name": "rat.parquet",
                                "join": {
                                    "raster_key": "TM_ID",
                                    "fia_key": "PLT_CN",
                                },
                                "columns": [
                                    {
                                        "name": "PLT_CN",
                                        "type": "int64",
                                        "description": "FIA condition identifier.",
                                    },
                                    {
                                        "name": "TM_ID",
                                        "type": "int64",
                                        "description": "TreeMap identifier.",
                                    },
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            catalog_root = root / "catalog"
            item_path = catalog_root / "treemap" / "2023" / "2023.json"
            collection_path = catalog_root / "treemap" / "collection.json"
            root_catalog_path = catalog_root / "catalog.json"
            item_path.parent.mkdir(parents=True)
            root_catalog_path.write_text(
                json.dumps({"description": "old"}),
                encoding="utf-8",
            )
            collection_path.write_text(
                json.dumps(
                    {
                        "extent": {
                            "spatial": {"bbox": [[0, 0, 0, 0]]},
                            "temporal": {"interval": [[None, None]]},
                        }
                    }
                ),
                encoding="utf-8",
            )
            item_path.write_text(
                json.dumps(
                    {
                        "id": "2023",
                        "stac_extensions": [
                            "https://stac-extensions.github.io/table/v1.3.0/schema.json"
                        ],
                        "properties": {"datetime": "2023-01-01T00:00:00Z"},
                        "assets": {},
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )
            prepare_rats(
                metadata_path,
                catalog_root / "treemap",
                confirm=True,
            )

            result = enrich_catalog(
                catalog_root,
                metadata_path,
                years=frozenset({2023}),
            )
            first = json.loads(item_path.read_text(encoding="utf-8"))
            enrich_catalog(
                catalog_root,
                metadata_path,
                years=frozenset({2023}),
            )
            second = json.loads(item_path.read_text(encoding="utf-8"))

            self.assertEqual(result, {"items": 1, "assets": 2})
            self.assertEqual(first, second)
            self.assertIn(
                "https://stac-extensions.github.io/table/v1.2.0/schema.json",
                first["stac_extensions"],
            )
            self.assertNotIn(
                "https://stac-extensions.github.io/table/v1.3.0/schema.json",
                first["stac_extensions"],
            )
            csv_asset = first["assets"]["raster-attribute-table-csv"]
            parquet_asset = first["assets"]["raster-attribute-table-parquet"]
            self.assertEqual(csv_asset["roles"], ["metadata", "source"])
            self.assertEqual(parquet_asset["roles"], ["metadata"])
            self.assertEqual(parquet_asset["table:row_count"], 2)
            self.assertEqual(
                [column["name"] for column in parquet_asset["table:columns"]],
                ["PLT_CN", "TM_ID"],
            )
            self.assertTrue(csv_asset["file:checksum"].startswith("1220"))
            self.assertTrue(parquet_asset["file:checksum"].startswith("1220"))
            root_catalog = json.loads(
                root_catalog_path.read_text(encoding="utf-8")
            )
            self.assertIn("Raster Attribute Table", root_catalog["description"])


if __name__ == "__main__":
    unittest.main()
