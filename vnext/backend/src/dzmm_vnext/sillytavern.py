from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import zlib
from typing import Any

from pydantic import BaseModel

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PNG_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024

# High-frequency chara_card_v3 fields preserved verbatim on import so a later
# export can hand them back to SillyTavern without loss.
_V3_PRESERVED_EXTRAS = (
    "alternate_greetings",
    "creator_notes",
    "creator",
    "character_version",
    "tags",
    "system_prompt",
    "post_history_instructions",
)


class ImportReport(BaseModel):
    source_format: str
    supported_fields: list[str]
    preserved_fields: list[str]
    ignored_fields: list[str]
    warnings: list[str]


class ImportedContent(BaseModel):
    suggested_hero: dict[str, Any] | None
    lorebook: dict[str, list[dict[str, Any]]]
    character_cards: list[dict[str, Any]]
    report: ImportReport


def import_sillytavern(payload: dict[str, Any]) -> ImportedContent:
    if payload.get("spec") == "chara_card_v3" and isinstance(payload.get("data"), dict):
        return _import_v3_card(payload)
    if isinstance(payload.get("entries"), (dict, list)):
        return _import_world_info(payload)
    raise ValueError("unsupported SillyTavern content: expected V3 card or World Info entries")


def import_sillytavern_png(encoded_png: str) -> ImportedContent:
    """Import standard `chara` PNG metadata without executing card content."""
    try:
        image = base64.b64decode(encoded_png, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("PNG payload is not valid base64") from error
    if len(image) > MAX_PNG_BYTES:
        raise ValueError("PNG payload exceeds 16 MiB import limit")
    card = _decode_png_card(image)
    imported = import_sillytavern(card)
    report = imported.report.model_copy(
        update={
            "source_format": "sillytavern_v3_png_character_card",
            "supported_fields": ["PNG chara metadata", *imported.report.supported_fields],
        }
    )
    return imported.model_copy(update={"report": report})


def _import_v3_card(payload: dict[str, Any]) -> ImportedContent:
    data = payload["data"]
    name = _string(data.get("name")) or "Imported character"
    book = data.get("character_book") if isinstance(data.get("character_book"), dict) else {}
    entries = book.get("entries", [])
    lorebook_entries, warnings = _entries_to_lorebook_entries(entries, "card")
    profile = {
        key: data[key]
        for key in ("description", "personality", "scenario", "first_mes", "mes_example")
        if _string(data.get(key))
    }
    extras = {
        key: data[key]
        for key in _V3_PRESERVED_EXTRAS
        if data.get(key) not in (None, "", [])
    }
    return ImportedContent(
        suggested_hero={"name": name, "profile": profile},
        lorebook={"entries": lorebook_entries},
        character_cards=[
            {
                "id": _card_id(name),
                "name": name,
                "format": "sillytavern_v3",
                "mapped": {
                    **profile,
                    **extras,
                    "character_book_entry_ids": [entry["id"] for entry in lorebook_entries],
                },
                "source_payload": payload,
            }
        ],
        report=ImportReport(
            source_format="sillytavern_v3_character_card",
            supported_fields=[
                "data.name",
                "data.character_book.entries",
                *[f"data.{key}" for key in _V3_PRESERVED_EXTRAS],
            ],
            preserved_fields=[
                "data.description",
                "data.personality",
                "data.scenario",
                "v3 metadata fields",
                "entry raw fields",
            ],
            ignored_fields=["extensions"],
            warnings=warnings,
        ),
    )


def _import_world_info(payload: dict[str, Any]) -> ImportedContent:
    lorebook_entries, warnings = _entries_to_lorebook_entries(payload["entries"], "world-info")
    return ImportedContent(
        suggested_hero=None,
        lorebook={"entries": lorebook_entries},
        character_cards=[],
        report=ImportReport(
            source_format="sillytavern_world_info",
            supported_fields=["entries.keys", "entries.content", "entries.constant", "entries.order"],
            preserved_fields=["entry raw fields"],
            ignored_fields=[],
            warnings=warnings,
        ),
    )


def _entries_to_lorebook_entries(
    entries: Any, prefix: str
) -> tuple[list[dict[str, Any]], list[str]]:
    source_entries = entries.values() if isinstance(entries, dict) else entries
    if not isinstance(source_entries, list) and not hasattr(source_entries, "__iter__"):
        return [], ["entries is not iterable"]
    lorebook_entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    used_ids: set[str] = set()
    for index, raw in enumerate(source_entries):
        if not isinstance(raw, dict):
            warnings.append(f"entry {index} is not an object and was ignored")
            continue
        body = _string(raw.get("content"))
        if not body:
            warnings.append(f"entry {index} has no content and was ignored")
            continue
        keys = _keywords(raw.get("keys", raw.get("key", [])))
        activation = "always" if raw.get("constant") or raw.get("always") or not keys else "keyword"
        entry_id = _unique_id(f"{prefix}-{raw.get('id', index)}", used_ids)
        used_ids.add(entry_id)
        lorebook_entries.append(
            {
                "id": entry_id,
                "title": _string(raw.get("comment")) or (keys[0] if keys else f"Imported lore {index + 1}"),
                "body": body,
                "activation": activation,
                "keywords": keys,
                "priority": _priority(raw),
                "source": {"sillytavern": raw},
            }
        )
    return lorebook_entries, warnings


def _keywords(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [item.strip() for item in values if isinstance(item, str) and item.strip()]


def _priority(raw: dict[str, Any]) -> int:
    value = raw.get("insertion_order", raw.get("order", 0))
    return max(0, min(100, value if isinstance(value, int) else 0))


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _unique_id(raw: str, used_ids: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_-]+", "-", raw.casefold()).strip("-") or "entry"
    if not base[0].isalpha():
        base = f"entry-{base}"
    base = base[:64]
    candidate, suffix = base, 2
    while candidate in used_ids:
        candidate = f"{base[:60]}-{suffix}"
        suffix += 1
    return candidate


def _card_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.casefold()).strip("-")
    if slug:
        return _unique_id(f"card-{slug}", set())
    return f"card-{hashlib.sha256(name.encode()).hexdigest()[:12]}"


def _decode_png_card(image: bytes) -> dict[str, Any]:
    if not image.startswith(PNG_SIGNATURE):
        raise ValueError("character card must be a PNG file")
    offset = len(PNG_SIGNATURE)
    while offset < len(image):
        if offset + 12 > len(image):
            raise ValueError("PNG metadata is truncated")
        length = int.from_bytes(image[offset : offset + 4], "big")
        chunk_type = image[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(image):
            raise ValueError("PNG metadata is truncated")
        chunk = image[offset + 8 : offset + 8 + length]
        offset = chunk_end
        text = _png_text(chunk_type, chunk)
        if text is None:
            continue
        keyword, value = text
        if keyword.casefold() != "chara":
            continue
        try:
            payload = json.loads(base64.b64decode(value, validate=True))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise ValueError("PNG chara metadata is not a valid base64 JSON card") from error
        if not isinstance(payload, dict):
            raise TypeError("PNG chara metadata must decode to a JSON object")
        return payload
    raise ValueError("PNG does not contain SillyTavern chara metadata")


def _png_text(chunk_type: bytes, chunk: bytes) -> tuple[str, bytes] | None:
    if chunk_type == b"tEXt":
        return _split_png_text(chunk)
    if chunk_type == b"zTXt":
        keyword, payload = _split_png_text(chunk)
        if not payload or payload[0] != 0:
            raise ValueError("PNG zTXt metadata uses an unsupported compression method")
        return keyword, _decompress_metadata(payload[1:])
    if chunk_type != b"iTXt":
        return None
    parts = chunk.split(b"\0", 4)
    if len(parts) != 5:
        raise ValueError("PNG iTXt metadata is malformed")
    keyword, compressed, compression_method, _language, translated_and_text = parts
    translated_parts = translated_and_text.split(b"\0", 1)
    if len(translated_parts) != 2:
        raise ValueError("PNG iTXt metadata is malformed")
    _translated_keyword, payload = translated_parts
    if compressed == b"\0":
        return _decode_keyword(keyword), payload
    if compressed == b"\x01" and compression_method == b"\0":
        return _decode_keyword(keyword), _decompress_metadata(payload)
    raise ValueError("PNG iTXt metadata uses an unsupported compression method")


def _split_png_text(chunk: bytes) -> tuple[str, bytes]:
    parts = chunk.split(b"\0", 1)
    if len(parts) != 2:
        raise ValueError("PNG text metadata is malformed")
    return _decode_keyword(parts[0]), parts[1]


def _decode_keyword(value: bytes) -> str:
    try:
        return value.decode("latin-1")
    except UnicodeDecodeError as error:
        raise ValueError("PNG metadata keyword is invalid") from error


def _decompress_metadata(value: bytes) -> bytes:
    try:
        decompressor = zlib.decompressobj()
        result = decompressor.decompress(value, MAX_METADATA_BYTES + 1)
        result += decompressor.flush(MAX_METADATA_BYTES + 1 - len(result))
    except zlib.error as error:
        raise ValueError("PNG compressed metadata is invalid") from error
    if len(result) > MAX_METADATA_BYTES or decompressor.unconsumed_tail:
        raise ValueError("PNG metadata exceeds 8 MiB import limit")
    return result
