import asyncio

from dzmm.db.models import ModelConfig
from dzmm.models.client import ModelClient
from dzmm.models.ollama import OllamaClient
from dzmm.models.openai_compat import OpenAICompatClient
from dzmm.secrets import get_api_key

# Process-wide concurrency gates, keyed by (cfg.id, max_concurrent). Cloud
# providers like Zhipu glm-4-flash enforce concurrency=1 — multiple in-flight
# requests from the same key all return 429. We hold a single Semaphore per
# config so all clients built for that cfg share the same gate.
#
# Stored by (id, limit) so a config edit that changes the limit gets a fresh
# semaphore instead of an outdated one. Old entries leak (a few bytes each);
# cleanup on cfg delete is not implemented yet.
_concurrency_gates: dict[tuple[int, int], asyncio.Semaphore] = {}


def _gate_for(cfg: ModelConfig) -> asyncio.Semaphore | None:
    limit = int(getattr(cfg, "max_concurrent", 0) or 0)
    if limit <= 0:
        return None
    key = (cfg.id, limit)
    sem = _concurrency_gates.get(key)
    if sem is None:
        sem = asyncio.Semaphore(limit)
        _concurrency_gates[key] = sem
    return sem


def build_client(cfg: ModelConfig) -> ModelClient:
    if cfg.type == "openai_compat":
        api_key = get_api_key(cfg.api_key_ref) if cfg.api_key_ref else ""
        return OpenAICompatClient(
            name=cfg.name,
            base_url=cfg.base_url,
            api_key=api_key or "",
            model=cfg.model_name,
            timeout=cfg.timeout,
            concurrency_gate=_gate_for(cfg),
        )
    if cfg.type == "lm_studio":
        # LM Studio exposes an OpenAI-compatible /v1/chat/completions endpoint
        # locally (default http://localhost:1234/v1). No API key required —
        # OpenAICompatClient with empty key omits the Authorization header.
        return OpenAICompatClient(
            name=cfg.name,
            base_url=cfg.base_url,
            api_key="",
            model=cfg.model_name,
            timeout=cfg.timeout,
            concurrency_gate=_gate_for(cfg),
        )
    if cfg.type == "ollama":
        return OllamaClient(
            name=cfg.name,
            base_url=cfg.base_url,
            model=cfg.model_name,
            timeout=cfg.timeout,
        )
    raise ValueError(f"unknown model type: {cfg.type}")
