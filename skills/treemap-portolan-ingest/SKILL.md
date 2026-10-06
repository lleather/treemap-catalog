---
name: treemap-portolan-ingest
description: Use when building or maintaining tooling in this repository to ingest Treemap data into a Portolan catalog, validate the output, and prepare publication to Source Cooperative.
---

# Treemap Portolan ingest

This skill is the repository-specific layer for Treemap ingest work. It does not replace the shared Portolan skills in the sibling `portolan-skills` repository. Use those skills for generic Portolan behavior. Use this skill for the decisions that are specific to this repository and this data source.

## Use this skill when

- you map Treemap source fields into Portolan-ready outputs
- you add or change ingest scripts in this repository
- you document Treemap provenance, schema meaning, or transformation rules
- you prepare validation or publish runs for Treemap outputs

## Shared skills to use first

- `portolan-bootstrap` for source research, metadata, collection layout, mirror-path decisions, and styling
- `portolan-cli` for exact command choice and flag verification
- `sourcecoop` for publish configuration and post-publish checks
- `reading-portolan` for validating outputs with DuckDB or browser-facing examples

Do not duplicate generic CLI help or spec summaries in this repository when the shared skills already cover them.

## What this repository should contain

Keep the repository-specific layer here:

- source URLs, access notes, and fetch dates
- schema mappings and decoded field meanings
- transform logic that turns Treemap data into publishable catalog inputs
- derived-field definitions and the exact query or code that produced them
- validation commands and the data they ran against
- publish-target details and any known limits in upstream source systems

## Working rules

Record the source of every claim. If a field meaning comes from provider metadata, save the URL or document path that proved it. If a number is derived, save the query or code that computed it.

Prefer reproducible scripts over manual editing. If a transformation is expensive, add a preview or sampling path before the full run when practical.

Keep generated outputs separate from source artifacts and scripts. A future agent should be able to see which files are inputs, which files are intermediate products, and which files are publishable outputs.

When you document publish behavior, use `source.coop` for human-facing pages and `data.source.coop` for machine-facing asset URLs.

## Preferred raster sources

Use the separated-attribute raster delivery as a read-only source.
Select files only from the top level of each configured directory.

- 2016: `2016`
- 2020: `2026_UPDATE/2020`
- 2022: `2026_UPDATE/2022`
- 2023: `2023_Production_rerun_final_zone_imputations`

Do not replace the preferred 2020, 2022, or 2023 sources with the default annual directories.
Do not descend into numbered legacy directories.

## COG output

Check every selected TIFF for COG compliance before conversion.
Copy compliant COGs unchanged.
Run conversion locally with GDAL only for files that fail the check.
If GDAL is unavailable, use the matching wheel from
`https://github.com/cgohlke/geospatial-wheels`.

Write validated outputs to the read-write delivery root:
`\\afssxgtacnas104\TreeMap\08_Data_Delivery\06_COGs`.
Use one nested directory for each year.

Convert a noncompliant source to a local temporary file before copying it.
Never modify the separated-attribute source TIFFs.
Never leave a partial file under its final network name.

## Definition of done

A Treemap ingest change is ready when:

- the transform path is reproducible from the repository
- Treemap-specific mappings and assumptions are documented
- validation commands have been run against real output data
- publish instructions identify the destination and required metadata
- repository docs do not drift into generic Portolan reference material that belongs in the shared skills repo