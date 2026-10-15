# Validation record

## Source inventory on October 6, 2026

Input:

```text
2016: \\afssxgtacnas104\TreeMap\08_Data_Delivery\01_Separated_Attribute_Rasters\2016
2020: \\afssxgtacnas104\TreeMap\08_Data_Delivery\01_Separated_Attribute_Rasters\2026_UPDATE\2020
2022: \\afssxgtacnas104\TreeMap\08_Data_Delivery\01_Separated_Attribute_Rasters\2026_UPDATE\2022
2023: \\afssxgtacnas104\TreeMap\08_Data_Delivery\01_Separated_Attribute_Rasters\2023_Production_rerun_final_zone_imputations
```

Command:

```powershell
python -m treemap_portolan_ingest inventory `
  --config config/ingest.json `
  --workers 4 `
  --write-manifest work/inventory.json
```

Result:

```text
Assets: 88
Bytes: 282491331955
COGs: 87
Issues: 0
```

Each preferred source directory contains 22 expected top-level TIFFs.
The 2016 `VALUE` raster is the only file that GDAL did not identify as a COG.
It is tiled and has internal overviews, but its image structure has no `LAYOUT=COG` marker.

The configured source map uses `2026_UPDATE` for 2020 and 2022.
It uses the final-zone-imputation rerun for 2023.
Only 2016 uses the default annual directory.

## Conversion environment on October 6, 2026

The local repository environment reported:

```text
GDAL 3.11.4 "Eganville", released 2025/09/04
COG driver: available
```

The requested destination exists:

```text
\\afssxgtacnas104\TreeMap\08_Data_Delivery\06_COGs
```

No conversion or network write occurred during this check.
The conversion plan now writes one validated COG tree per year under this root.

## Staging preview on October 6, 2026

Command:

```powershell
python -m treemap_portolan_ingest stage `
  --manifest work/inventory.json `
  --destination treemap
```

Result:

```text
Assets: 88
Bytes to copy or replace: 282491331955
Assets requiring COG conversion: 1
Preview only: no files were copied.
```

This preview predates the dedicated COG delivery requirement.
It remains evidence for source size and the original COG assessment.
The replacement workflow checks all 88 selected TIFFs for COG compliance.
It copies the 87 compliant COGs unchanged and converts only failed checks.
It writes validated outputs to `06_COGs/<year>/` with guarded final names.

## Automated tests on October 6, 2026

Command:

```powershell
python -m pytest
```

Result:

```text
15 passed in 2.87s
```

The tests use small GDAL rasters in temporary directories.
They cover unchanged copies, conversion, pixel checks, filters, resume, and overwrite protection.

## COG delivery preview on October 6, 2026

Command:

```powershell
python -m treemap_portolan_ingest prepare-cogs `
  --inventory work/inventory.json `
  --metadata config/metadata.json `
  --delivery-manifest work/delivery-manifest.json
```

Result:

```text
Assets: 88
Copy unchanged: 87
Convert locally: 1
Destination: \\afssxgtacnas104\TreeMap\08_Data_Delivery\06_COGs
Preview only: no files or manifest were written.
```

The preview used the inventoried network source paths.
It did not open pixel arrays or write to the network destination.

## Initial Portolan checks on October 6, 2026

Portolan CLI version:

```text
portolan, version 0.8.0
```

Commands:

```powershell
portolan metadata validate
portolan readme --check
portolan check --metadata --no-data
```

Results:

```text
Validated 1 metadata.yaml file - all valid
All 1 README is up-to-date
Catalog conforms (1 file checked)
```

These checks cover the root catalog only.
Full data validation must wait until the 282,491,331,955 source bytes are staged.

## TreeMap 2023 publication on October 14, 2026

The first publication contains one 2023 item with 22 COG assets.
The upload used the Source Cooperative S3-compatible proxy.

```text
Remote: s3://redcastle-resources/treemap/
Endpoint: https://data.source.coop
Public catalog: https://data.source.coop/redcastle-resources/treemap/catalog.json
Human page: https://source.coop/redcastle-resources/treemap
```

The Source Cooperative CLI supplied refreshable credentials:

```powershell
source-coop login --duration 12h
source-coop creds --format env
```

The publication command used conservative multipart concurrency:

```powershell
portolan push `
  --collection treemap `
  --verbose `
  --concurrency 4 `
  --chunk-concurrency 1 `
  --no-adaptive
```

Result:

```text
Synced 7 metadata files
Pushed versions 1.0.0, 1.0.1, and 1.0.2
Transferred 68.0 GB
Pushed 57 files
```

The live catalog check passed:

```powershell
portolan check `
  --metadata `
  --live `
  --url https://data.source.coop/redcastle-resources/treemap/
```

```text
Catalog conforms (3 files checked)
```

