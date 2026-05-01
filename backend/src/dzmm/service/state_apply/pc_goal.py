"""<pc_goal> handler — add / complete / abandon player-character goals."""

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import PCGoal


async def _apply_pc_goal(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    op = attrs.get("type", "add").strip().lower()
    text = content.strip()

    if op == "add":
        if not text:
            return
        priority = attrs.get("priority", "normal").strip().lower()
        if priority not in ("high", "normal", "low"):
            priority = "normal"
        goal = PCGoal(
            session_id=session_id,
            description=text,
            priority=priority,
            status="active",
            introduced_turn=current_turn,
        )
        session.add(goal)
        return

    if op in ("complete", "abandon"):
        goal_id_str = attrs.get("id", "").strip()
        if not goal_id_str.isdigit():
            return
        goal = await session.get(PCGoal, int(goal_id_str))
        if goal is None or goal.session_id != session_id:
            return
        goal.status = "completed" if op == "complete" else "abandoned"
        goal.completed_turn = current_turn
        if text:
            goal.completion_note = text
