# TreeMap ingest plan

## Scope

Publish TreeMap 2016, 2020, 2022, and 2023 in one collection.
Each year is a STAC Item with 22 single-band COG assets.

The source root is the separated-attribute raster delivery at:

```text
\\afssxgtacnas104\TreeMap\08_Data_Delivery\01_Separated_Attribute_Rasters
```

Use these preferred directories under that root:

| Year | Source directory |
|---|---|
| 2016 | `2016` |
| 2020 | `2026_UPDATE/2020` |
| 2022 | `2026_UPDATE/2022` |
| 2023 | `2023_Production_rerun_final_zone_imputations` |

Read TIFFs directly under each configured source directory.
Do not descend into numbered legacy directories.
Never modify files on the network share.

## Source inventory

Run a read-only preview first:

```powershell
python -m treemap_portolan_ingest inventory `
  --config config/ingest.json `
  --workers 4
```

Add `--write-manifest work/inventory.json` only after the preview succeeds.
The manifest records raster header facts and source paths.
It does not read pixel arrays.

The expected annual substitutions are:

| Years | Quadratic mean diameter | Stand density | Identifier source |
|---|---|---|---|
| 2016 | `QMD_RMRS` | `SDIPCT_RMRS` | `VALUE` |
| 2020, 2022, 2023 | `QMD` | `SDIsum` | `TM_ID` |

Publish the 2016 `VALUE` source as `TM_ID`.
Each `TM_ID` needs its year-specific RAT to map values to FIA `PLT_CN`.
The 2023 publication includes its RAT.
Do not publish another vintage until its matching RAT is available.

## Local GDAL setup

Run COG conversion on the local workstation with GDAL.
Use the Python environment configured for this repository.

