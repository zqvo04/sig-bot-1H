"""Canonical execution-plan contract for WRF paper trades.

One approved trade is represented by one immutable absolute-price plan.  The
Notion paper ledger and offline research labels must evaluate this same plan;
no consumer is allowed to rebase TP/SL to a later candle open.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from typing import Any

import pandas as pd

try:
    import config
except ImportError:  # pragma: no cover
    from src import config  # type: ignore

PLAN_SCHEMA_VERSION = 1
SAME_BAR_POLICY = "SL_FIRST"
TRAILING_BAR_POLICY = "PRIOR_STOP_ONLY"


def _jsonable(value: Any) -> Any:
    """Canonical, non-secret config representation used in an audit hash."""
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in sorted(value) if not callable(v)]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in sorted(value.items())}
    return str(value)


def config_hash() -> str:
    """Hash only execution-relevant public config, never credentials."""
    prefixes = ("WRF_", "TPSL_", "ATR_", "BOLLINGER_")
    payload = {
        k: _jsonable(v)
        for k, v in vars(config).items()
        if k.startswith(prefixes) and not callable(v)
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def code_sha() -> str:
    """Workflow-provided code identity; local runs deliberately remain explicit."""
    return os.getenv("GITHUB_SHA") or os.getenv("WRF_CODE_SHA") or "LOCAL_UNVERSIONED"


def _round_price(value: Any) -> float:
    return round(float(value), 8)


def make_decision_id(symbol: str, ts: str, candidate: dict, cfg_hash: str, sha: str) -> str:
    """Stable ID for a single approved plan, independent of downstream storage."""
    key = {
        "symbol": symbol,
        "ts": ts,
        "setup": candidate.get("setup"),
        "dir": candidate.get("dir"),
        "entry": _round_price(candidate["entry"]),
        "tp": _round_price(candidate["tp"]),
        "sl": _round_price(candidate["sl"]),
        "t_max": int(candidate["t_max"]),
        "cfg": cfg_hash,
        "sha": sha,
    }
    raw = json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_plan(symbol: str, ts: str, candidate: dict) -> dict:
    """Freeze a candidate into the one execution definition consumed everywhere."""
    cfg_hash = config_hash()
    sha = code_sha()
    plan = {
        "plan_schema_version": PLAN_SCHEMA_VERSION,
        "decision_ts": ts,
        "symbol": symbol,
        "setup": candidate["setup"],
        "dir": candidate["dir"],
        # The bot currently records a paper entry at its decision price.  It is
        # intentionally not rewritten to a future candle open by labels.py.
        "price_basis": "decision_price",
        "entry": _round_price(candidate["entry"]),
        "tp": _round_price(candidate["tp"]),
        "sl": _round_price(candidate["sl"]),
        "r_dist": _round_price(candidate["r_dist"]),
        "rr": round(float(candidate["rr"]), 8),
        "t_max": int(candidate["t_max"]),
        "trail_dist": (_round_price(candidate["trail_dist"])
                       if candidate.get("trail_dist") is not None else None),
        "same_bar_policy": SAME_BAR_POLICY,
        "trailing_bar_policy": TRAILING_BAR_POLICY,
        "config_hash": cfg_hash,
        "code_sha": sha,
    }
    plan["decision_id"] = make_decision_id(symbol, ts, candidate, cfg_hash, sha)
    return plan


def plan_from_candidate(candidate: dict, symbol: str | None = None, ts: str | None = None) -> dict | None:
    """Read a canonical plan, with a legacy fallback only for historical rows."""
    plan = candidate.get("execution_plan")
    if isinstance(plan, dict) and all(k in plan for k in ("entry", "tp", "sl", "t_max", "dir")):
        return plan
    if not symbol or not ts or not all(candidate.get(k) is not None for k in ("entry", "tp", "sl", "r_dist", "rr", "t_max")):
        return None
    return build_plan(symbol, ts, candidate)


def path_to_absolute_ohlc(path: dict, p0: float) -> pd.DataFrame | None:
    """Restore future absolute OHLC without changing the plan's absolute levels."""
    if not path or not p0 or float(p0) <= 0:
        return None
    closes = path.get("c") or []
    if not closes:
        return None
    opens = path.get("o") or closes
    highs = path.get("h") or closes
    lows = path.get("l") or closes
    n = min(len(closes), len(opens), len(highs), len(lows))
    if n <= 0:
        return None
    base = float(p0)
    return pd.DataFrame({
        "open": [base * (1.0 + float(v)) for v in opens[:n]],
        "high": [base * (1.0 + float(v)) for v in highs[:n]],
        "low": [base * (1.0 + float(v)) for v in lows[:n]],
        "close": [base * (1.0 + float(v)) for v in closes[:n]],
    })


