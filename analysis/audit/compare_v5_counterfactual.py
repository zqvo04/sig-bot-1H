"""Counterfactual v5-vs-legacy execution comparison on stored legacy candidates.

Legacy rows do not contain decision_ts or candidate-level 5m paths.  This tool
therefore uses the documented scheduler proxy ``entry_ts = feature row ts +
5 minutes`` and public OKX 5m OHLC as the only counterfactual timestamp basis.
It compares the legacy labels' rebased triple-barrier result with v5's immutable
absolute barrier evaluator.  It does not claim to be an observed v5 cohort.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

import ccxt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "analysis"))

from wrf import execution  # noqa: E402
import labels  # noqa: E402


BAR_MS = 5 * 60 * 1000


def _rows(data_dir: Path) -> list[dict]:
    out = []
    for name in glob.glob(str(data_dir / "*" / "*.jsonl")):
        with open(name, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return out


def _legacy_result(row: dict, candidate: dict) -> dict | None:
    path = row.get("path") or {}
    entry, tp, sl = candidate.get("entry"), candidate.get("tp"), candidate.get("sl")
    if not path.get("c") or not all(x is not None for x in (entry, tp, sl)):
        return None
    entry, tp, sl = float(entry), float(tp), float(sl)
    if entry <= 0 or abs(entry - sl) <= 0:
        return None
    trail = candidate.get("trail_dist")
    return labels.triple_barrier(
        path, str(candidate.get("dir", "")), abs(entry - sl) / entry,
        abs(tp - entry) / entry, int(candidate.get("t_max") or 0),
        sl_priority=True, trail_frac=(abs(float(trail)) / entry if trail else None),
    )


def _market(symbol: str) -> str:
    return f"{symbol.split('/')[0]}/USDT:USDT"


def _fetch_range(exchange, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    cursor = int(start.value // 1_000_000)
    stop = int(end.value // 1_000_000)
    records = []
    while cursor < stop:
        batch = exchange.fetch_ohlcv(_market(symbol), timeframe="5m", since=cursor, limit=300)
        if not batch:
            break
        records.extend(batch)
        nxt = int(batch[-1][0]) + BAR_MS
        if nxt <= cursor:
            break
        cursor = nxt
        time.sleep(max(0.0, exchange.rateLimit / 1000.0))
    if not records:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    df = pd.DataFrame(records, columns=["ms", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ms").sort_values("ms")
    df.index = pd.to_datetime(df.pop("ms"), unit="ms", utc=True)
    return df.loc[(df.index >= start) & (df.index <= end), ["open", "high", "low", "close"]]


def _plan(c: dict, entry_ts: pd.Timestamp) -> dict:
    entry, tp, sl = float(c["entry"]), float(c["tp"]), float(c["sl"])
    return {
        "decision_ts": entry_ts.isoformat(), "entry_ts": entry_ts.isoformat(),
        "dir": str(c["dir"]).lower(), "entry": entry, "tp": tp, "sl": sl,
        "r_dist": abs(entry - sl), "rr": abs(tp - entry) / abs(entry - sl),
        "t_max": int(c["t_max"]), "trail_dist": c.get("trail_dist"),
        "path_timeframe": "5m", "path_bar_minutes": 5,
        "same_bar_policy": "SL_FIRST", "trailing_bar_policy": "PRIOR_STOP_ONLY",
    }


def _metrics(frame: pd.DataFrame, r_col: str, cost_bps: float) -> dict:
    if frame.empty:
        return {"n": 0}
    r = pd.to_numeric(frame[r_col], errors="coerce").dropna()
    gross_win = r[r > 0].sum()
    gross_loss = -r[r < 0].sum()
    cost_r = pd.to_numeric(frame.loc[r.index, "cost_r"], errors="coerce").fillna(0.0)
    net = r - cost_r
    return {
        "n": int(len(r)),
        "win_rate": float((r > 0).mean()),
        "mean_r": float(r.mean()),
        "sum_r": float(r.sum()),
        "profit_factor": (float(gross_win / gross_loss) if gross_loss > 0 else None),
        "mean_net_r_at_cost_bps": float(net.mean()),
        "sum_net_r_at_cost_bps": float(net.sum()),
        "cost_bps": cost_bps,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "research"))
    ap.add_argument("--out-dir", default=str(ROOT / "results"))
    ap.add_argument("--cost-bps", type=float, default=16.0)
    ap.add_argument("--fired-only", action="store_true")
    args = ap.parse_args()

    rows = [r for r in _rows(Path(args.data_dir)) if int(r.get("schema_version", 0)) <= 4]
    candidates = []
    for row in rows:
        ts = pd.to_datetime(row.get("ts"), utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        for ordinal, candidate in enumerate(row.get("candidates") or []):
            if args.fired_only and not candidate.get("fire"):
                continue
            legacy = _legacy_result(row, candidate)
            if legacy is None:
                continue
            entry_ts = ts + pd.Timedelta(minutes=5)
            candidates.append({
                "snapshot_id": row.get("snapshot_id"), "symbol": row.get("symbol"),
                "ts": ts.isoformat(), "entry_ts_proxy": entry_ts.isoformat(), "ordinal": ordinal,
                "setup": candidate.get("setup"), "dir": candidate.get("dir"), "fire": bool(candidate.get("fire")),
                "entry": candidate.get("entry"), "tp": candidate.get("tp"), "sl": candidate.get("sl"),
                "r_dist": candidate.get("r_dist"), "t_max": candidate.get("t_max"),
                "legacy_outcome": legacy.get("outcome"), "legacy_r": legacy.get("r_multiple"),
                "plan": _plan(candidate, entry_ts),
            })
    if not candidates:
        raise RuntimeError("No mature legacy candidates found")

    exchange = ccxt.okx({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    by_symbol = {}
    for symbol in sorted({x["symbol"] for x in candidates}):
        subset = [x for x in candidates if x["symbol"] == symbol]
        start = min(pd.Timestamp(x["entry_ts_proxy"]) for x in subset).floor("5min")
        end = max(pd.Timestamp(x["entry_ts_proxy"]) + pd.Timedelta(hours=int(x["t_max"])) for x in subset)
        by_symbol[symbol] = _fetch_range(exchange, symbol, start, end)

    records = []
    for x in candidates:
        start = pd.Timestamp(x["entry_ts_proxy"]).floor("5min")
        n = int(x["plan"]["t_max"]) * 12
        candles = by_symbol[x["symbol"]]
        future = candles.loc[candles.index >= start].iloc[:n]
        out = execution.evaluate_plan(x["plan"], future)
        if out is None:
            continue
        cost_r = float(args.cost_bps) / 10000.0 * float(x["entry"]) / float(x["r_dist"])
        records.append({k: v for k, v in x.items() if k != "plan"} | {
            "v5_outcome": out["outcome"], "v5_r": out["r_multiple"],
            "v5_bars": out["bars"], "cost_r": cost_r,
            "outcome_changed": x["legacy_outcome"] != out["outcome"],
        })

    df = pd.DataFrame(records)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "fired" if args.fired_only else "all"
    csv_path = out_dir / f"v5_counterfactual_{suffix}.csv"
    json_path = out_dir / f"v5_counterfactual_{suffix}_summary.json"
    txt_path = out_dir / f"v5_counterfactual_{suffix}_summary.txt"
    df.to_csv(csv_path, index=False)

    summary = {
        "basis": {
            "legacy": "stored legacy triple-barrier label",
            "v5_counterfactual": "absolute barriers, entry_ts_proxy=row ts+5m, public OKX completed 5m OHLC",
            "cost_sensitivity": f"{args.cost_bps} bp round-trip as R deduction",
            "not_observed_v5_cohort": True,
        },
        "input_candidates": len(candidates),
        "replayed_candidates": int(len(df)),
        "legacy": _metrics(df, "legacy_r", args.cost_bps),
        "v5_counterfactual": _metrics(df, "v5_r", args.cost_bps),
        "outcome_transition": (pd.crosstab(df["legacy_outcome"], df["v5_outcome"]).to_dict() if not df.empty else {}),
        "changed_outcomes": int(df["outcome_changed"].sum()) if not df.empty else 0,
        "by_setup": {},
    }
    if not df.empty:
        for setup, group in df.groupby("setup"):
            summary["by_setup"][setup] = {
                "n": int(len(group)), "legacy": _metrics(group, "legacy_r", args.cost_bps),
                "v5_counterfactual": _metrics(group, "v5_r", args.cost_bps),
                "changed_outcomes": int(group["outcome_changed"].sum()),
            }
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"CSV={csv_path}")


if __name__ == "__main__":
    main()
