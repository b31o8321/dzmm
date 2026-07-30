"""Tests for engine/dice.py — roll(), skill_check(), get_modifier()."""

import random
import statistics

import pytest

from dzmm.engine.dice import (
    get_modifier,
    roll,
    skill_check,
)


# ── get_modifier ──────────────────────────────────────────────────────────────

def test_modifier_low():
    assert get_modifier(3) == -4    # (3-10)//2 = -7//2 = -4 (floor div)


def test_modifier_ten():
    assert get_modifier(10) == 0


def test_modifier_eleven():
    assert get_modifier(11) == 0


def test_modifier_eighteen():
    assert get_modifier(18) == 4


def test_modifier_thirty():
    assert get_modifier(30) == 10


# ── roll: basic shapes ────────────────────────────────────────────────────────

def test_roll_d20_range():
    rng = random.Random(42)
    for _ in range(200):
        r = roll("d20", rng=rng)
        assert 1 <= r.total <= 20


def test_roll_d20_distribution():
    rng = random.Random(0)
    results = [roll("d20", rng=rng).total for _ in range(1000)]
    seen = set(results)
    # All values 1-20 should appear
    assert seen == set(range(1, 21))
    # Mean should be close to 10.5
    assert abs(statistics.mean(results) - 10.5) < 0.5


def test_roll_2d6_plus3_range():
    rng = random.Random(7)
    for _ in range(200):
        r = roll("2d6+3", rng=rng)
        assert 5 <= r.total <= 15  # min: 1+1+3=5, max: 6+6+3=15


def test_roll_d100_range():
    rng = random.Random(1)
    for _ in range(100):
        r = roll("d100", rng=rng)
        assert 1 <= r.total <= 100


def test_roll_3d8_minus1():
    rng = random.Random(99)
    for _ in range(100):
        r = roll("3d8-1", rng=rng)
        assert 2 <= r.total <= 23  # min: 1+1+1-1=2, max: 8+8+8-1=23
        assert len(r.rolls) == 3
        assert r.modifier == -1


def test_roll_formula_stored():
    r = roll("d20")
    assert r.formula == "d20"


def test_roll_malformed_formula_raises():
    with pytest.raises(ValueError):
        roll("20d")

    with pytest.raises(ValueError):
        roll("abc")

    with pytest.raises(ValueError):
        roll("d")


# ── roll: critical flags ──────────────────────────────────────────────────────

def test_crit_success_on_natural_20():
    # Force a d20 roll of 20 using seeded rng
    rng = random.Random()
    # Patch randint to always return 20
    rng.randint = lambda a, b: 20
    r = roll("d20", rng=rng)
    assert r.critical_success is True
    assert r.critical_failure is False


def test_crit_failure_on_natural_1():
    rng = random.Random()
    rng.randint = lambda a, b: 1
    r = roll("d20", rng=rng)
    assert r.critical_failure is True
    assert r.critical_success is False


def test_no_crit_on_d6():
    rng = random.Random()
    rng.randint = lambda a, b: 20  # would be crit if d20
    r = roll("d6", rng=rng)
    assert r.critical_success is False
    assert r.critical_failure is False


# ── rng seeding produces deterministic results ────────────────────────────────

def test_deterministic_with_seed():
    rng1 = random.Random(12345)
    rng2 = random.Random(12345)
    results1 = [roll("d20", rng=rng1).total for _ in range(10)]
    results2 = [roll("d20", rng=rng2).total for _ in range(10)]
    assert results1 == results2


# ── skill_check ───────────────────────────────────────────────────────────────

def test_skill_check_success_when_total_gte_dc():
    rng = random.Random()
    rng.randint = lambda a, b: 10  # natural 10, attr_mod=0, skill_bonus=0 → total 10
    result = skill_check(attribute_value=10, skill_level=0, dc=10, rng=rng)
    assert result.succeeded is True
    assert result.margin == 0


def test_skill_check_failure_when_total_lt_dc():
    rng = random.Random()
    rng.randint = lambda a, b: 5   # total 5, dc=10 → fail
    result = skill_check(attribute_value=10, skill_level=0, dc=10, rng=rng)
    assert result.succeeded is False
    assert result.margin == -5


def test_skill_check_natural_1_is_crit_fail_regardless_of_modifier():
    """Natural 1 always fails, even with a huge modifier."""
    rng = random.Random()
    rng.randint = lambda a, b: 1
    # attr 30 → mod +10; skill 100 → bonus +10; total = 1+10+10=21 vs dc=1
    result = skill_check(attribute_value=30, skill_level=100, dc=1, rng=rng)
    assert result.succeeded is False
    assert result.roll.critical_failure is True
    assert result.crit is True


def test_skill_check_natural_20_is_crit_success_regardless_of_dc():
    """Natural 20 always succeeds, even with impossible DC."""
    rng = random.Random()
    rng.randint = lambda a, b: 20
    result = skill_check(attribute_value=3, skill_level=0, dc=9999, rng=rng)
    assert result.succeeded is True
    assert result.roll.critical_success is True
    assert result.crit is True


def test_skill_check_skill_bonus_contributes():
    rng = random.Random()
    rng.randint = lambda a, b: 8  # natural 8
    # attr=10 mod=0, skill=50 → bonus=5, total=13, dc=13
    result = skill_check(attribute_value=10, skill_level=50, dc=13, rng=rng)
    assert result.succeeded is True


def test_skill_check_result_has_correct_dc():
    rng = random.Random()
    rng.randint = lambda a, b: 10
    result = skill_check(attribute_value=10, skill_level=0, dc=15, rng=rng)
    assert result.dc == 15
