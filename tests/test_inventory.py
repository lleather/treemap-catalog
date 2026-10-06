from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from treemap_portolan_ingest.inventory import (
    discover_sources,
    load_config,
    parse_source_name,
)


def _write_config(root: Path, path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "source_root": str(root),
                "collection_id": "treemap",
                "years": [2016, 2020],
                "source_directories": {
                    "2016": "2016",
                    "2020": "preferred/2020",
                },
                "common_attributes": ["TM_ID", "STANDHT"],
                "year_attributes": {
                    "2016": ["QMD_RMRS"],
                    "2020": ["QMD"],
                },
                "source_aliases": {"2016": {"VALUE": "TM_ID"}},
                "ignored_name_suffixes": ["_cat"],
            }
        ),
        encoding="utf-8",
    )


class InventoryTests(unittest.TestCase):
    def test_parse_normalizes_legacy_alias_and_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.json"
            _write_config(root, config_path)
            config = load_config(config_path)

            self.assertEqual(
                parse_source_name(Path("TreeMap2016_VALUE.tif"), config),
                (2016, "VALUE", "TM_ID"),
            )
            self.assertEqual(
                parse_source_name(
                    Path("TreeMap2020_CONUS_STANDHT_cat.tif"), config
                ),
                (2020, "STANDHT", "STANDHT"),
            )

    def test_discovery_uses_only_top_level_annual_tiffs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.json"
            _write_config(root, config_path)
            for year, names in {
                2016: [
                    "TreeMap2016_VALUE.tif",
                    "TreeMap2016_STANDHT.tif",
                    "TreeMap2016_QMD_RMRS.tif",
                ],
                2020: [
                    "TreeMap2020_CONUS_TM_ID.tif",
                    "TreeMap2020_CONUS_STANDHT_cat.tif",
                    "TreeMap2020_CONUS_QMD.tif",
                ],
            }.items():
                year_dir = (
                    root / str(year)
                    if year == 2016
                    else root / "preferred" / str(year)
                )
                year_dir.mkdir(parents=True)
                for name in names:
                    (year_dir / name).touch()
                legacy = year_dir / "legacy"
                legacy.mkdir()
                (legacy / names[0]).touch()

            sources, issues = discover_sources(load_config(config_path))

            self.assertEqual(len(sources), 6)
            self.assertEqual(issues, [])
            self.assertTrue(all(source.path.parent.name != "legacy" for source in sources))

    def test_discovery_reports_missing_and_unexpected_attributes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "config.json"
            _write_config(root, config_path)
            (root / "2016").mkdir()
            (root / "preferred" / "2020").mkdir(parents=True)
            (root / "2016" / "TreeMap2016_OTHER.tif").touch()

            _, issues = discover_sources(load_config(config_path))

            self.assertIn("2016: unexpected attribute OTHER", issues)
            self.assertIn("2016: missing expected attribute TM_ID", issues)
            self.assertIn("2020: missing expected attribute QMD", issues)


if __name__ == "__main__":
    unittest.main()