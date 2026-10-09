"""ComfyUI HTTP client: submit workflows, poll history, fetch images.

Talks to a running ComfyUI instance (default http://127.0.0.1:8188) over
its plain HTTP API — no websocket needed for fire-and-forget generation:

- POST /prompt  {prompt: <api-format workflow>, client_id} → prompt_id
- GET  /history/{prompt_id} → outputs once status completed
- GET  /view?filename=…&subfolder=…&type=output → image bytes

Stdlib urllib only (same constraint as embedded_model_requests): the
embedded runtime ships zero third-party wheels.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
POLL_INTERVAL_SECONDS = 1.0


class ComfyUIError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedImage:
    filename: str
    subfolder: str
    image_type: str

    @property
    def view_query(self) -> str:
        return urllib.parse.urlencode(
            {
                "filename": self.filename,
                "subfolder": self.subfolder,
                "type": self.image_type,
            }
        )


def submit_workflow(
    base_url: str,
    workflow: dict[str, Any],
    *,
    client_id: str = "dzmm",
    timeout: float = 10.0,
) -> str:
    """Queue an API-format workflow; return its prompt_id."""

    body = json.dumps({"prompt": workflow, "client_id": client_id}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/prompt",
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    prompt_id = payload.get("prompt_id")
    if not prompt_id:
        raise ComfyUIError(f"ComfyUI did not return a prompt_id: {payload}")
    return prompt_id


def fetch_images(
    base_url: str,
    prompt_id: str,
    *,
    timeout_seconds: float = 180.0,
    poll_interval: float = POLL_INTERVAL_SECONDS,
) -> list[GeneratedImage]:
    """Poll /history until the prompt completes; return generated images."""

    deadline = time.monotonic() + timeout_seconds
    url = f"{base_url.rstrip('/')}/history/{prompt_id}"
    while time.monotonic() < deadline:
        with urllib.request.urlopen(url, timeout=10) as response:
            history = json.loads(response.read().decode("utf-8"))
        entry = history.get(prompt_id)
        if entry:
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                raise ComfyUIError(
                    f"ComfyUI workflow failed: {status.get('messages')}"
                )
            outputs = entry.get("outputs") or {}
            images: list[GeneratedImage] = []
            for node_output in outputs.values():
                for image in node_output.get("images") or []:
                    images.append(
                        GeneratedImage(
                            filename=image.get("filename", ""),
                            subfolder=image.get("subfolder", ""),
                            image_type=image.get("type", "output"),
                        )
                    )
            if images:
                return images
        time.sleep(poll_interval)
    raise ComfyUIError(f"ComfyUI generation timed out after {timeout_seconds:.0f}s")


def download_image(
    base_url: str,
    image: GeneratedImage,
    *,
    timeout: float = 30.0,
) -> bytes:
    url = f"{base_url.rstrip('/')}/view?{image.view_query}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def generate(
    base_url: str,
    workflow: dict[str, Any],
    *,
    timeout_seconds: float = 180.0,
) -> tuple[list[GeneratedImage], list[bytes]]:
    """Submit + wait + download. Convenience wrapper for fire-and-forget callers."""

    prompt_id = submit_workflow(base_url, workflow)
    images = fetch_images(base_url, prompt_id, timeout_seconds=timeout_seconds)
    return images, [download_image(base_url, image) for image in images]


def load_workflow(template: dict[str, Any], substitutions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Deep-copy a template workflow and apply per-node input overrides.

    ``substitutions`` maps node_id → {"inputs": {field: value}}; missing
    fields keep the template value so the exported workflow stays the
    single source of truth for models/samplers.
    """

    import copy

    workflow = copy.deepcopy(template)
    for node_id, overrides in substitutions.items():
        node = workflow.get(node_id)
        if node is None:
            continue
        inputs = node.setdefault("inputs", {})
        inputs.update(overrides)
    return workflow
