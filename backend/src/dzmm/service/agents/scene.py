"""Scene agent — narrative + dice + state, no NPC say."""
from __future__ import annotations

from collections.abc import AsyncIterator

from dzmm.models.client import GenerationParams, Message, ModelClient, TokenUsage
from dzmm.parsing.events import ParseEvent, UsageSummary
from dzmm.parsing.stream_parser import StreamingTagParser
from dzmm.prompts.scene_v2_template import build_scene_messages


async def run_scene(
    *,
    client: ModelClient,
    pc_name: str,
    plot_directive: str,
    world_md: str,
    character_md: str,
    live_state_text: str,
    key_facts: str,
    recent_messages: list[Message],
    current_action: str,
    params: GenerationParams | None = None,
) -> AsyncIterator[ParseEvent | UsageSummary]:
    """Stream Scene agent's output, parsing XML tags incrementally so the
    SSE consumer can render narrative chunks immediately.

    Yields ParseEvents followed by a final UsageSummary with token counts.
    """
    msgs = build_scene_messages(
        pc_name=pc_name,
        plot_directive=plot_directive,
        world_md=world_md,
        character_md=character_md,
        live_state_text=live_state_text,
        key_facts=key_facts,
        recent_messages=recent_messages,
        current_action=current_action,
    )
    parser = StreamingTagParser()
    usage = TokenUsage()
    async for chunk in client.stream(msgs, params or GenerationParams()):
        if chunk.delta:
            for ev in parser.feed(chunk.delta):
                yield ev
        if chunk.usage is not None:
            usage = chunk.usage
    for ev in parser.finish():
        yield ev
    yield UsageSummary(tokens_in=usage.input_tokens, tokens_out=usage.output_tokens)
