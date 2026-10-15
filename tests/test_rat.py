from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import pyarrow.parquet as pq

from treemap_portolan_ingest.rat import prepare_rats


def write_rat_metadata(root: Path, csv_text: str) -> Path:
    source = root / "source.csv"
    source.write_text(csv_text, encoding="utf-8")
    metadata_path = root / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "raster_attribute_tables": {
                    "2023": {
                        "source": str(source),
                        "expected_size": source.stat().st_size,
                        "expected_sha256": hashlib.sha256(
                            source.read_bytes()
                        ).hexdigest(),
                        "expected_rows": len(csv_text.strip().splitlines()) - 1,
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
                            {
                                "name": "VALUE",
                                "type": "float64",
                                "description": "Example value.",
                            },
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return metadata_path


class RatTests(unittest.TestCase):
    def test_previews_then_prepares_verified_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path = write_rat_metadata(
                root,
                "PLT_CN,TM_ID,VALUE\n100,1,2.5\n101,2,NA\n",
            )
            destination = root / "catalog"

            preview = prepare_rats(metadata_path, destination)

            self.assertEqual(preview[0]["csv"]["status"], "create")
            self.assertEqual(preview[0]["parquet"]["status"], "create")
            self.assertFalse(destination.exists())

            applied = prepare_rats(metadata_path, destination, confirm=True)

            source = root / "source.csv"
            csv_target = destination / "2023" / "rat.csv"
            parquet_target = destination / "2023" / "rat.parquet"
            self.assertEqual(applied[0]["csv"]["status"], "created")
            self.assertEqual(applied[0]["parquet"]["status"], "created")
            self.assertEqual(csv_target.read_bytes(), source.read_bytes())
            table = pq.read_table(parquet_target)
            self.assertEqual(table.num_rows, 2)
            self.assertEqual(table["PLT_CN"].to_pylist(), [100, 101])
            self.assertEqual(table["TM_ID"].to_pylist(), [1, 2])
            self.assertEqual(table["VALUE"].to_pylist(), [2.5, None])

            repeated = prepare_rats(metadata_path, destination, confirm=True)

            self.assertEqual(repeated[0]["csv"]["status"], "verified-existing")
            self.assertEqual(
                repeated[0]["parquet"]["status"],
                "verified-existing",
            )

    def test_refuses_changed_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata_path = write_rat_metadata(
                root,
                "PLT_CN,TM_ID,VALUE\n100,1,2.5\n",
            )
            target = root / "catalog" / "2023" / "rat.csv"
            target.parent.mkdir(parents=True)
            target.write_text("changed", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                prepare_rats(metadata_path, root / "catalog", confirm=True)

            self.assertEqual(target.read_text(encoding="utf-8"), "changed")
            self.assertFalse((target.parent / "rat.parquet").exists())

    def test_rejects_duplicate_or_null_join_keys(self) -> None:
        cases = {
            "duplicate TM_ID": (
                "PLT_CN,TM_ID,VALUE\n100,1,2.5\n101,1,3.5\n",
                "TM_ID",
            ),
            "duplicate PLT_CN": (
                "PLT_CN,TM_ID,VALUE\n100,1,2.5\n100,2,3.5\n",
                "PLT_CN",
            ),
            "null TM_ID": (
                "PLT_CN,TM_ID,VALUE\n100,NA,2.5\n",
                "TM_ID",
            ),
            "null PLT_CN": (
                "PLT_CN,TM_ID,VALUE\nNA,1,2.5\n",
                "PLT_CN",
            ),
        }
        for label, (csv_text, key) in cases.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    metadata_path = write_rat_metadata(root, csv_text)
                    with self.assertRaisesRegex(ValueError, key):
                        prepare_rats(metadata_path, root / "catalog")


if __name__ == "__main__":
    unittest.main()