def _timeout(plan: dict, candles: pd.DataFrame, mfe: float, mae: float) -> dict:
    long = plan["dir"].lower() == "long"
    entry, r_dist = float(plan["entry"]), float(plan["r_dist"])
    px = float(candles.iloc[int(plan["t_max"]) - 1]["close"])
    realized = (px - entry) if long else (entry - px)
    return {
        "status": "SCRATCH", "outcome": "TIMEOUT",
        "reason": "EXPIRED_WIN" if realized >= 0 else "EXPIRED_LOSS",
        "mfe": mfe, "mae": mae, "bars": int(plan["t_max"]),
        "exit_price": round(px, 8), "r_multiple": round(realized / r_dist, 8),
    }


def evaluate_plan(plan: dict, candles: pd.DataFrame) -> dict | None:
    """Evaluate one immutable plan against future absolute OHLC.

    Fixed TP/SL uses SL-first when both barriers occur in an OHLC bar.  A
    trailing stop uses the *previous* bar's stop for a bar; it is updated only
    after the current bar, avoiding an unknowable same-bar high/low ordering.
    """
    if candles is None or candles.empty:
        return None
    try:
        entry, tp, sl = float(plan["entry"]), float(plan["tp"]), float(plan["sl"])
        r_dist, t_max = float(plan["r_dist"]), int(plan["t_max"])
    except (KeyError, TypeError, ValueError):
        return None
    if entry <= 0 or r_dist <= 0 or t_max <= 0:
        return None
    if len(candles) < t_max:
        # A barrier touch can still resolve a short partial path; otherwise it
        # remains PENDING rather than being labelled as a timeout.
        horizon = len(candles)
    else:
        horizon = t_max
    long = str(plan.get("dir", "")).lower() == "long"
    trail_dist = plan.get("trail_dist")
    trailing = trail_dist is not None and float(trail_dist) > 0
    stop = sl
    hwm = entry
    mfe = 0.0
    mae = 0.0

    for i in range(horizon):
        row = candles.iloc[i]
        hi, lo = float(row["high"]), float(row["low"])
        fav = (hi - entry) if long else (entry - lo)
        adv = (entry - lo) if long else (hi - entry)
        mfe = max(mfe, fav / r_dist)
        mae = max(mae, adv / r_dist)

        if trailing:
            # PRIOR_STOP_ONLY is deliberately conservative under OHLC ambiguity.
            stop_hit = (lo <= stop) if long else (hi >= stop)
            if stop_hit:
                r = ((stop - entry) if long else (entry - stop)) / r_dist
                return {
                    "status": "WIN" if r > 0 else "LOSS",
                    "outcome": "WIN" if r > 0 else "LOSS",
                    "reason": "TRAIL_STOP" if r > 0 else "SL_HIT",
                    "mfe": mfe, "mae": mae, "bars": i + 1,
                    "exit_price": round(stop, 8), "r_multiple": round(r, 8),
                }
            if long:
                hwm = max(hwm, hi)
                stop = max(stop, hwm - float(trail_dist))
            else:
                hwm = min(hwm, lo)
                stop = min(stop, hwm + float(trail_dist))
            continue

        sl_hit = (lo <= sl) if long else (hi >= sl)
        tp_hit = (hi >= tp) if long else (lo <= tp)
        # Same-bar sequencing is explicitly SL_FIRST and stored in the plan.
        if sl_hit:
            return {"status": "LOSS", "outcome": "LOSS", "reason": "SL_HIT",
                    "mfe": mfe, "mae": mae, "bars": i + 1,
                    "exit_price": round(sl, 8), "r_multiple": -1.0}
        if tp_hit:
            r = abs(tp - entry) / r_dist
            return {"status": "WIN", "outcome": "WIN", "reason": "TP_HIT",
                    "mfe": mfe, "mae": mae, "bars": i + 1,
                    "exit_price": round(tp, 8), "r_multiple": round(r, 8)}

    if len(candles) < t_max:
        return None
    return _timeout(plan, candles, mfe, mae)


def evaluate_plan_path(plan: dict, path: dict, p0: float) -> dict | None:
    """Offline replay wrapper: restore absolute path, then use the live evaluator."""
    candles = path_to_absolute_ohlc(path, p0)
    return evaluate_plan(plan, candles) if candles is not None else None
