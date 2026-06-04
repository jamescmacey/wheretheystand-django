"""Resolve licence and copyright party metadata from workbook step payloads."""

from __future__ import annotations

from wts_app.models.documents import CopyrightParty, Licence


def _strip(value) -> str:
    return str(value or "").strip()


def _resolve_licence(meta: dict) -> str | None:
    licence_id = meta.get("licence_id")
    if licence_id:
        if not Licence.objects.filter(pk=licence_id).exists():
            raise ValueError("licence_id does not exist.")
        return str(licence_id)

    inline = meta.get("licence_create") or meta.get("licence")
    if not isinstance(inline, dict):
        return None
    name = _strip(inline.get("name"))
    if not name:
        return None
    licence_url = _strip(inline.get("licence_url") or inline.get("url"))
    licence, created = Licence.objects.get_or_create(
        name=name,
        defaults={"licence_url": licence_url or ""},
    )
    if not created and licence_url and not licence.licence_url:
        licence.licence_url = licence_url
        licence.save(update_fields=["licence_url", "updated_at"])
    return str(licence.id)


def _resolve_copyright_party(meta: dict, *, id_key: str, inline_key: str) -> str | None:
    party_id = meta.get(id_key)
    if party_id:
        if not CopyrightParty.objects.filter(pk=party_id).exists():
            raise ValueError(f"{id_key} does not exist.")
        return str(party_id)

    inline = meta.get(inline_key)
    if not isinstance(inline, dict):
        return None
    name = _strip(inline.get("name"))
    if not name:
        return None
    website = _strip(inline.get("website") or inline.get("url"))
    party, created = CopyrightParty.objects.get_or_create(
        name=name,
        defaults={"website": website or ""},
    )
    if not created and website and not party.website:
        party.website = website
        party.save(update_fields=["website", "updated_at"])
    return str(party.id)


def resolve_file_metadata_ids(file_metadata: dict) -> dict:
    """
    Return a copy of file_metadata with inline licence/party creates resolved to UUIDs.
    """
    meta = dict(file_metadata or {})
    resolved = dict(meta)

    licence_id = _resolve_licence(meta)
    if licence_id:
        resolved["licence_id"] = licence_id
    resolved.pop("licence_create", None)
    resolved.pop("licence", None)

    owner_id = _resolve_copyright_party(
        meta,
        id_key="copyright_owner_id",
        inline_key="copyright_owner_create",
    )
    if owner_id:
        resolved["copyright_owner_id"] = owner_id
    resolved.pop("copyright_owner_create", None)
    resolved.pop("copyright_owner", None)

    grantor_id = _resolve_copyright_party(
        meta,
        id_key="licence_grantor_id",
        inline_key="licence_grantor_create",
    )
    if grantor_id:
        resolved["licence_grantor_id"] = grantor_id
    resolved.pop("licence_grantor_create", None)
    resolved.pop("licence_grantor", None)

    return resolved


def merge_file_metadata(*sources: dict | None) -> dict:
    """Merge file_metadata dicts; later sources override earlier ones."""
    merged: dict = {}
    for source in sources:
        if not source:
            continue
        merged = {**merged, **source}
    return merged
