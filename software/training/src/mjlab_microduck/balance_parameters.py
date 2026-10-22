"""Portable single-leg skill contract and evaluation, without simulation imports."""

import math
from collections.abc import Mapping, Sequence


BALANCE_TASK_ID = "Mjlab-Balance-Flat-MicroDuck-HD1910"
BALANCE_EXPERIMENT = "microduck_hd1910_balance"
BALANCE_DEFAULTS = {"support_side": "left", "lift_height_m": 0.01, "hold_seconds": 3.0}
INIT_SECONDS = 1.0
LIFT_SECONDS = 1.0
RETURN_SECONDS = 1.0
SETTLE_SECONDS = 0.5
MAX_TILT_RAD = math.radians(25.0)
MIN_SUPPORT_FORCE_N = 0.5
MAX_ROOT_SPEED_MPS = 0.08
MAX_SUPPORT_SPEED_MPS = 0.04
MIN_COM_MARGIN_M = -0.002
LAND_CLEARANCE_M = 0.003


def validate_balance_parameters(parameters: Mapping) -> dict:
    if not isinstance(parameters, Mapping) or set(parameters) != set(BALANCE_DEFAULTS):
        raise ValueError("Balance requires exactly support_side, lift_height_m, hold_seconds")
    if parameters["support_side"] not in ("left", "right"):
        raise ValueError("support_side must be left or right")
    result = {"support_side": parameters["support_side"]}
    for key, lower, upper in (("lift_height_m", .005, .02), ("hold_seconds", 1., 5.)):
        value = parameters[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a finite number")
        if not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f"{key} must be between {lower} and {upper}")
        result[key] = float(value)
    return result


def balance_cycle_seconds(parameters: Mapping) -> float:
    return validate_balance_parameters(parameters)["hold_seconds"] + 3.5


def apply_balance_parameters(cfg, parameters: Mapping) -> dict:
    """Apply a saved skill before constructing train/play/export environments."""
    result = validate_balance_parameters(parameters)
    command = cfg.commands.get("twist")
    if getattr(command, "contract_version", None) != "microduck.single_leg_balance.v1":
        raise ValueError("Balance parameters require the registered balance task")
    for name, value in result.items():
        setattr(command, name, value)
    # The command's cycle-complete timeout ends each episode at its own duration.
    # The fixed ceiling also accommodates direct typed CLI overrides to 5 s hold.
    cfg.episode_length_s = 9.0
    return result


def balance_command_contract(parameters: Mapping) -> dict:
    skill = validate_balance_parameters(parameters)
    return {
        "version": "microduck.single_leg_balance.v1",
        "actor_observation_size": 61, "action_size": 14, "control_hz": 50,
        "twist_slots": ["support_sign (+1 left, -1 right)",
                        "scheduled swing sole clearance (metres)",
                        "phase / 3 (0 init, 1 lift, 2 hold, 3 return)"],
        "phase_seconds": {"init": 1.0, "lift": 1.0,
                          "hold": skill["hold_seconds"], "return": 1.5},
        "return_includes_settle_seconds": .5,
        "cycle_seconds": balance_cycle_seconds(skill),
        "head_body_commands": "Near-zero pose command padding; deployment uses zeros.",
        "runtime_adapter_required": True,
        "runtime_note": "A matching phase scheduler is required; this is not a velocity policy.",
        "hardware_validated": False, "skill": skill,
    }


