"""Director run triggers — when does the Director agent fire each turn?

Default cadence: every 5 turns in the background. Sync triggers fire
when the prior turn's outcome demands fresh long-term reasoning:
- bootstrap (first run)
- chapter_advance (last turn emitted <chapter_advance/>)
- plot_turn major (last turn emitted <plot_turn impact="major">)
- hp / sanity <= 5 (PC in critical state — needs rescue or ending)
- hidden_event maturity reached
"""
from __future__ import annotations

DIRECTOR_INTERVAL_TURNS = 5
HP_CRITICAL = 5
SANITY_CRITICAL = 5


def should_run_director(stream, session, current_turn: int) -> tuple[bool, str]:
    """Return (fire?, reason). `stream` has .last_run_turn; `session` has the
    fields shown in the test stub (built by the orchestrator).
    """
    if stream.last_run_turn == 0:
        return True, "bootstrap"
    if getattr(session, "chapter_advanced_last_turn", False):
        return True, "chapter_advance"
    if getattr(session, "major_plot_turn_last_turn", False):
        return True, "plot_turn_major"
    if int(getattr(session, "hp", 99)) <= HP_CRITICAL:
        return True, "hp_critical"
    if int(getattr(session, "sanity", 99)) <= SANITY_CRITICAL:
        return True, "sanity_critical"
    if getattr(session, "hidden_event_due", False):
        return True, "hidden_event_due"
    if (current_turn - stream.last_run_turn) >= DIRECTOR_INTERVAL_TURNS:
        return True, "interval"
    return False, "skip"
