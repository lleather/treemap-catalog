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
