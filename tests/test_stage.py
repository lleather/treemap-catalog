from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from treemap_portolan_ingest.stage import apply_stage_plan, stage_plan


class StageTests(unittest.TestCase):
    def test_plan_uses_validated_delivery_output(self) -> None:
        manifest = {
            "assets": [
                {
                    "year": 2016,
                    "attribute": "TM_ID",
                    "target": "delivery/2016/TreeMap2016_CONUS_TM_ID.tif",
                    "output": {
                        "facts": {"size_bytes": 12},
                        "sha256": "abc",
                    },
                }
            ]
        }

        actions = stage_plan(manifest, Path("treemap"))

        self.assertEqual(actions[0]["target"], str(Path("treemap/2016/TreeMap2016_CONUS_TM_ID.tif")))
        self.assertEqual(
            actions[0]["source"],
            str(Path("delivery/2016/TreeMap2016_CONUS_TM_ID.tif")),
        )
        self.assertEqual(actions[0]["post_copy_action"], "retain")

    def test_apply_uses_partial_file_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.tif"
            source.write_bytes(b"test bytes")
            target = root / "treemap" / "2023" / "target.tif"
            actions = [
                {
                    "source": str(source),
                    "target": str(target),
                    "size_bytes": source.stat().st_size,
                    "sha256": hashlib.sha256(b"test bytes").hexdigest(),
                    "status": "copy",
                }
            ]

            apply_stage_plan(actions)

            self.assertEqual(source.read_bytes(), b"test bytes")
            self.assertEqual(target.read_bytes(), b"test bytes")
            self.assertFalse(target.with_suffix(".tif.partial").exists())

    def test_plan_does_not_overwrite_different_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "2016" / "TreeMap2016_CONUS_TM_ID.tif"
            target.parent.mkdir()
            target.write_bytes(b"converted")
            manifest = {
                "assets": [
                    {
                        "year": 2016,
                        "attribute": "TM_ID",
                        "target": "delivery/2016/TreeMap2016_CONUS_TM_ID.tif",
                        "output": {
                            "facts": {"size_bytes": 12},
                            "sha256": "abc",
                        },
                    }
                ]
            }

            actions = stage_plan(manifest, root)

            self.assertEqual(actions[0]["status"], "refuse-existing")
            with self.assertRaises(FileExistsError):
                apply_stage_plan(actions)


if __name__ == "__main__":
    unittest.main()