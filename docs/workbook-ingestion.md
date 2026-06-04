---
title: Workbook ingestion
description: Step-based ingestion pipelines for console and system events.
aiAssistedGeneration: true
---

## Overview

Workbooks group staged files on private storage. Each workbook runs a **recipe** (`recipe_key`) as an ordered list of **WorkbookStep** rows. All staging data lives in `WorkbookStep.payload` (JSON). Production writes happen only when a step is **committed**.

## Models

- **Workbook** — `recipe_key`, `source` (`manual` | `system_event`)
- **WorkbookFile** — staged upload (GCS `private_files`)
- **WorkbookStep** — `step_key`, `status`, `payload`, optional production GFK after commit

Batch recipes (e.g. `credit_card_reconciliation`) create one step chain **per file**.

## Recipe: `credit_card_reconciliation`

| Step | Purpose | Commit writes |
|------|---------|---------------|
| `upload` | File present on private GCS | — |
| `link_entities` | Person + dates | — (validation only) |
| `gemini_extract` | AI extraction from GCS (`gs://` URI preferred) | — (`payload.proposal`) |
| `publish_reconciliation` | Staff review | Copy to R2 `documents.File` + `CreditCardReconciliation` + expenses |

Staged files remain on **private GCS** until `publish_reconciliation` is committed, so they are not exposed on the public R2 bucket during review or Gemini processing.

### Payload examples

**link_entities:**
```json
{"person_id": "uuid", "start_date": "2025-01-01", "end_date": "2025-01-31", "workbook_file_id": "uuid"}
```

**gemini_extract (after processing):**
```json
{"proposal": {"concerns": null, "expenses": [...]}, "gemini_batch_item_id": "uuid"}
```

## API (admin session)

- `POST /v2/workbooks/` — `{ "name", "recipe_key" }` then `POST .../ensure-steps/`
- `GET /v2/workbooks/{id}/steps/` — steps + `progress` rollup
- `PATCH /v2/workbooks/{id}/steps/{step_key}/?workbook_file=` — save draft
- `POST .../steps/{step_key}/start|commit|reject/` — step actions

## System events

See `docs/system-events.md`. Monitored sources create system workbooks and advance steps until review gates.

## Recipe: `user_profile_pictures`

Batch recipe for person profile photos (site profile pictures).

| Step | Purpose | Commit writes |
|------|---------|---------------|
| `upload` | Staged image on private GCS | — |
| `link_entities` | Person, original URL, attribution, copyright metadata | — (validation only) |
| `publish_profile_picture` | Staff review | Copy to R2 `documents.File` + set `Person.photo` |

Copyright can reference existing `Licence` / `CopyrightParty` rows or inline `*_create` objects in `file_metadata` (resolved on publish). Workbook `batch_defaults` can pre-fill licence and copyright party IDs for all files.

## Stubs

- `election_donation_return` — registered, not implemented (publish step promotes from GCS)
