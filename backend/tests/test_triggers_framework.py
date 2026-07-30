"""Tests for framework-mode (open-world) Director triggers.

Covers the five new event-driven triggers added in v0.11 Batch 3, plus the
shorter interval logic and non-regression for screenplay-only sessions.
"""
from types import SimpleNamespace


from dzmm.service.agents.triggers import (
    DIRECTOR_INTERVAL_TURNS,
    DIRECTOR_INTERVAL_TURNS_FRAMEWORK,
    should_run_director,
)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _stream(last_run_turn: int):
    return SimpleNamespace(last_run_turn=last_run_turn)


def _session(**kwargs):
    """Build a trigger-state session stub.

    Defaults represent a healthy, screenplay-mode session well within the
    interval — so no trigger fires unless kwargs explicitly set one.
    """
    base = dict(
        # screenplay-mode fields
        turn_count=5,
        doom_score=0,
        scene_turn_count=1,
        chapter_advanced_last_turn=False,
        major_plot_turn_last_turn=False,
        hp=20,
        sanity=20,
        hidden_event_due=False,
        # framework-mode fields
        is_framework_mode=False,
        event_triggered_last_turn=False,
        event_completed_last_turn=False,
        phase_advanced_last_turn=False,
        faction_tension_breached=False,
        proactive_npc_pending=False,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


# ──────────────────────────────────────────────────────────────
# Individual open-world trigger tests
# ──────────────────────────────────────────────────────────────

def test_event_completed_last_turn_fires():
    fire, reason = should_run_director(
        _stream(4),
        _session(is_framework_mode=True, event_completed_last_turn=True),
        current_turn=5,
    )
    assert fire
    assert reason == "event_completed"


def test_event_triggered_last_turn_fires():
    fire, reason = should_run_director(
        _stream(4),
        _session(is_framework_mode=True, event_triggered_last_turn=True),
        current_turn=5,
    )
    assert fire
    assert reason == "event_triggered"


def test_phase_advanced_last_turn_fires():
    fire, reason = should_run_director(
        _stream(4),
        _session(is_framework_mode=True, phase_advanced_last_turn=True),
        current_turn=5,
    )
    assert fire
    assert reason == "phase_advanced"


def test_faction_tension_breach_fires():
    fire, reason = should_run_director(
        _stream(4),
        _session(is_framework_mode=True, faction_tension_breached=True),
        current_turn=5,
    )
    assert fire
    assert reason == "faction_tension"


def test_proactive_npc_pending_fires():
    """NPC with sufficient favor and elapsed cooldown triggers the Director."""
    fire, reason = should_run_director(
        _stream(4),
        _session(is_framework_mode=True, proactive_npc_pending=True),
        current_turn=5,
    )
    assert fire
    assert reason == "proactive_npc"


def test_proactive_npc_cooldown_not_passed_does_not_fire():
    """NPC cooldown not yet elapsed — no trigger, no false positive."""
    fire, reason = should_run_director(
        _stream(4),
        _session(
            is_framework_mode=True,
            proactive_npc_pending=False,  # cooldown not met
        ),
        current_turn=5,
    )
    assert not fire
    assert reason == "skip"


# ──────────────────────────────────────────────────────────────
# Priority: event_completed fires before phase_advanced
# ──────────────────────────────────────────────────────────────

def test_event_completed_takes_priority_over_phase_advanced():
    """event_completed is checked first; reason should be event_completed."""
    fire, reason = should_run_director(
        _stream(4),
        _session(
            is_framework_mode=True,
            event_completed_last_turn=True,
            phase_advanced_last_turn=True,
        ),
        current_turn=5,
    )
    assert fire
    assert reason == "event_completed"


# ──────────────────────────────────────────────────────────────
# Shorter interval in framework mode
# ──────────────────────────────────────────────────────────────

def test_framework_mode_uses_shorter_interval():
    """Framework mode fires at DIRECTOR_INTERVAL_TURNS_FRAMEWORK (3), not 5."""
    # At turn 4 with last_run=1, delta=3: should fire in framework mode
    fire, reason = should_run_director(
        _stream(1),
        _session(is_framework_mode=True),
        current_turn=1 + DIRECTOR_INTERVAL_TURNS_FRAMEWORK,
    )
    assert fire
    assert reason == "interval"


def test_framework_interval_shorter_than_default():
    """Sanity-check: the framework interval constant is less than the default."""
    assert DIRECTOR_INTERVAL_TURNS_FRAMEWORK < DIRECTOR_INTERVAL_TURNS


def test_screenplay_mode_still_uses_default_interval():
    """Screenplay session (is_framework_mode=False) keeps the 5-turn interval."""
    # At DIRECTOR_INTERVAL_TURNS_FRAMEWORK turns since last run — should NOT fire
    fire, _ = should_run_director(
        _stream(1),
        _session(is_framework_mode=False),
        current_turn=1 + DIRECTOR_INTERVAL_TURNS_FRAMEWORK,
    )
    assert not fire  # 3 < 5, so interval not reached for screenplay mode

    # At DIRECTOR_INTERVAL_TURNS turns — should fire
    fire, reason = should_run_director(
        _stream(1),
        _session(is_framework_mode=False),
        current_turn=1 + DIRECTOR_INTERVAL_TURNS,
    )
    assert fire
    assert reason == "interval"


# ──────────────────────────────────────────────────────────────
# Non-regression: screenplay session with all framework fields absent/False
# ──────────────────────────────────────────────────────────────

def test_non_framework_session_unaffected():
    """A session without framework fields set should not produce false positives."""
    # Simulates a legacy screenplay session object with no framework attrs at all
    screenplay_sess = SimpleNamespace(
        turn_count=5,
        doom_score=0,
        scene_turn_count=1,
        chapter_advanced_last_turn=False,
        major_plot_turn_last_turn=False,
        hp=20,
        sanity=20,
        hidden_event_due=False,
        # No framework fields — getattr with default=False should handle them
    )
    fire, reason = should_run_director(_stream(4), screenplay_sess, current_turn=5)
    assert not fire
    assert reason == "skip"


def test_non_framework_all_framework_flags_false():
    """All framework flags explicitly False — no trigger."""
    fire, reason = should_run_director(
        _stream(4),
        _session(
            is_framework_mode=True,
            event_triggered_last_turn=False,
            event_completed_last_turn=False,
            phase_advanced_last_turn=False,
            faction_tension_breached=False,
            proactive_npc_pending=False,
        ),
        current_turn=5,  # delta=1, below 3-turn framework interval
    )
    assert not fire
    assert reason == "skip"