The environment currently has GDAL 3.11.4 and the COG driver.
If GDAL is missing, install the matching Windows wheel from
[Christoph Gohlke's geospatial wheels](https://github.com/cgohlke/geospatial-wheels).
Match the wheel to the active Python version and Windows architecture.
Verify the GDAL version and the COG driver before conversion.

Do not install GDAL from an unverified wheel source.
Do not start conversion when the COG driver is unavailable.

## COG compliance and conversion

Check all 88 selected TIFFs for COG compliance first.
Copy compliant COGs without raster conversion.
Convert only noncompliant TIFFs with the local GDAL COG driver.
Read the preferred source directories without modifying them.

Write the completed COGs under:

```text
\\afssxgtacnas104\TreeMap\08_Data_Delivery\06_COGs
```

Use one directory for each year:

```text
06_COGs/
├── 2016/
├── 2020/
├── 2022/
└── 2023/
```

Convert each noncompliant source to a temporary file on a local disk.
Validate the temporary COG before copying it to `06_COGs/<year>/`.
For each compliant source, verify compliance and copy the file unchanged.
Use a temporary destination name during the network copy.
Rename it to the final name only after size and COG checks pass.

Preserve the source CRS, grid, dtype, nodata value, and pixel values.
Use categorical overview resampling for codes and identifiers.
Use continuous overview resampling for measured attributes.
Record the compliance result for every source in the manifest.
Record the exact GDAL creation options for each converted source.

Preview the complete delivery without writing files:

```powershell
python -m treemap_portolan_ingest prepare-cogs `
  --inventory work/inventory.json `
  --metadata config/metadata.json `
  --delivery-manifest work/delivery-manifest.json
```

Use repeatable `--year` and `--attribute` options for a small trial.
For example, prepare only the 2016 identifier after the preview succeeds:

```powershell
python -m treemap_portolan_ingest prepare-cogs `
  --inventory work/inventory.json `
  --metadata config/metadata.json `
  --delivery-manifest work/delivery-manifest.json `
  --year 2016 `
  --attribute TM_ID `
  --confirm
```

The default destination is the `06_COGs` network path above.
Use `--destination` to test with a temporary local directory.
The command writes no output or delivery manifest without `--confirm`.
On resume, it verifies the manifest fingerprint, output SHA-256, and COG structure.
It skips a verified existing output and refuses all other existing targets.

## Catalog staging

Preview the catalog staging operation after COG conversion:

```powershell
python -m treemap_portolan_ingest stage `
  --manifest work/delivery-manifest.json `
  --destination treemap
```

Use `--year` and `--attribute` for a small trial.
The command copies nothing unless `--confirm` is present.

The staged layout is:

```text
treemap/
├── 2016/
├── 2020/
├── 2022/
└── 2023/
```

Use the validated files in `06_COGs/<year>/` as catalog inputs.
Do not stage the original separated-attribute TIFFs.
The source inventory found 87 compliant COGs that can be copied unchanged.
Only the 2016 `VALUE` identifier raster currently requires conversion.
The staging command requires completed COG and pixel validation records.
It verifies each staged copy against the delivery SHA-256.

## Raster Attribute Table preparation

The 2023 RAT source is:

```text
\\afssxgtacnas104\TreeMap\03_outputs\06_Reference_Data\v2023\03_Raster_attributes\TM2023_RAT_tmid_contValues.csv
```

Preview the operation first:

```powershell
python -m treemap_portolan_ingest prepare-rat `
  --metadata config/metadata.json `
  --destination treemap `
  --year 2023
```

Add `--confirm` only after the preview reports the expected source checksum,
69,800 rows, and two new targets.

The command copies the source CSV without modification.
It also writes a Zstandard-compressed Parquet derivative.
It parses source `NA` values as Parquet nulls.
It requires complete and unique `TM_ID` and `PLT_CN` columns.
It refuses to replace an existing output with different content.

## Attribute data dictionary preparation

The source workbook is:

```text
\\afssxgtacnas104\TreeMap\08_Data_Delivery\02_Metadata\2023\Data Dictionary\TreeMap2020_CONUS_DataDictionary.xlsx
```

Preview the normalized CSV export before writing it:

```powershell
python -m treemap_portolan_ingest prepare-data-dictionary `
  --metadata config/metadata.json `
  --destination treemap
```

Add `--confirm` to write `treemap\TreeMap2020_CONUS_DataDictionary.csv`.
The enrichment step uses its matched rows for raster asset and band metadata.
It publishes the CSV as a collection-level metadata asset.

## Catalog generation

Add each year separately because each item has a different date.
Use the calendar year as the temporal interval.
After Portolan creates item JSON, enrich each asset from [the metadata registry](../config/metadata.json).

The enrichment step must preserve machine-derived projection and raster fields.
It adds attribute descriptions and sources, annual version properties, DOI,
citation, the data dictionary asset, and RAT assets.
The RAT assets include checksums, row count, and column descriptions.
Generate `items.parquet` after enrichment.

```powershell
portolan add treemap\2016 --datetime 2016-01-01 --no-thumbnails
portolan add treemap\2020 --datetime 2020-01-01 --no-thumbnails
portolan add treemap\2022 --datetime 2022-01-01 --no-thumbnails
portolan add treemap\2023 --datetime 2023-01-01 --no-thumbnails
python -m treemap_portolan_ingest enrich `
  --catalog . `
  --metadata config/metadata.json `
  --year 2023
portolan stac-geoparquet --collection treemap
portolan readme
```

## Validation

Compare source and converted rasters for grid, CRS, dtype, nodata, statistics, and pixel values.
Verify `LAYOUT=COG`, internal tiling, internal overviews, and compression.
Verify the network copy against the validated local temporary COG.
Then run the Portolan metadata, README, and complete catalog checks.

The complete catalog must contain four items and 88 COG assets.
Each item must contain exactly 22 data assets.
Each published item must also include its year-specific RAT before that year is complete.

Save real commands and results in [validation.md](validation.md).

## Publication

The publication target is [TreeMap on Source Cooperative](https://source.coop/redcastle-resources/treemap).
Machine clients use `https://data.source.coop/redcastle-resources/treemap/`.

Run the push preview before uploading any object.
A human must approve the object list and byte total before the real push.
After publication, test catalog links, CORS, HTTP ranges, `items.parquet`, and representative COG reads.
