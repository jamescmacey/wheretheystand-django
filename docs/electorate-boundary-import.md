---
title: Electorate boundary import (GeoJSON worksheet and upload)
description: Prepare GeometryCollection GeoJSON, build the mapping worksheet, and upload boundaries via management commands.
aiAssistedGeneration: true
---

## Overview

This workflow brings official electorate boundaries from a shapefile into the database as `ElectorateBoundary` records linked to a `ElectorateBoundarySet`. It uses two Django management commands:

- `generate_electorate_boundary_worksheet` — builds a CSV worksheet that maps each geometry index in your GeoJSON to an electorate slug.
- `upload_electorate_boundaries` — reads full and simplified GeometryCollection files plus the completed worksheet (or an alternate mapping), creates document/file records, and attaches boundaries to electorates.

Run commands from the Django project directory with `python manage.py …`.

---

::steps{level="2"}

## 1) Shapefile to GeoJSON and simplification (mapshaper.org)

Use [mapshaper.org](https://mapshaper.org/) to convert and simplify geometries.

1. **Import** your electorate shapefile (or a zip that contains it). Confirm on the map that features look correct and that **feature order is meaningful** — geometry indices in later steps follow the order of geometries in the exported collection.

2. **Full-resolution export**  
   Export a GeoJSON snapshot you will treat as the **full** boundary source. Keep this file as close to the source precision as you need for accurate geometry.

3. **Simplified export**  
   On the same layer topology (or a duplicate import of the same source), apply simplification appropriate for web maps — for example Mapshaper’s **Simplify** tools — then export a second GeoJSON as the **simplified** boundary source. **Geometry count and order must match** the full file: each index `i` should describe the same electorate in both files.

4. **GeometryCollection requirement**  
   Both management commands expect a single JSON object with:

   - `"type": "GeometryCollection"`
   - a `"geometries"` array listing each polygon/multipolygon in order.

   Mapshaper often exports a **FeatureCollection** or other structure. If so, convert to a GeometryCollection by collecting each feature’s `geometry` into the `geometries` array (preserving order). The full and simplified files must remain **parallel**: same length, same index semantics.

5. **Save paths**  
   Place or name files consistently with the defaults used by the commands (for example under `migration/`), or pass explicit `--json-file` / `--full-json` / `--simplified-json` paths in steps 2 and 3.

---

## 2) Worksheet creation and checking (`generate_electorate_boundary_worksheet`)

### Prerequisites

- Electorate rows already exist in the database with **non-empty slugs**.
- Slugs are chosen using **`--electorate-type`** and **`--date`**:
  - **`--electorate-type`**: `all`, `general`, or `māori` (`maori` without macron is accepted; stored type is `maori`).
  - **`--date`**: reference date `YYYY-MM-DD`. The command includes electorates with `valid_from` on or before that date that are still valid on that date (`valid_to` null or `valid_to` ≥ date).

### Generate the worksheet

Example:

```bash
python manage.py generate_electorate_boundary_worksheet \
  --electorate-type general \
  --date 2023-10-14 \
  --json-file migration/general-electorates-2020.json \
  --output-csv migration/electorate_geometry_mapping.csv
```

Other useful flags:

- `--overwrite` — replace an existing output CSV.
- Defaults: `--json-file` → `migration/general-electorates-2020.json`, `--output-csv` → `migration/electorate_geometry_mapping.csv`.

### Output columns

The CSV has:

| Column | Purpose |
|--------|--------|
| `geometry_index` | Index into the GeometryCollection `geometries` array (0-based). |
| `electorate_slug` | **You fill this in** — must match `Electorate.slug` when uploading. |
| `suggested_slug` | Ordered slugs from the database for the given type and date (hints only). |
| `notes` | Optional; ignored by upload if present. |

### Checking the worksheet

1. **Row count** — One row per geometry in the JSON (same count as `geometries.length`).
2. **`electorate_slug`** — Every row you intend to upload must have the correct slug; upload fails if a slug is missing from the database.
3. **Indices** — Must be unique and cover `0 … N-1` without duplicates (upload validates duplicates).
4. **Alignment** — Order in the GeoJSON is arbitrary relative to names; use maps or external metadata to pair each index with the right electorate. `suggested_slug` is alphabetical-by-name order and **may not** match mapshaper order — treat it as a hint only.

---

## 3) Uploading electorate boundaries (`upload_electorate_boundaries`)

### Mapping source

Provide **either**:

- **`--mapping-csv PATH`** — CSV with at least `geometry_index` and `electorate_slug` (extra columns such as `suggested_slug` / `notes` are fine). This is the usual path after completing the worksheet.

**Or**

- **`--use-order-mapping`** — Builds the mapping from `migration/electorates.csv` general rows in file order. Only safe when that order **exactly** matches geometry order. **`--electorates-csv`** overrides the CSV path.

### Required and common flags

- **`--valid-from`** — `YYYY-MM-DD` stored on the `ElectorateBoundarySet` (boundary set validity).
- **`--full-json`** — full GeometryCollection path (default `migration/general-electorates-2020.json`).
- **`--simplified-json`** — simplified GeometryCollection path (default `migration/general-electorates-2020-simplified.json`).
- **`--dry-run`** — validate mapping and print planned actions without saving.

Optional metadata:

- **`--document-name`**, **`--document-description`** — `Document` record (default name/description target general electorates; adjust for Māori boundaries).
- **`--copyright-owner`**, **`--licence-name`**, **`--licence-grantor`** — linked `CopyrightParty` / `Licence` data when non-empty.

### Example

```bash
python manage.py upload_electorate_boundaries \
  --mapping-csv migration/electorate_geometry_mapping.csv \
  --full-json migration/general-electorates-2020.json \
  --simplified-json migration/general-electorates-2020-simplified.json \
  --valid-from 2023-10-14 \
  --dry-run
```

After review, run the same command without `--dry-run`.

### What the upload does

For each mapping row it resolves the electorate by slug, wraps the matching full and simplified geometries as small FeatureCollections, stores two GeoJSON files on a `Document`, and **`update_or_create`s** an `ElectorateBoundary` for `(electorate, boundary_set)` with `shape` and `simplified_shape` pointing at those files.

::

## Quick checklist

1. Two parallel **GeometryCollection** GeoJSON files (full + simplified), same geometry count and order.
2. Worksheet generated with correct **`--electorate-type`** and **`--date`**; **`electorate_slug`** filled and checked.
3. **`upload_electorate_boundaries`** with **`--mapping-csv`**, **`--valid-from`**, and paths to both JSON files; **`--dry-run`** first.

::callout{icon="i-lucide-info" color="neutral"}
This documentation file was generated largely by Cursor.
::