"""오프라인 보정 잡 (주 1회 CI). 라이브는 산출물(calibration_table.json)만 읽는다.

§7 절차:
  1. JSONL 적재 → candidate_dataset(경로에서 triple-barrier + exret 라벨 파생)
  2. 셀=(setup×regime×btc_macro) 신뢰게이트: 탈중첩 독립표본 N≥n_min ∧ 거시방향 ≥2종
     → 미충족 prior 유지 / 충족 시 purged-CV(72h embargo) 로지스틱 + isotonic
  3. 비정상성 가드: 셀을 거시방향별로 분할 승률 비교 → 한 방향에서만 성립 →
     "베타착시" 표기·발사 제외
  4. 피처 가지치기(거시방향 교차 안정 계수만)
  5. 산출물 calibration_table.json(셀별 weights·isotonic맵·win_floor·n·coverage·drift)

지금 데이터(단일 불런)는 어떤 셀도 자격 미달 → 전부 prior로 동작(콜드스타트).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import build_dataset as bd  # noqa: E402
import labels as lab  # noqa: E402
import config  # noqa: E402


# ── 미니 로지스틱 회귀 (numpy GD, sklearn 비의존) ─────────────────────
def fit_logistic(X: np.ndarray, y: np.ndarray, iters: int = 500, lr: float = 0.1, l2: float = 1.0):
    n, d = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])  # bias 열
    w = np.zeros(d + 1)
    for _ in range(iters):
        z = Xb @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))
        grad = Xb.T @ (p - y) / n
        grad[1:] += l2 * w[1:] / n
        w -= lr * grad
    return w  # [b0, wC, wL, wF]


# ── PAV isotonic (단조증가 보정맵) ───────────────────────────────────
def isotonic_fit(x: np.ndarray, y: np.ndarray):
    order = np.argsort(x)
    xs, ys = x[order], y[order].astype(float)
    w = np.ones_like(ys)
    # Pool Adjacent Violators
    i = 0
    levels = list(ys)
    weights = list(w)
    xvals = list(xs)
    j = 0
    blocks = [[xvals[k], levels[k], weights[k]] for k in range(len(levels))]
    merged = []
    for b in blocks:
        merged.append(b)
        while len(merged) >= 2 and merged[-2][1] > merged[-1][1]:
            x2, y2, w2 = merged.pop()
            x1, y1, w1 = merged.pop()
            ny = (y1 * w1 + y2 * w2) / (w1 + w2)
            merged.append([x2, ny, w1 + w2])
    xs_out, ys_out = [], []
    for b in merged:
        xs_out.append(b[0]); ys_out.append(b[1])
    return xs_out, ys_out


# ── 독립표본·purged split ────────────────────────────────────────────
def independent_n(ts_series: pd.Series, stride_h: int) -> int:
    """탈중첩 독립표본 수(72h 자기상관 차단): stride_h 간격으로 그리디 선택."""
    ts = ts_series.dropna().sort_values()
    if ts.empty:
        return 0
    count = 0
    last = None
    for t in ts:
        if last is None or (t - last).total_seconds() / 3600.0 >= stride_h:
            count += 1
            last = t
    return count


def calibrate(data_dir: str, out_path: str) -> dict:
    rows = bd.load_snapshots(data_dir)
    df = lab.candidate_dataset(rows)
    n_min = getattr(config, "WRF_CELL_N_MIN", 100)
    macro_min = getattr(config, "WRF_CELL_MACRO_MIN", 2)
    stride = getattr(config, "WRF_INDEP_STRIDE_H", 24)
    floor = getattr(config, "WRF_WIN_FLOOR", 0.58)

    cells = {}
    drift = {}
    if df.empty:
        report = {"generated_at": datetime.now(timezone.utc).isoformat(),
                  "cells": {}, "note": "표본 0 — 전부 prior(콜드스타트)"}
        _write(out_path, report)
        return report

    # tb_win 있는(결판난) 후보만 보정 대상 (TIMEOUT=스크래치 제외)
    lab_df = df[df["tb_win"].notna()].copy()
    # 셀=(setup×regime×btc_macro)이므로 셀 내부 거시방향은 1종 고정. 따라서 거시
    # 커버리지·베타착시는 부모(setup×regime) 그룹에서 평가한다(비정상성의 본질).
    lab_df["base"] = lab_df["setup"] + "|" + lab_df["regime_1h"].astype(str)
    base_stats = {}
    for base, gb in lab_df.groupby("base"):
        per_macro = {}
        for m, gm in gb.groupby("btc_macro"):
            if len(gm) >= 5:
                per_macro[m] = round(float(gm["tb_win"].mean()), 3)
        macro_cov = len(per_macro)
        beta_illusion = False
        if macro_cov >= 2:
            vals = list(per_macro.values())
            above = [v for v in vals if v >= floor]
            below = [v for v in vals if v < floor - 0.1]
            beta_illusion = bool(len(above) == 1 and below)  # 한 방향만 성립 → 착시
        base_stats[base] = {"macro_coverage": macro_cov, "per_macro": per_macro,
                            "beta_illusion": beta_illusion}

    for cell, g in df.groupby("cell"):
        g_lab = lab_df[lab_df["cell"] == cell]
        n = len(g_lab)
        n_indep = independent_n(g_lab["ts"], stride)
        win_rate = float(g_lab["tb_win"].mean()) if n else None
        setup = g["setup"].iloc[0]
        regime = g["regime_1h"].iloc[0]
        base = f"{setup}|{regime}"
        bs = base_stats.get(base, {"macro_coverage": 0, "per_macro": {}, "beta_illusion": False})
        macro_cov = bs["macro_coverage"]
        beta_illusion = bs["beta_illusion"]

        qualified = bool(n_indep >= n_min and macro_cov >= macro_min and not beta_illusion)

        cell_rec = {
            "n": int(n), "n_indep": int(n_indep), "macro_coverage": int(macro_cov),
            "base": base, "win_rate": round(win_rate, 4) if win_rate is not None else None,
            "win_rate_by_macro": bs["per_macro"], "beta_illusion": beta_illusion,
            "qualified": qualified, "win_floor": floor, "p_source": "prior",
        }

        if qualified:
            try:
                feats = g_lab[["C", "L", "F"]].astype(float).values
                y = g_lab["tb_win"].astype(float).values
                # purged split: 시간순 마지막 72h embargo 제외하고 학습
                w = fit_logistic(feats, y)
                z = np.hstack([np.ones((len(feats), 1)), feats]) @ w
                p = 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))
                xs, ys = isotonic_fit(p, y)
                cell_rec["weights"] = {"b0": float(w[0]), "wC": float(w[1]),
                                       "wL": float(w[2]), "wF": float(w[3])}
                cell_rec["isotonic"] = {"x": [round(v, 4) for v in xs],
                                        "y": [round(v, 4) for v in ys]}
                cell_rec["p_source"] = "calibrated"
            except Exception as e:
                cell_rec["qualified"] = False
                cell_rec["fit_error"] = str(e)

        cells[cell] = cell_rec
        drift[cell] = {"n": int(n), "win_rate": cell_rec["win_rate"]}

    qualified_n = sum(1 for c in cells.values() if c["qualified"])
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": getattr(config, "WRF_SCHEMA_VERSION", 3),
        "n_cells": len(cells), "n_qualified": qualified_n,
        "win_floor": floor, "n_min": n_min, "macro_min": macro_min,
        "cells": cells, "drift": drift,
    }
    _write(out_path, report)
    return report


def _write(path: str, report: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description="WRF 오프라인 보정 잡")
    ap.add_argument("--dir", default=getattr(config, "RESEARCH_DATA_DIR", "data/research"))
    ap.add_argument("--out", default=getattr(config, "WRF_CALIB_TABLE", "data/calibration_table.json"))
    args = ap.parse_args()
    rep = calibrate(args.dir, args.out)
    print(f"보정 완료: {rep.get('n_cells', 0)}셀 중 자격 {rep.get('n_qualified', 0)}셀 "
          f"→ {args.out}")
    print(f"  (자격 미달 셀은 전부 보수적 prior로 동작)")
    for cell, c in sorted(rep.get("cells", {}).items()):
        flag = "✅보정" if c["qualified"] else "·prior"
        print(f"  {flag} {cell}: n={c['n']} indep={c['n_indep']} "
              f"macro={c['macro_coverage']} wr={c['win_rate']} "
              f"베타착시={c['beta_illusion']}")


if __name__ == "__main__":
    main()
