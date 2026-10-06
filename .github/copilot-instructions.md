# Treemap Portolan ingest instructions

This repository contains tooling for ingesting Treemap data into a Portolan catalog and preparing publication to Source Cooperative.

Before you write code or docs, inspect the sibling `portolan-skills` repository and reuse its shared guidance instead of rewriting it here.

Use these shared skills when they fit the task:

- `portolan-bootstrap` for source research, metadata, collection layout, and style planning
- `portolan-cli` for command choice and flag verification
- `sourcecoop` for publish setup and host-specific rules
- `reading-portolan` for query validation and browser-oriented checks

Treat `portolan-spec` as the source of truth. Do not describe the CLI as authoritative over the specification.

Keep this repository focused on Treemap-specific facts and implementation details:

- source endpoints and access method
- schema mapping and field decoding
- data cleaning, transformation, and partitioning decisions
- metadata values that must go into `.portolan/metadata.yaml`
- validation and publish commands that were run against real data

Prefer deterministic scripts over ad hoc manual steps. For expensive operations, provide a preview path when practical.

Use `source.coop` for human-facing links and `data.source.coop` for machine-facing asset URLs when you document published outputs.