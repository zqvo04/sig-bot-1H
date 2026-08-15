"""Statistical analysis for legacy-vs-v5 counterfactual execution results."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def _sign_test_p(pos: int, neg: int) -> float | None:
    n = pos + neg
    if n == 0:
        return None
    k = min(pos, neg)
    lower = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2.0 * lower)


def _paired_metrics(group: pd.DataFrame, reps: int, rng: np.random.Generator) -> dict:
    delta = pd.to_numeric(group["v5_r"], errors="coerce") - pd.to_numeric(group["legacy_r"], errors="coerce")
    delta = delta.dropna().to_numpy(dtype=float)
    if not len(delta):
        return {"n": 0}
    idx = rng.integers(0, len(delta), size=(reps, len(delta)))
    boot = delta[idx].mean(axis=1)
    eps = 1e-12
    pos = int((delta > eps).sum())
    neg = int((delta < -eps).sum())
    legacy_outcome = group["legacy_outcome"]
    v5_outcome = group["v5_outcome"]
    legacy_decided = legacy_outcome.isin(["WIN", "LOSS"])
    v5_decided = v5_outcome.isin(["WIN", "LOSS"])
    legacy_win_all = (legacy_outcome == "WIN").mean()
    v5_win_all = (v5_outcome == "WIN").mean()
    legacy_win_decided = (legacy_outcome[legacy_decided] == "WIN").mean() if legacy_decided.any() else float("nan")
    v5_win_decided = (v5_outcome[v5_decided] == "WIN").mean() if v5_decided.any() else float("nan")
    return {
        "n": int(len(delta)),
        "mean_delta_r": float(delta.mean()),
        "median_delta_r": float(np.median(delta)),
        "bootstrap_ci95_mean_delta_r": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
        "positive_delta": pos,
        "negative_delta": neg,
        "tie_delta": int(len(delta) - pos - neg),
        "sign_test_two_sided_p": _sign_test_p(pos, neg),
        "legacy_decided_n": int(legacy_decided.sum()),
        "v5_decided_n": int(v5_decided.sum()),
        "legacy_win_rate_decided": float(legacy_win_decided),
        "v5_win_rate_decided": float(v5_win_decided),
        "decided_win_rate_delta_pp": float((v5_win_decided - legacy_win_decided) * 100.0),
        "legacy_win_rate_all_path": float(legacy_win_all),
        "v5_win_rate_all_path": float(v5_win_all),
        "outcome_changed": int((group["legacy_outcome"] != group["v5_outcome"]).sum()),
    }


def _embargo_subset(df: pd.DataFrame, hours: int = 72) -> pd.DataFrame:
    """Keep one candidate per symbol per non-overlapping holding horizon.

    This is a conservative effective-sample proxy, not an iid claim. It is
    reported separately because hourly candidates share most of their future
    path over a 72h time stop.
    """
    pieces = []
    for _, group in df.assign(_ts=pd.to_datetime(df["ts"], utc=True)).sort_values("_ts").groupby("symbol"):
        last = None
        keep = []
        for idx, row in group.iterrows():
            if last is None or row["_ts"] >= last + pd.Timedelta(hours=hours):
                keep.append(idx)
                last = row["_ts"]
        pieces.append(df.loc[keep])
    return pd.concat(pieces, axis=0).sort_values("ts") if pieces else df.iloc[0:0]


def _cost_sensitivity(group: pd.DataFrame) -> list[dict]:
    base_cost = pd.to_numeric(group["cost_r"], errors="coerce").fillna(0.0)
    legacy = pd.to_numeric(group["legacy_r"], errors="coerce")
    v5 = pd.to_numeric(group["v5_r"], errors="coerce")
    out = []
    for bps in (0, 8, 16, 24, 32):
        scale = bps / 16.0
        out.append({
            "round_trip_cost_bps": bps,
            "legacy_mean_net_r": float((legacy - base_cost * scale).mean()),
            "v5_mean_net_r": float((v5 - base_cost * scale).mean()),
            "v5_minus_legacy_mean_net_r": float((v5 - legacy).mean()),
        })
    return out


def _chart(group: pd.DataFrame, path: Path) -> None:
    rows = []
    for setup, g in group.groupby("setup"):
        rows.append((setup, (g["v5_r"] - g["legacy_r"]).mean(), len(g)))
    rows.sort()
    names, vals, ns = zip(*rows) if rows else ([], [], [])
    fig, ax = plt.subplots(figsize=(8.2, 4.8), dpi=160)
    colors = ["#0B6E4F" if x >= 0 else "#B42318" for x in vals]
    ax.bar(names, vals, color=colors)
    ax.axhline(0, color="#263238", linewidth=0.8)
    for i, (val, n) in enumerate(zip(vals, ns)):
        ax.text(i, val + (0.008 if val >= 0 else -0.015), f"n={n}\n{val:+.3f}R",
                ha="center", va="bottom" if val >= 0 else "top", fontsize=8)
    ax.set_title("Counterfactual v5 − Legacy: Mean R by Setup")
    ax.set_ylabel("Paired mean ΔR")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out-dir", default=str(ROOT / "results"))
    ap.add_argument("--bootstrap-reps", type=int, default=20000)
    args = ap.parse_args()
    df = pd.read_csv(args.input)
    rng = np.random.default_rng(20260816)
    result = {
        "basis": {
            "comparison": "paired stored legacy label vs counterfactual v5 absolute-plan replay",
            "data": "public OKX 5m OHLC; entry timestamp proxy = legacy row timestamp + 5 minutes",
            "inference": "percentile bootstrap of paired mean ΔR; exact two-sided sign test on non-zero paired ΔR",
            "warning": "counterfactual replay, not observed v5 production cohort",
        },
        "label": args.label,
        "overall": _paired_metrics(df, args.bootstrap_reps, rng),
        "embargo_72h_proxy": _paired_metrics(_embargo_subset(df, 72), args.bootstrap_reps, rng),
        "cost_sensitivity": _cost_sensitivity(df),
        "by_setup": {setup: _paired_metrics(g, args.bootstrap_reps, rng) for setup, g in df.groupby("setup")},
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"v5_comparison_{args.label}_stats.json"
    txt_path = out_dir / f"v5_comparison_{args.label}_stats.txt"
    chart_path = out_dir / f"v5_comparison_{args.label}_setup_delta.png"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    _chart(df, chart_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"CHART={chart_path}")


if __name__ == "__main__":
    main()
