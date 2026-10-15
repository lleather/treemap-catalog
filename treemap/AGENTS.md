# TreeMap 2023 agent guide

## Overview

This collection contains one 2023 item with 22 single-band COG assets.
The item also includes its Raster Attribute Table in CSV and Parquet.
The collection includes `TreeMap2020_CONUS_DataDictionary.csv`.
Each COG maps one TreeMap forest attribute across the conterminous United States.

Read `collection.json`, then follow its `item` link to `2023/2023.json`.
Select assets by the `data` role rather than by asset key.

## Accessing the data

Use `https://data.source.coop/redcastle-resources/treemap/` for machine access.
The following example reads one raster window without downloading the full COG.

```python
import rasterio

url = (
    "https://data.source.coop/redcastle-resources/treemap/"
    "treemap/2023/TreeMap2023_CONUS_CANOPYPCT.tif"
)

with rasterio.open(url) as src:
    window = rasterio.windows.Window(0, 0, 512, 512)
    canopy = src.read(1, window=window)
    print(src.crs, src.res, canopy.shape)
```

Read `treemap/items.parquet` to discover items without fetching each item JSON.

Query the Raster Attribute Table through its Parquet asset:

```sql
SELECT TM_ID, PLT_CN, FORTYPCD, BALIVE
FROM read_parquet(
  'https://data.source.coop/redcastle-resources/treemap/'
  'treemap/2023/TreeMap2023_RAT_tmid_contValues.parquet'
)
WHERE TM_ID = 3903;
```

The original CSV is available at the same path with a `.csv` suffix.

## Schema and field notes

Every data asset has one band. Its name matches the attribute suffix in the file name.
The item metadata records each band description, source, unit, data type, nodata value, and embedded statistics.
The standalone data dictionary preserves the publisher's complete attribute definitions and FIADB source notes.

`TM_ID` identifies an imputed TreeMap record. Do not compare this value across vintages.
The 2023 Raster Attribute Table contains 69,800 rows.
Both `TM_ID` and FIA `PLT_CN` are complete and unique, so the join is one-to-one.
The Parquet derivative represents source `NA` values as nulls.

The table column `CARBON_DOWN_DEAD` corresponds to the `CARBON_DWN` raster.
`ForTypName` and `FldTypName` provide names for their adjacent forest-type codes.

`FLDSZCD`, `FLDTYPCD`, `FORTYPCD`, and `STDSZCD` are categorical.
Their band metadata includes class values, names, and color hints.

## Data quality and usage notes

The rasters use EPSG:5070 with 30-meter pixels.
The footprint covers the forested extent of the conterminous United States.

Read windows or overviews instead of complete pixel arrays.
The COGs include internal overviews and support HTTP range requests.

The 2023 source is the final-zone-imputation production rerun.
The source DOI is [10.2737/RDS-2026-0038](https://doi.org/10.2737/RDS-2026-0038).

## Example inspection

This example reads embedded statistics from STAC instead of computing them from pixels.

```python
import json
from urllib.request import urlopen

item_url = (
    "https://data.source.coop/redcastle-resources/treemap/"
    "treemap/2023/2023.json"
)

with urlopen(item_url) as response:
    item = json.load(response)

for key, asset in item["assets"].items():
    if "data" not in asset.get("roles", []):
        continue
    band = asset["bands"][0]
    print(key, band["name"], band.get("unit"), band.get("statistics"))
```

This example reads a public `TM_ID` pixel, then resolves its FIA condition:

```python
import duckdb
import rasterio
from rasterio.windows import Window

root = "https://data.source.coop/redcastle-resources/treemap/treemap/2023/"
tm_id_url = root + "TreeMap2023_CONUS_TM_ID.tif"
rat_url = root + "TreeMap2023_RAT_tmid_contValues.parquet"

with rasterio.open(tm_id_url) as src:
    tm_id = int(src.read(1, window=Window(12721, 161, 1, 1))[0, 0])

row = duckdb.sql(
    "SELECT TM_ID, PLT_CN, FORTYPCD, BALIVE "
    f"FROM read_parquet('{rat_url}') WHERE TM_ID = {tm_id}"
).fetchone()
print(row)
```

## Related data

Use the FIA DataMart for plot and tree records.
Join through the published 2023 `TM_ID` to `PLT_CN` mapping.
