"""JSON Schema validation for workbook step payloads."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import jsonschema

SCHEMAS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=32)
def load_schema(recipe_key: str, step_key: str) -> dict | None:
    path = SCHEMAS_DIR / recipe_key / f"{step_key}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def validate_payload(recipe_key: str, step_key: str, payload: dict) -> dict:
    schema = load_schema(recipe_key, step_key)
    if schema is None:
        return payload
    jsonschema.validate(instance=payload, schema=schema)
    return payload
