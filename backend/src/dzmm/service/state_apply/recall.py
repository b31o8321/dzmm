"""<recall> handler — append NPC name to Session.recall_pending_json."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Session as GameSession


async def _apply_recall(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    """GM-driven NPC recall: signals 'this NPC is back, re-inject full dossier
    next turn.' Appends the name to Session.recall_pending_json (a JSON list).
    The list is drained on the next prompt build."""
    name = (attrs.get("name") or "").strip()
    if not name:
        # Tolerate GM placing the name in body text as a fallback.
        name = (content or "").strip()
    if not name:
        return

    sess = await session.get(GameSession, session_id)
    if sess is None:
        return
    pending = json.loads(sess.recall_pending_json or "[]")
    if not isinstance(pending, list):
        pending = []
    if name not in pending:
        pending.append(name)
    sess.recall_pending_json = json.dumps(pending, ensure_ascii=False)