def aggregate_balance_trial(samples: Sequence[Mapping], parameters: Mapping) -> dict:
    """Score measured 50 Hz samples from one reset through hold AND return.

    Each sample is taken after a simulation step, contains elapsed_s and dt_s,
    and uses the scalar fields from tasks.mdp.balance_measurements. Missing,
    non-finite, reversed or gapped samples cannot silently count as held time.
    CoM margin is to the projected sole outline, a diagnostic approximation;
    sustained loaded contact and low measured velocities are also mandatory.
    """
    skill = validate_balance_parameters(parameters)
    hold_start, hold_end = 2.0, 2.0 + skill["hold_seconds"]
    settle_start, cycle_end = hold_end + 1.0, hold_end + 1.5
    hold_run = best_hold = return_run = best_return = 0.0
    previous = 0.0
    finite_all, terminated, chronological = True, False, True
    max_tilt, hold_heights, contact_steps = 0.0, [], 0
    numeric = ("elapsed_s", "dt_s", "swing_clearance_m", "support_clearance_m",
               "support_force_n", "tilt_rad", "root_speed_mps", "support_speed_mps", "com_margin_m")
    last_t = 0.0
    for sample in samples:
        numbers_ok = all(isinstance(sample.get(key), (int, float))
                         and not isinstance(sample.get(key), bool)
                         and math.isfinite(sample[key]) for key in numeric)
        if not numbers_ok:
            finite_all = False
            hold_run = return_run = 0.0
            continue
        t, dt = float(sample["elapsed_s"]), float(sample["dt_s"])
        consecutive = 0 < dt <= .021 and t > previous and abs(t - previous - dt) <= .002
        chronological &= consecutive
        previous, last_t = t, t
        finite = bool(sample.get("finite", False))
        finite_all &= finite
        terminated |= bool(sample.get("terminated", False) or sample.get("nonfoot_contact", False))
        contact = bool(sample.get("support_contact", False))
        contact_steps += int(contact)
        max_tilt = max(max_tilt, sample["tilt_rad"])
        stable = (finite and contact and not sample.get("nonfoot_contact", False)
                  and sample["support_force_n"] >= MIN_SUPPORT_FORCE_N
                  and sample["tilt_rad"] <= MAX_TILT_RAD
                  and sample["root_speed_mps"] <= MAX_ROOT_SPEED_MPS
                  and sample["support_speed_mps"] <= MAX_SUPPORT_SPEED_MPS)
        # Account only for the part of this sample interval inside each window.
        hold_dt = max(0., min(t, hold_end) - max(t - dt, hold_start))
        hold_valid = (stable and not sample.get("swing_contact", True)
                      and sample["com_margin_m"] >= MIN_COM_MARGIN_M
                      and abs(sample["swing_clearance_m"] - skill["lift_height_m"])
                      <= max(.002, skill["lift_height_m"] * .2))
        if hold_dt > 1e-8:
            hold_heights.append(sample["swing_clearance_m"])
            hold_run = (hold_run + hold_dt) if consecutive and hold_valid else 0.
            best_hold = max(best_hold, hold_run)
        settle_dt = max(0., min(t, cycle_end) - max(t - dt, settle_start))
        landed = (stable and bool(sample.get("swing_contact", False))
                  and abs(sample["swing_clearance_m"]) <= LAND_CLEARANCE_M
                  and abs(sample["support_clearance_m"]) <= LAND_CLEARANCE_M)
        if settle_dt > 1e-8:
            return_run = (return_run + settle_dt) if consecutive and landed else 0.
            best_return = max(best_return, return_run)
    # Two control frames cover phase-boundary sampling, never a missing segment.
    reasons = []
    complete = bool(samples) and last_t >= cycle_end - .021
    if not complete:
        reasons.append("cycle_incomplete")
    if not finite_all:
        reasons.append("non_finite_state")
    if terminated:
        reasons.append("physics_termination")
    if not chronological:
        reasons.append("sample_gap")
    if best_hold < skill["hold_seconds"] - .041:
        reasons.append("hold_incomplete")
    if best_return < SETTLE_SECONDS - .041:
        reasons.append("return_incomplete")
    return {"success": not reasons, "hold_achieved_s": round(best_hold, 6),
            "return_achieved_s": round(best_return, 6), "cycle_complete": complete,
            "max_tilt_deg": math.degrees(max_tilt),
            "mean_hold_clearance_m": sum(hold_heights) / len(hold_heights) if hold_heights else None,
            "support_contact_fraction": contact_steps / len(samples) if samples else 0.,
            "failure_reasons": reasons}
