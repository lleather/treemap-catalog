from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from treemap_portolan_ingest.dictionary import prepare_attribute_dictionary


def _write_workbook(path: Path) -> None:
    shared = [
        "Date reviewed",
        "FIA User Guide version ",
        "Column name ",
        "Attribute name",
        "Units",
        "Display name for attribute layer",
        "Short description",
        "Long Description  ",
        "Source (table/column/query); Sec = FIADB manual section ",
        "ALSTK",
        "All-LiveTree Stocking",
        "percent",
        "All live tree stocking (percent)",
        "The sum of stocking percent values of all live trees.",
        "From COND.ALSTK (Sec. 2.5.52)",
    ]
    shared_xml = "".join(f"<si><t>{value}</t></si>" for value in shared)
    sheet_xml = """
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>46078</v></c></row>
    <row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>9.4</v></c></row>
    <row r="4">
      <c r="A4" t="s"><v>2</v></c><c r="B4" t="s"><v>3</v></c>
      <c r="C4" t="s"><v>4</v></c><c r="D4" t="s"><v>5</v></c>
      <c r="E4" t="s"><v>6</v></c><c r="F4" t="s"><v>7</v></c>
      <c r="G4" t="s"><v>8</v></c>
    </row>
    <row r="5">
      <c r="A5" t="s"><v>9</v></c><c r="B5" t="s"><v>10</v></c>
      <c r="C5" t="s"><v>11</v></c><c r="E5" t="s"><v>12</v></c>
      <c r="F5" t="s"><v>13</v></c><c r="G5" t="s"><v>14</v></c>
    </row>
  </sheetData>
</worksheet>
"""
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            """
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>
""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Target="worksheets/sheet1.xml"
   Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>
</Relationships>
""",
        )
        archive.writestr("xl/sharedStrings.xml", f"<sst xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">{shared_xml}</sst>")
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


class DictionaryTests(unittest.TestCase):
    def test_previews_then_writes_normalized_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "dictionary.xlsx"
            _write_workbook(source)
            metadata_path = root / "metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "attribute_dictionary": {
                            "source": str(source),
                            "expected_size": source.stat().st_size,
                            "expected_sha256": hashlib.sha256(
                                source.read_bytes()
                            ).hexdigest(),
                            "worksheet": "Sheet1",
                            "csv_name": "dictionary.csv",
                        }
                    }
                ),
                encoding="utf-8",
            )

            preview = prepare_attribute_dictionary(
                metadata_path,
                root / "catalog",
            )

            self.assertEqual(preview["status"], "create")
            self.assertFalse((root / "catalog").exists())

            applied = prepare_attribute_dictionary(
                metadata_path,
                root / "catalog",
                confirm=True,
            )

            output = (root / "catalog" / "dictionary.csv").read_text(
                encoding="utf-8"
            )
            self.assertEqual(applied["status"], "created")
            self.assertIn("Date reviewed,2026-02-25", output)
            self.assertIn("Column name,Attribute name,Units", output)
            self.assertIn("ALSTK,All-LiveTree Stocking,percent", output)


if __name__ == "__main__":
    unittest.main()
