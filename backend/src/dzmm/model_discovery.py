"""LAN discovery for local model servers (Ollama / LM Studio / OpenAI-compatible).

Powers the mobile model-configuration flow: instead of hand-typing IP + model
name, the app scans the local /24 for well-known ports and pulls each server's
model catalog. Network probing is factored behind injectable callables so the
subnet sweep is deterministically testable.
"""

from __future__ import annotations

import asyncio
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

# port → provider hint; order matters only for documentation
DEFAULT_PORTS: tuple[tuple[int, str], ...] = (
    (11434, "ollama"),
    (1234, "lm_studio"),
    (8080, "openai_compat"),
    (8000, "openai_compat"),
)
SCAN_TIMEOUT_SECONDS = 0.35
SCAN_CONCURRENCY = 96
SCAN_SUBNET_LIMIT = 256  # one /24


@dataclass(frozen=True)
class DiscoveredServer:
    host: str
    port: int
    provider_hint: str
    base_url: str
    models: list[str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "provider_hint": self.provider_hint,
            "base_url": self.base_url,
            "models": self.models,
        }


def _normalize_base_url(provider_type: str, base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if provider_type != "ollama" and not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    if provider_type == "ollama" and normalized.endswith("/v1"):
        normalized = normalized[: -len("/v1")]
    return normalized


def _models_from_payload(provider_type: str, payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    if provider_type == "ollama":
        items = payload.get("models")
    else:
        items = payload.get("data")
    names: list[str] = []
    for item in items or []:
        if isinstance(item, dict):
            name = item.get("name") or item.get("id")
            if isinstance(name, str) and name:
                names.append(name)
    return names


async def fetch_remote_models(
    provider_type: str, base_url: str, api_key: str | None = None, timeout: float = 4.0
) -> list[str]:
    """Pull the model catalog from an Ollama / OpenAI-compatible server."""

    if provider_type not in ("ollama", "lm_studio", "openai_compat"):
        raise ValueError(f"unsupported provider type: {provider_type}")
    normalized = _normalize_base_url(provider_type, base_url)
    path = "/api/tags" if provider_type == "ollama" else "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None, lambda: _http_get_json(f"{normalized}{path}", headers, timeout)
    )
    return _models_from_payload(provider_type, response)


def _detect_local_subnet() -> str | None:
    """Return the local /24 prefix (e.g. ``192.168.199``) via a UDP socket."""

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    return ".".join(parts[:3])


async def _classify(host: str, port: int, timeout: float) -> DiscoveredServer | None:
    """Identify the provider on host:port and pull its model catalog."""

    for provider, path in (
        ("ollama", "/api/tags"),
        ("openai_compat", "/v1/models"),
    ):
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout
            )
        except (OSError, TimeoutError):
            return None
        writer.close()
        scheme = "https" if port == 443 else "http"
        base = f"{scheme}://{host}:{port}"
        loop = asyncio.get_running_loop()
        try:
            url = f"{base}{path}"
            payload = await loop.run_in_executor(
                None, lambda url=url: _http_get_json(url, {}, timeout)
            )
        except (OSError, ValueError):
            continue
        models = _models_from_payload(provider, payload)
        if provider == "ollama" or models:
            hint = "lm_studio" if (provider == "openai_compat" and port == 1234) else provider
            return DiscoveredServer(
                host=host,
                port=port,
                provider_hint=hint,
                base_url=_normalize_base_url(hint, base),
                models=models,
            )
    return None


def _http_get_json(url: str, headers: dict[str, str], timeout: float) -> Any:
    """Blocking GET returning parsed JSON; runs on a worker thread."""

    request = urllib.request.Request(url, headers={"accept": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if getattr(response, "status", 200) != 200:
            raise OSError(f"HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


async def scan_lan(
    *,
    subnet: str | None = None,
    ports: list[int] | None = None,
    timeout: float = SCAN_TIMEOUT_SECONDS,
    prober=None,
) -> list[dict[str, Any]]:
    """Sweep the local /24 on well-known model-server ports.

    ``prober`` replaces ``_classify`` in tests; production keeps the default.
    """

    prefix = subnet or _detect_local_subnet()
    if not prefix:
        return []
    port_map = tuple(
        (port, hint)
        for port, hint in DEFAULT_PORTS
        if ports is None or port in ports
    ) or DEFAULT_PORTS
    classify = prober or _classify

    async def one(host: str, port: int) -> DiscoveredServer | None:
        try:
            return await asyncio.wait_for(classify(host, port, timeout), timeout=timeout + 1.5)
        except (TimeoutError, OSError):
            return None

    tasks = [
        one(f"{prefix}.{last}", port)
        for last in range(1, SCAN_SUBNET_LIMIT)
        for port, _hint in port_map
    ]
    if len(tasks) > SCAN_CONCURRENCY:
        # bounded concurrency without pulling in a semaphore per task
        results: list[DiscoveredServer | None] = []
        for start in range(0, len(tasks), SCAN_CONCURRENCY):
            results.extend(await asyncio.gather(*tasks[start : start + SCAN_CONCURRENCY]))
    else:
        results = await asyncio.gather(*tasks)
    servers = [item for item in results if item is not None]
    servers.sort(key=lambda s: (s.host, s.port))
    return [item.to_payload() for item in servers]
