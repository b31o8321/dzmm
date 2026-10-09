"""Canonical-image pipeline: 文生图定妆 → 图生图延续.

一致性模型（无 LoRA 训练，零等待）：
1. 角色/地点**首次登场**：文生图（外貌描述卡 + 风格前缀，固定 seed）
   → 存为该角色/地点的「基准图」，同时充当 UI 的立绘/场景卡
2. 后续回合的场景插画：**图生图**（基准图为参考 + 当回合情境，denoise 0.5）
   → 人物长相与场景基调延续

数据落点：
- RunState: character_cards/locations 旁挂 ``visual`` 字段
  {trigger, appearance, seed, ref_image}——引擎规则层不读它，仅图像服务使用
- 图片文件: <data_dir>/media/<world_id>/…
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 风格前缀：全局统一画风（可在设置覆盖）；拼在每个提示词头部
DEFAULT_STYLE_PREFIX = (
    "masterpiece, best quality, soft cinematic lighting, detailed illustration, "
    "fantasy storybook style, "
)
DEFAULT_NEGATIVE = (
    "lowres, bad anatomy, bad hands, text, watermark, signature, "
    "multiple views, cropped, worst quality"
)


@dataclass(frozen=True)
class VisualCard:
    """角色/地点的视觉描述卡——提示词的确定性来源。"""

    appearance: str
    trigger: str = ""
    seed: int = 0

    def prompt_fragment(self) -> str:
        parts = [part for part in (self.trigger, self.appearance) if part]
        return ", ".join(parts)


def visual_card_from(entry: dict[str, Any]) -> VisualCard:
    """从 character_card/location 的 visual 字段构建描述卡（缺省安全）。"""

    visual = entry.get("visual") if isinstance(entry, dict) else None
    visual = visual if isinstance(visual, dict) else {}
    appearance = str(
        visual.get("appearance")
        # 降级：直接用 description 的前段当外貌描述（大多数卡都有）
        or (entry.get("description") if isinstance(entry, dict) else "")
        or ""
    ).strip()[:300]
    return VisualCard(
        appearance=appearance,
        trigger=str(visual.get("trigger") or "").strip(),
        seed=int(visual.get("seed") or 0),
    )


def build_prompt(
    *,
    style_prefix: str,
    fragments: list[str],
    scene_note: str = "",
) -> str:
    parts = [style_prefix.strip()]
    parts.extend(fragment for fragment in fragments if fragment.strip())
    if scene_note.strip():
        parts.append(scene_note.strip())
    return ", ".join(part for part in parts if part)


def build_txt2img_workflow(
    template: dict[str, Any],
    *,
    positive_prompt: str,
    negative_prompt: str,
    seed: int,
) -> dict[str, Any]:
    """Fill a txt2img API-format template's sampler/CLIP nodes."""

    workflow = json.loads(json.dumps(template))  # deep copy
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") == "KSampler":
            node.setdefault("inputs", {})["seed"] = seed
            node["inputs"]["noise_seed"] = seed
    for node in workflow.values():
        if not isinstance(node, dict) or node.get("class_type") != "CLIPTextEncode":
            continue
        inputs = node.get("inputs") or {}
        text = str(inputs.get("text") or "")
        # 模板约定：positive 占位文本含 POSITIVE，negative 含 NEGATIVE
        if "NEGATIVE" in text.upper():
            inputs["text"] = negative_prompt
        elif "POSITIVE" in text.upper() or text:
            inputs["text"] = positive_prompt
    return workflow


def build_img2img_workflow(
    template: dict[str, Any],
    *,
    positive_prompt: str,
    negative_prompt: str,
    seed: int,
    denoise: float = 0.5,
    reference_image_filename: str,
) -> dict[str, Any]:
    """Fill an img2img template: LoadImage(reference) → VAEEncode → KSampler."""

    workflow = json.loads(json.dumps(template))
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        inputs = node.setdefault("inputs", {})
        if class_type == "LoadImage":
            inputs["image"] = reference_image_filename
        elif class_type == "KSampler":
            inputs["seed"] = seed
            inputs["noise_seed"] = seed
            inputs["denoise"] = denoise
        elif class_type == "CLIPTextEncode":
            text = str(inputs.get("text") or "")
            if "NEGATIVE" in text.upper():
                inputs["text"] = negative_prompt
            elif text:
                inputs["text"] = positive_prompt
    return workflow


def save_media(
    media_dir: Path,
    world_id: str,
    image_bytes: bytes,
    *,
    kind: str,
    subject_id: str,
    extension: str = "png",
) -> Path:
    """Write one generated image under media/<world_id>/ and return its path."""

    target = media_dir / world_id
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{kind}-{subject_id}-{uuid.uuid4().hex[:8]}.{extension}"
    path.write_bytes(image_bytes)
    return path


def new_client_id() -> str:
    return uuid.uuid4().hex[:12]


# ---- 模板加载（内置 SDXL 模板，可被 ComfyUI 导出的 API 工作流覆盖）----

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "workflows"


def load_workflow_template(kind: str, custom_path: str | None = None) -> dict[str, Any]:
    """Load txt2img/img2img workflow; custom ComfyUI export overrides builtin."""

    if custom_path:
        path = Path(custom_path)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    path = _TEMPLATE_DIR / f"{kind}_sdxl.json"
    return json.loads(path.read_text(encoding="utf-8"))
