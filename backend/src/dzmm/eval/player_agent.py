import logging
from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.player_template import build_player_messages

log = logging.getLogger(__name__)

_PLAYER_PARAMS = GenerationParams(temperature=0.8, max_tokens=100)


async def generate_player_action(
    messages: list,
    character_md: str,
    character_name: str,
    client: ModelClient,
) -> str:
    pairs: list[tuple[str, str]] = []
    user_msg: str | None = None
    for msg in messages:
        if msg.role == "user":
            user_msg = msg.content
        elif msg.role == "assistant" and user_msg is not None:
            pairs.append((user_msg, msg.content))
            user_msg = None

    prompt_msgs = build_player_messages(
        character_name=character_name,
        character_md=character_md,
        recent_history=pairs,
    )
    try:
        action, _ = await client.complete(prompt_msgs, _PLAYER_PARAMS)
        action = action.strip()
        if not action:
            return "我四处张望，等待下一步的线索。"
        return action
    except Exception as exc:
        log.warning("player_agent failed: %s", exc)
        return "我思考了一下，决定继续观察周围的环境。"
