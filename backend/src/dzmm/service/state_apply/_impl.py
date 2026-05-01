"""state_apply dispatcher — routes parsed tags to per-domain handlers.

After the r4-a refactor, every handler lives in its own per-tag module
under `state_apply/`. This file now contains only:
  - `apply_tags(...)` — the dispatcher
  - re-exports for legacy callers that imported handler symbols from `_impl`
    directly (kept stable for `from state_apply._impl import *` users).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.parsing.events import TagComplete
from dzmm.service.state_apply.character_xp import _apply_character_xp
from dzmm.service.state_apply.era import _apply_era_begin
from dzmm.service.state_apply.hidden_event import _apply_hidden_event
from dzmm.service.state_apply.npc import (
    _NER_CONTEXT_CUES,
    _NER_STOPWORDS,
    _NPC_REVEALABLE_FIELDS,
    _apply_npc_update,
    _auto_reveal_for_create,
    _explicit_npc_names_from_tags,
    _hanzi_ngrams,
    _ner_extract_candidate_names,
    _parse_reveal_attr,
    _register_npc_ner_fallback,
)
from dzmm.service.state_apply.npc_relation import _apply_npc_relation
from dzmm.service.state_apply.pc_goal import _apply_pc_goal
from dzmm.service.state_apply.pc_mood import _apply_pc_mood
from dzmm.service.state_apply.plot_event import _apply_plot_event
from dzmm.service.state_apply.recall import _apply_recall
from dzmm.service.state_apply.screenplay import (
    _apply_chapter_advance,
    _apply_ending,
    _apply_event_complete,
    _apply_plot_turn,
)
from dzmm.service.state_apply.location import _apply_location_enter
from dzmm.service.state_apply.state_change import _apply_state_change

# Re-export for callers that imported these names from `_impl` directly
# (e.g. via the `from _impl import *` wildcard in __init__.py).
__all__ = [
    "_NER_CONTEXT_CUES",
    "_NER_STOPWORDS",
    "_NPC_REVEALABLE_FIELDS",
    "_apply_npc_update",
    "_auto_reveal_for_create",
    "_explicit_npc_names_from_tags",
    "_hanzi_ngrams",
    "_ner_extract_candidate_names",
    "_parse_reveal_attr",
    "_register_npc_ner_fallback",
    "apply_tags",
]


async def apply_tags(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    tags: list[TagComplete],
    narrative_text: str = "",
    *,
    character_name: str = "",
) -> None:
    """Mutate CharState and NPC rows based on parsed tags. Caller commits.

    `narrative_text` is the raw narrative (concatenated from streamed
    NarrativeDelta events). It's used by the lightweight NPC NER fallback to
    register stub NPCs the GM mentions but forgets to declare via <npc_update>.

    `character_name` is the PC's name. The NER fallback uses it to suppress
    stubs whose name is a substring of the PC's own name (e.g. "塞巴" /
    "奥斯特" must not become NPCs when PC is "塞巴斯蒂安·冯·奥斯特").
    """
    for tag in tags:
        if tag.name == "state_change":
            await _apply_state_change(session, session_id, tag.content)
        elif tag.name == "npc_update":
            await _apply_npc_update(
                session, session_id, current_turn, tag.attrs, tag.content
            )
        elif tag.name == "plot_event":
            await _apply_plot_event(session, session_id, current_turn, tag.attrs, tag.content)
        elif tag.name == "character_xp":
            await _apply_character_xp(session, session_id, tag.attrs, tag.content)
        elif tag.name == "recall":
            await _apply_recall(session, session_id, tag.attrs, tag.content)
        elif tag.name == "era_begin":
            await _apply_era_begin(session, session_id, current_turn, tag.attrs, tag.content)
        elif tag.name == "pc_goal":
            await _apply_pc_goal(session, session_id, current_turn, tag.attrs, tag.content)
        elif tag.name == "pc_mood":
            await _apply_pc_mood(session, session_id, tag.content)
        elif tag.name == "npc_relation":
            await _apply_npc_relation(
                session, session_id, current_turn, tag.attrs, tag.content
            )
        elif tag.name == "hidden_event":
            await _apply_hidden_event(
                session, session_id, current_turn, tag.attrs, tag.content
            )
        elif tag.name == "chapter_advance":
            await _apply_chapter_advance(session, session_id, tag.attrs, current_turn)
        elif tag.name == "event_complete":
            await _apply_event_complete(session, session_id, tag.attrs, current_turn)
        elif tag.name == "plot_turn":
            await _apply_plot_turn(session, session_id, tag.attrs, current_turn)
        elif tag.name == "ending":
            await _apply_ending(session, session_id, tag.attrs, current_turn)
        elif tag.name == "location_enter":
            await _apply_location_enter(session, session_id, current_turn, tag.attrs, tag.content)

    # Light NER fallback: if narrative mentions names the GM forgot to register
    # via <npc_update>, register them as stubs so the next prompt's NPC list
    # at least surfaces the name (even if details are missing).
    if narrative_text and narrative_text.strip():
        explicit_names = _explicit_npc_names_from_tags(tags)
        await _register_npc_ner_fallback(
            session,
            session_id,
            current_turn,
            narrative_text,
            explicit_names,
            character_name=character_name,
        )
