from dzmm.db.models import ModelConfig
from dzmm.models.client import ModelClient
from dzmm.models.ollama import OllamaClient
from dzmm.models.openai_compat import OpenAICompatClient
from dzmm.secrets import get_api_key


def build_client(cfg: ModelConfig) -> ModelClient:
    if cfg.type == "openai_compat":
        api_key = get_api_key(cfg.api_key_ref) if cfg.api_key_ref else ""
        return OpenAICompatClient(
            name=cfg.name,
            base_url=cfg.base_url,
            api_key=api_key or "",
            model=cfg.model_name,
            timeout=cfg.timeout,
        )
    if cfg.type == "ollama":
        return OllamaClient(
            name=cfg.name,
            base_url=cfg.base_url,
            model=cfg.model_name,
            timeout=cfg.timeout,
        )
    raise ValueError(f"unknown model type: {cfg.type}")