HTTP checks used `items.parquet` and the 2023 canopy-cover COG.
Both files returned `Access-Control-Allow-Origin: *`.
Both returned status 206 for the range `bytes=0-1023`.
The `Content-Range` totals matched the HEAD content lengths.

The published `items.parquet` contained one row with item ID `2023`.
A Rasterio window read from the published canopy-cover COG returned:

```text
CRS: EPSG:5070
Resolution: 30 by 30 meters
Window: 512 by 512 pixels
Data type: uint16
Nodata: 65535
Overviews: 2, 4, 8, 16, 32, 64
```

## TreeMap 2023 RAT local validation on October 14, 2026

Source:

```text
\\afssxgtacnas104\TreeMap\03_outputs\06_Reference_Data\v2023\03_Raster_attributes\TM2023_RAT_tmid_contValues.csv
```

The read-only preparation preview reported:

```text
Rows: 69800
Bytes: 13435850
SHA-256: 93e5e752d32c128892ae3b9b80d5d1dd5f59ba51a77f494d5bdee86ddbffc1dc
CSV target: create
Parquet target: create
```

The confirmed command copied the CSV unchanged and created the Parquet file:

```powershell
python -m treemap_portolan_ingest prepare-rat `
  --metadata config/metadata.json `
  --destination treemap `
  --year 2023 `
  --confirm
```

DuckDB compared both complete tables after parsing source `NA` values as nulls:

```text
Rows: 69800
Distinct TM_ID: 69800
Distinct PLT_CN: 69800
Null TM_ID: 0
Null PLT_CN: 0
CSV rows absent from Parquet: 0
Parquet rows absent from CSV: 0
```

A local raster-to-table check sampled raster row 161 and column 12721:

```text
TM_ID: 3903
PLT_CN: 30761983020004
FORTYPCD raster: 281
FORTYPCD RAT: 281
BALIVE raster: 56.189701080322266
BALIVE RAT: 56.1897
```

The continuous values agree at the precision stored in the source CSV.
The complete automated suite passed:

```text
20 passed, 4 subtests passed in 2.70s
```

## TreeMap 2023 RAT publication on October 14, 2026

The public assets are:

```text
https://data.source.coop/redcastle-resources/treemap/treemap/2023/TreeMap2023_RAT_tmid_contValues.csv
https://data.source.coop/redcastle-resources/treemap/treemap/2023/TreeMap2023_RAT_tmid_contValues.parquet
```

The offline push preview listed all catalog assets because that mode skips the
remote state check. The public catalog was at version 1.0.2.
Three unpublished item-mirror snapshots were collapsed into one version 1.0.3
before publication.

The authenticated push compared the local and remote manifests:

```text
Remote version: 1.0.2
Uploading 1 new/changed asset, skipping 44 unchanged
Synced 9 metadata files
Pushed version: 1.0.3
Pushed 15 files
```

The one changed versioned asset was `items.parquet`.
The metadata sync included the CSV, Parquet, STAC, README, and agent guidance.
No COG was uploaded again.

Portolan did not replace `catalog.json` or `treemap/collection.json` after the
remote version was current. Both small JSON objects were uploaded directly
through the Source Cooperative S3-compatible proxy.
Their public descriptions now state that the 2023 item includes the RAT.

The live table checks returned:

```text
CSV HEAD: 200, 13435850 bytes, Access-Control-Allow-Origin: *
CSV range: 206, bytes 0-1023/13435850
Parquet HEAD: 200, 5814683 bytes, Access-Control-Allow-Origin: *
Parquet range: 206, bytes 0-1023/5814683
CSV SHA-256: 93e5e752d32c128892ae3b9b80d5d1dd5f59ba51a77f494d5bdee86ddbffc1dc
Remote version: 1.0.3
```

The public CSV checksum matches the read-only network source.
DuckDB queried the public Parquet file:

```text
Rows: 69800
Distinct TM_ID: 69800
Distinct PLT_CN: 69800
Null TM_ID: 0
Null PLT_CN: 0
TM_ID 3903: PLT_CN 30761983020004, FORTYPCD 281, BALIVE 56.1897
```

A range-backed Rasterio read used the same public catalog:

```text
Pixel row: 161
Pixel column: 12721
TM_ID raster: 3903
FORTYPCD raster: 281
BALIVE raster: 56.189701080322266
```

The RAT and raster values agree.
The small BALIVE difference reflects the decimal precision in the source CSV.

The live metadata command completed successfully:

```powershell
portolan check `
  --metadata `
  --no-data `
  --live `
  --url https://data.source.coop/redcastle-resources/treemap/
```

```text
Catalog conforms (3 files checked)
```

The CLI still reports 23 registered assets as missing during its local disk
discovery. All referenced files exist locally, and each public RAT and COG URL
used in these checks returned the expected bytes.
