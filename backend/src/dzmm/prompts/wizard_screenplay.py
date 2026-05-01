"""v0.2.0 wizard step 5 — screenplay generation that also takes pre-approved NPCs.

We deliberately do **not** modify `outliner_template.build_outliner_messages` —
that function's exact text is depended on by existing screenplay tests + GM
behavior. Instead we wrap it: build the standard outliner messages, then
append a `# 已有 NPC` section to the user message so the model integrates the
wizard's already-confirmed cast into chapters / main_characters.
"""
import json

from dzmm.models.client import Message
from dzmm.prompts.outliner_template import build_outliner_messages


def build_wizard_screenplay_messages(
    world_md: str,
    character_md: str,
    npcs: list[dict],
    genre: str,
    *,
    world_name: str = "",
    character_name: str = "",
) -> list[Message]:
    """Build outliner messages with an additional "pre-approved NPCs" section.

    We pass `world_md` / `character_md` straight through (Markdown blob) — the
    outliner prompt accepts an unstructured world description. world_name /
    character_name are optional convenience params; if not provided we fall
    back to a generic label since the outliner template prepends them.
    """
    msgs = build_outliner_messages(
        world_name=world_name or "（向导生成）",
        world_md=world_md,
        character_name=character_name or "（向导生成）",
        character_md=character_md,
        genre=genre or "悬疑探案",
        custom_prompt="",
    )

    if not npcs:
        return msgs

    # Append NPC summary to the user message (last message). We rebuild
    # rather than mutate so the original Message instances stay immutable.
    npcs_summary_lines = ["", "# 已有 NPC（玩家已审阅，请将这些角色融入剧本）"]
    for n in npcs:
        if not isinstance(n, dict):
            continue
        name = str(n.get("name") or "?").strip()
        role = str(n.get("role") or "").strip()
        desc = str(n.get("description") or "").strip()
        motiv = str(n.get("motivation") or "").strip()
        head = f"- **{name}**" + (f"（{role}）" if role else "")
        npcs_summary_lines.append(head + f"：{desc}" + (f" 动机：{motiv}" if motiv else ""))
    extra = "\n".join(npcs_summary_lines)

    user_msg = msgs[-1]
    new_content = user_msg.content + "\n" + extra
    return [*msgs[:-1], Message(role="user", content=new_content)]


def npcs_summary_json(npcs: list[dict]) -> str:
    """Helper for tests / debugging — same data the prompt embeds, as JSON."""
    return json.dumps(npcs, ensure_ascii=False)
