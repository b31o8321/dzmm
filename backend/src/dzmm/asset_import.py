"""Asset import from URLs (v1.7.0 P0) — paste a link, get a DZMM asset.

Fetches an HTTP(S) resource and routes it into the existing import
pipelines by content sniffing: JSON is tried as a SillyTavern V3 card /
World Info, PNG is tried as a base64-embedded character card. Nothing is
executed from the payload; every importer treats content as untrusted.
"""

from __future__ import annotations

import base64
import binascii
import json
import urllib.error
import urllib.request

from .sillytavern import ImportedContent, import_sillytavern, import_sillytavern_png

MAX_URL_BYTES = 16 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 30


class AssetImportError(ValueError):
    """Player-safe URL import failure."""


def fetch_asset(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise AssetImportError("只支持 http(s) 链接。")
    request = urllib.request.Request(url, headers={"user-agent": "dzmm-asset-import/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            declared = response.headers.get("content-length")
            if declared and int(declared) > MAX_URL_BYTES:
                raise AssetImportError("链接内容超过 16MB 导入上限。")
            return response.read(MAX_URL_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise AssetImportError(f"链接返回 HTTP {error.code}。") from error
    except urllib.error.URLError as error:
        raise AssetImportError(f"链接无法访问：{error.reason}") from error
    except TimeoutError as error:
        raise AssetImportError("链接下载超时。") from error


def sniff_body(body: bytes) -> dict[str, str]:
    """Route the fetched bytes by content, not by extension."""

    stripped = body.lstrip()
    if stripped.startswith((b"{", b"[")):
        return {"kind": "json", "payload": body.decode("utf-8", errors="strict")}
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"kind": "png", "payload": base64.b64encode(body).decode("ascii")}
    raise AssetImportError("链接内容不是可识别的资产格式（JSON 或 PNG 角色卡）。")


def import_asset_from_url(url: str) -> ImportedContent:
    body = fetch_asset(url)
    sniffed = sniff_body(body)
    if sniffed["kind"] == "png":
        imported = import_sillytavern_png(sniffed["payload"])
        report = imported.report.model_copy(
            update={"source_format": "url_png_character_card", "source_url": url}
        )
        return imported.model_copy(update={"report": report})
    try:
        payload = json.loads(sniffed["payload"])
    except (ValueError, UnicodeDecodeError) as error:
        raise AssetImportError("链接内容不是有效的 JSON。") from error
    if not isinstance(payload, dict):
        raise AssetImportError("链接 JSON 不是可识别的资产对象。")
    imported = import_sillytavern(payload)
    report = imported.report.model_copy(
        update={"source_format": "url_json_asset", "source_url": url}
    )
    return imported.model_copy(update={"report": report})


def base64_png_size(encoded: str) -> int:
    try:
        return len(base64.b64decode(encoded, validate=True))
    except (binascii.Error, ValueError):
        return 0
