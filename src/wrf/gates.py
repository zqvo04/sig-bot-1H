"""Canonical live/offline execution-probability and gate evaluation.

A candidate's probability adjustment, floor, EV/RR guard and quarantine must be
calculated once.  The engine and research/audit replays consume the same pure
functions; consumers may not independently approximate BO geometry handling.
"""
from __future__ import annotations

from typing import Any

try:
    import config
except ImportError:  # pragma: no cover
    from src import config  # type: ignore


def execution_probability(candidate: dict, levels: dict, probability: dict) -> dict:
    """Apply deterministic execution geometry to prior/calibrated probabilities.

    The returned adjustment is persisted on each candidate so historical replay
    does not need detector-only box fields to reproduce the production gate.
    """
    p_prior = float(probability["p_prior"])
    p_cal = float(probability["p_cal"])
    adjustment = 0.0
    if (candidate.get("setup") == "BO" and getattr(config, "WRF_BO_SL_NEAR", False)
            and candidate.get("box_hi") is not None and candidate.get("box_lo") is not None):
        box_h = abs(float(candidate["box_hi"]) - float(candidate["box_lo"]))
        if box_h > 0:
            tight = float(levels["r_dist"]) / box_h
            ref = getattr(config, "WRF_BO_SL_TIGHT_REF", 0.60)
            adjustment = getattr(config, "WRF_BO_SL_TIGHT_PEN", 0.15) * max(0.0, ref - tight)
            p_prior = max(0.0, p_prior - adjustment)
            p_cal = max(0.0, p_cal - adjustment)
    source = probability["source"]
    return {
        "p_execution": p_cal if source == "calibrated" else p_prior,
        "p_execution_prior": p_prior,
        "p_execution_cal": p_cal,
        "p_execution_adjustment": adjustment,
    }


def gate_decision(candidate: dict, levels: dict, probability: dict,
                  p_execution: float, vetoes: list[str] | None = None) -> dict:
    """Return the canonical threshold, EV/RR, quarantine and fire decision."""
    vetoes = list(vetoes or [])
    quarantine: list[str] = []
    if candidate.get("setup") in getattr(config, "WRF_SHADOW_SETUPS", set()):
        quarantine.append("SHADOW_SETUP")
    if (getattr(config, "WRF_FIRE_RIGHTS_ENABLED", True)
            and probability.get("fire_rights") == "shadow"):
        quarantine.append("FIRE_RIGHTS")

    rr = float(levels["rr"])
    if getattr(config, "WRF_EV_GATE", True):
        ev = p_execution * rr - (1.0 - p_execution)
        rr_ok = (ev >= getattr(config, "WRF_EV_MIN", 0.15)
                 and rr >= getattr(config, "WRF_EV_RR_FLOOR", 1.0))
    else:
        ev = p_execution * rr - (1.0 - p_execution)
        rr_ok = rr >= getattr(config, "WRF_MIN_RR", 1.5)

    if getattr(config, "WRF_FLOOR_MODE", "winrate") == "ev" and rr > -1.0:
        floor = (1.0 + getattr(config, "WRF_EV_MIN", 0.15)) / (1.0 + rr)
    else:
        floor = float(probability["floor"])
    fire = bool(p_execution >= floor and not vetoes and rr_ok and not quarantine)
    band_w = getattr(config, "WRF_SHADOW_BAND_WIDTH", 0.03)
    shadow_band = bool(
        getattr(config, "WRF_SHADOW_BAND", True)
        and not fire and not vetoes and rr_ok
        and (floor - band_w) <= p_execution < floor
    )
    return {
        "p_execution": p_execution,
        "win_floor": floor,
        "ev": ev,
        "rr_ok": rr_ok,
        "quarantine": quarantine,
        "veto": vetoes,
        "fire": fire,
        "shadow_band": shadow_band,
    }


def replay_gate(candidate: dict, probability: dict, vetoes: list[str] | None = None) -> dict:
    """Replay persisted candidate fields without recalculating detector geometry.

    v5 rows persist ``p_execution_adjustment``.  Legacy rows explicitly fall
    back to zero adjustment and must remain labelled legacy by reporting code.
    """
    adjustment = float(candidate.get("p_execution_adjustment") or 0.0)
    p_prior = max(0.0, float(probability["p_prior"]) - adjustment)
    p_cal = max(0.0, float(probability["p_cal"]) - adjustment)
    source = probability["source"]
    p_exec = p_cal if source == "calibrated" else p_prior
    levels = {"rr": float(candidate["rr"])}
    decision = gate_decision(candidate, levels, probability, p_exec, vetoes=vetoes)
    decision.update({
        "p_execution_prior": p_prior,
        "p_execution_cal": p_cal,
        "p_execution_adjustment": adjustment,
    })
    return decision
