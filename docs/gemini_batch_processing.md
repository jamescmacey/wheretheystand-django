---
title: Gemini batch processing
---

# Gemini batch processing

## Overview
This app uses Google AI Studio batch jobs to process uploaded files with Gemini and store results in the database. Batch processing is used to reduce cost and is driven by management commands rather than REST endpoints.

The implementation is model-agnostic: batch jobs are tracked in generic tables and processors can target any model via a generic foreign key.

## Configuration
Set these environment variables:
- `GEMINI_API_KEY`: AI Studio API key used by the Gemini SDK.
- `GEMINI_MODEL`: default model alias used when submitting batch jobs (for example, a `-latest` alias).

The resolved model name is captured when the job is created and can be overwritten later from the response model version when available.

## Data model
### Gemini batch tracking
- `GeminiBatchJob`: one record per Gemini batch job. Stores status, request/response payloads, input/output file names, timestamps, `requested_model`, and `resolved_model`.
- `GeminiBatchItem`: one record per item in a batch job. Uses a generic foreign key (`content_type` + `object_id`) to point to the source model, and stores request/response payloads plus per-item status.

### Credit card expenses
- `CreditCardExpense`: extracted row linked to `CreditCardReconciliation` with `date`, `merchant_name`, `description`, `amount_nzd`, `original_currency_code`, and `original_amount`.

## Workflow
### 1) Submit a batch job
Run: `python manage.py gemini_submit_batches credit_card_reconciliation --batch-size 10`

Optional flags:
- `--ids`: submit only specified IDs (space or comma separated).
- `--limit`: cap the total number of records.
- `--model`: override `GEMINI_MODEL` for this run.
- `--display-name`: set a display name for the Gemini batch job.
- `--include-failed`: include records that previously failed.
- `--dry-run`: show what would be submitted without calling Gemini.

Submitting creates `GeminiBatchJob` and `GeminiBatchItem` rows, uploads each file to Gemini, and submits the batch job. Each item is associated with an output index to keep ordering stable.

### 2) Process completed batches
Run: `python manage.py gemini_process_batches --processor credit_card_reconciliation`

This command:
- Fetches each batch job status from Gemini.
- Updates `resolved_model` from Gemini job metadata or response model versions when consistent.
- Downloads the output file or uses inlined responses when available.
- Parses each response and persists output rows to the database.

## Response format for credit card reconciliations
The processor requests a JSON response that matches a strict schema. Each response should include the `request_id` and an `expenses` array with per-transaction details. Example:
`{"request_id":"<uuid>","expenses":[{"date":"2025-01-15","merchant_name":"Example Store","description":"Optional description","amount_nzd":12.34,"original_currency_code":"NZD","original_amount":12.34}]}`

If the original currency is NZD and `amount_nzd` is missing, the processor will copy `original_amount` into `amount_nzd`. Transactions missing required fields are skipped.

## Extending to new models
To add a new processor:
1. Create a subclass of `GeminiBatchProcessor` in `wts_app/gemini/processors.py`.
2. Implement `get_queryset`, `build_request`, and `handle_response`.
3. Register the processor in `PROCESSOR_REGISTRY`.

The same submit/process management commands can then be used with the new processor name.
