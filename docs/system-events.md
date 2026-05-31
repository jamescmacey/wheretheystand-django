---
title: System events
description: Automated workbook creation from monitored sources.
---

## Models

- **MonitoredSource** — `slug`, `handler`, `config`, `default_recipe_key`
- **SystemEvent** — deduped by `(source, external_id)`, links to **Workbook**

## Celery

- `poll_monitored_sources` — poll all active sources, enqueue `process_system_event_task`
- `process_system_event_task` — bootstrap workbook + optional auto-advance

## API

- `GET /v2/system-events/` — list (filter `status`, `source`)
- `POST /v2/system-events/{id}/retry/` — re-run preprocessing
