from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from treemap_portolan_ingest.stage import apply_stage_plan, stage_plan


class StageTests(unittest.TestCase):
    def test_plan_normalizes_destination_name_and_marks_conversion(self) -> None:
        inventory = {
            "assets": [
                {
                    "year": 2016,
                    "attribute": "TM_ID",
                    "source_path": "source/TreeMap2016_VALUE.tif",
                    "size_bytes": 12,
                    "cog_valid": False,
                }
            ]
        }

        actions = stage_plan(inventory, Path("treemap"))

        self.assertEqual(actions[0]["target"], str(Path("treemap/2016/TreeMap2016_CONUS_TM_ID.tif")))
        self.assertEqual(actions[0]["post_copy_action"], "convert-staged-copy-to-cog")

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
                    "status": "copy",
                }
            ]

            apply_stage_plan(actions)

            self.assertEqual(source.read_bytes(), b"test bytes")
            self.assertEqual(target.read_bytes(), b"test bytes")
            self.assertFalse(target.with_suffix(".tif.partial").exists())

    def test_plan_does_not_overwrite_possible_converted_cog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "2016" / "TreeMap2016_CONUS_TM_ID.tif"
            target.parent.mkdir()
            target.write_bytes(b"converted")
            inventory = {
                "assets": [
                    {
                        "year": 2016,
                        "attribute": "TM_ID",
                        "source_path": "source/TreeMap2016_VALUE.tif",
                        "size_bytes": 12,
                        "cog_valid": False,
                    }
                ]
            }

            actions = stage_plan(inventory, root)

            self.assertEqual(actions[0]["status"], "review-existing-conversion")
            with self.assertRaises(FileExistsError):
                apply_stage_plan(actions)


if __name__ == "__main__":
    unittest.main()