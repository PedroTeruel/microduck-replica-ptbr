import math

import pytest

from mjlab_microduck.balance_parameters import (
    aggregate_balance_trial,
    balance_command_contract,
    balance_cycle_seconds,
    validate_balance_parameters,
)


SKILL = {"support_side": "left", "lift_height_m": 0.01, "hold_seconds": 3.0}


@pytest.mark.parametrize("field,value", [
    ("support_side", "both"), ("lift_height_m", 0.0),
    ("lift_height_m", float("nan")), ("hold_seconds", float("inf")),
    ("hold_seconds", True), ("hold_seconds", 6),
])
def test_invalid_skill_is_rejected(field, value):
    with pytest.raises(ValueError):
        validate_balance_parameters({**SKILL, field: value})


def successful_samples(skill=SKILL):
    rows = []
    for step in range(1, round(balance_cycle_seconds(skill) / .02) + 2):
        t = step * .02
        hold = 2.0 <= t < 2.0 + skill["hold_seconds"]
        settle = t >= 3.0 + skill["hold_seconds"]
        phase = 0 if t < 1 else 1 if t < 2 else 2 if hold else 3
        rows.append(dict(elapsed_s=t, dt_s=.02, phase=phase,
                         swing_clearance_m=skill["lift_height_m"] if hold else 0,
                         support_clearance_m=0, support_contact=True,
                         swing_contact=not hold, support_force_n=7.,
                         tilt_rad=.1, root_speed_mps=.01, support_speed_mps=0,
                         com_margin_m=.01 if hold else -.01, finite=True))
    return rows


def test_full_hold_and_return_are_required_not_reward():
    rows = successful_samples()
    assert aggregate_balance_trial(rows, SKILL)["success"]
    assert not aggregate_balance_trial(rows[:250], SKILL)["success"]
    for row in rows:
        if row["phase"] == 2:
            row["swing_contact"] = True
    result = aggregate_balance_trial(rows, SKILL)
    assert not result["success"]
    assert "hold_incomplete" in result["failure_reasons"]


@pytest.mark.parametrize("change", [
    {"support_contact": False}, {"swing_clearance_m": .03},
    {"com_margin_m": -.01}, {"finite": False},
    {"tilt_rad": math.radians(45)}, {"terminated": True},
    {"nonfoot_contact": True},
])
def test_wrong_support_falling_and_nonfinite_never_count_as_success(change):
    rows = successful_samples()
    for row in rows:
        if row["phase"] == 2:
            row.update(change)
    assert not aggregate_balance_trial(rows, SKILL)["success"]


def test_missing_land_and_sample_gaps_are_failures():
    rows = successful_samples()
    for row in rows:
        if row["phase"] == 3:
            row["swing_contact"] = False
    assert "return_incomplete" in aggregate_balance_trial(rows, SKILL)["failure_reasons"]
    rows = successful_samples()
    rows = [row for row in rows if not 2.5 < row["elapsed_s"] < 3.0]
    assert not aggregate_balance_trial(rows, SKILL)["success"]


def test_contract_states_scheduler_requirement_and_full_cycle():
    params = validate_balance_parameters(SKILL)
    assert balance_cycle_seconds(params) == 6.5
    contract = balance_command_contract(params)
    assert contract["control_hz"] == 50
    assert contract["actor_observation_size"] == 61
    assert contract["action_size"] == 14
    assert contract["runtime_adapter_required"] is True
    assert contract["skill"] == SKILL
