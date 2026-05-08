from types import SimpleNamespace

from dzmm.service.agents.triggers import should_run_director


def _stream(last_run_turn: int):
    return SimpleNamespace(last_run_turn=last_run_turn)


def _session(**kwargs):
    base = dict(
        turn_count=0, doom_score=0, scene_turn_count=1,
        chapter_advanced_last_turn=False,
        major_plot_turn_last_turn=False,
        hp=20, sanity=20,
        hidden_event_due=False,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_first_run_bootstraps():
    fire, reason = should_run_director(_stream(0), _session(), current_turn=1)
    assert fire
    assert reason == "bootstrap"


def test_interval_5_turns():
    fire, _ = should_run_director(_stream(1), _session(), current_turn=5)
    assert fire is False
    fire, reason = should_run_director(_stream(1), _session(), current_turn=6)
    assert fire and reason == "interval"


def test_chapter_advance_forces():
    fire, reason = should_run_director(
        _stream(4), _session(chapter_advanced_last_turn=True), current_turn=5,
    )
    assert fire and reason == "chapter_advance"


def test_major_plot_turn_forces():
    fire, reason = should_run_director(
        _stream(4), _session(major_plot_turn_last_turn=True), current_turn=5,
    )
    assert fire and reason == "plot_turn_major"


def test_hp_critical_forces():
    fire, reason = should_run_director(
        _stream(4), _session(hp=3), current_turn=5,
    )
    assert fire and reason == "hp_critical"


def test_sanity_critical_forces():
    fire, reason = should_run_director(
        _stream(4), _session(sanity=4), current_turn=5,
    )
    assert fire and reason == "sanity_critical"


def test_hidden_event_due_forces():
    fire, reason = should_run_director(
        _stream(4), _session(hidden_event_due=True), current_turn=5,
    )
    assert fire and reason == "hidden_event_due"
