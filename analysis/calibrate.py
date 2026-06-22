"""[Phase 2] 오프라인 보정 잡 — 계층적 부분풀링(partial pooling). 주 1회 CI.

라이브는 산출물(calibration_table.json)의 셀별 δ_eff만 읽는다(여기선 학습만).

구(舊) 방식의 자격 게이트(독립 N≥100 × 거시≥2종)는 데이터 누적 대비 비현실적이라
어떤 셀도 보정되지 못했다(실효≈0). 이를 폐기하고 random-intercept 로지스틱으로 교체:

  계층  GLOBAL → SETUP → BASE(setup×regime) → CELL(setup×regime×macro)
  ① prior 기울기(wC/wL/wF) 고정 — 소표본에서 (C,L,F) 반응성 재학습 금지(과적합 차단).
  ② 셀 승률을 Beta-Binomial로 부모 승률에 수축:
        wr_pooled = (wr_obs·n_indep + wr_parent·k) / (n_indep + k)
     데이터 적으면 부모로 회귀, 쌓이면 자기 셀로 수렴(자격 0/1 이분법 폐기).
  ③ 셀 절편 오프셋  δ = logit(wr_pooled) − logit(prior_raw_mean)
        (prior가 이 셀에서 얼마나 어긋났나 = 보정해야 할 로그오즈 양)
  ④ 신뢰도 가중 + 하드캡  δ_eff = clamp( conf·δ , ±delta_cap ),  conf = n_indep/(n_indep+k_conf)
  ⑤ 비정상성 가드: 부모(setup×regime)가 거시방향별로 승률이 갈리면(베타착시) conf 페널티.

수축·신뢰도의 n은 모두 '독립표본 n'(72h 중첩 탈상관, stride=24h) — 명목 n의 과신 차단.
산출물은 셀별 {n, n_indep, wr_pooled, delta_eff, win_floor, p_source}. 라이브는 δ_eff만.

CLI:
  python analysis/calibrate.py            # JSONL → calibration_table.json 생성
  python analysis/calibrate.py --dry-run  # 파일 쓰지 않고 요약만
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "src"))
sys.path.insert(0, os.path.join(_HERE, "..", "src", "wrf"))

import build_dataset as bd  # noqa: E402
import labels as lab  # noqa: E402
import config  # noqa: E402
import calibration as live_calib  # noqa: E402  (src/wrf/calibration.py — prior 일관성)


_EPS = 1e-6


def _logit(p: float) -> float:
    p = min(1.0 - _EPS, max(_EPS, p))
    return math.log(p / (1.0 - p))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def independent_n(ts_series: pd.Series, stride_h: float) -> int:
    """탈중첩 독립표본 수(72h 자기상관 차단): stride_h 간격으로 그리디 선택."""
    ts = ts_series.dropna().sort_values()
    if ts.empty:
        return 0
    count, last = 0, None
    for t in ts:
        if last is None or (t - last).total_seconds() / 3600.0 >= stride_h:
            count += 1
            last = t
    return count


def _shrink(wr_obs: float, n_eff: float, wr_parent: float, k: float) -> float:
    """Beta-Binomial 수축: 부모 승률을 k 의사관측으로 본 사후평균."""
    denom = n_eff + k
    if denom <= 0:
        return wr_parent
    return (wr_obs * n_eff + wr_parent * k) / denom


def calibrate(data_dir: str) -> dict:
    rows = bd.load_snapshots(data_dir)
    df = lab.candidate_dataset(rows)

    stride = getattr(config, "WRF_INDEP_STRIDE_H", 24)
    floor = getattr(config, "WRF_WIN_FLOOR", 0.58)
    k_setup = getattr(config, "WRF_CALIB_K_SETUP", 40.0)
    k_base = getattr(config, "WRF_CALIB_K_BASE", 30.0)
    k_cell = getattr(config, "WRF_CALIB_K_CELL", 25.0)
    k_conf = getattr(config, "WRF_CALIB_K_CONF", 20.0)
    min_dec = getattr(config, "WRF_CALIB_MIN_DECIDED", 3)
    delta_cap = getattr(config, "WRF_CALIB_DELTA_CAP", 1.2)

    base_params = {
        "method": "partial_pooling", "k_setup": k_setup, "k_base": k_base,
        "k_cell": k_cell, "k_conf": k_conf, "min_decided": min_dec,
        "delta_cap": delta_cap, "stride_h": stride, "floor": floor,
    }
    if df.empty:
        return _empty_report(base_params, "표본 0 — 전부 prior(콜드스타트)")

    # 결판(WIN/LOSS)만 보정 모집단. TIMEOUT=스크래치 제외.
    dec = df[df["tb_win"].notna()].copy()
    if dec.empty:
        return _empty_report(base_params, "결판 후보 0(경로 미성숙) — 전부 prior")

    dec["btc_macro"] = dec["btc_macro"].astype(str)
    dec["base"] = dec["setup"].astype(str) + "|" + dec["regime_1h"].astype(str)

    # ── 계층 수축 cascade: GLOBAL → SETUP → BASE ──────────────────────
    wr_global = float(dec["tb_win"].mean())

    wr_setup = {}
    for s, g in dec.groupby("setup"):
        n_ind = independent_n(g["ts"], stride)
        wr_setup[s] = _shrink(float(g["tb_win"].mean()), n_ind, wr_global, k_setup)

    wr_base, base_macro = {}, {}
    for b, g in dec.groupby("base"):
        setup = b.split("|")[0]
        parent = wr_setup.get(setup, wr_global)
        n_ind = independent_n(g["ts"], stride)
        wr_base[b] = _shrink(float(g["tb_win"].mean()), n_ind, parent, k_base)
        # 베타착시(비정상성): 거시방향별 승률 분산(각 ≥5건). 한쪽만 성립하면 페널티.
        per_macro = {m: float(gm["tb_win"].mean())
                     for m, gm in g.groupby("btc_macro") if len(gm) >= 5}
        illusion = False
        if len(per_macro) >= 2:
            vals = list(per_macro.values())
            above = [v for v in vals if v >= floor]
            below = [v for v in vals if v < floor - 0.1]
            illusion = bool(len(above) == 1 and below)
        base_macro[b] = {"per_macro": per_macro, "macro_coverage": len(per_macro),
                         "beta_illusion": illusion}

    # ── CELL: 수축 승률 → δ → δ_eff ───────────────────────────────────
    cells, drift = {}, {}
    for cell, g in dec.groupby("cell"):
        setup, regime, macro = (str(cell).split("|") + ["", "", ""])[:3]
        base = f"{setup}|{regime}"
        n = len(g)
        n_ind = independent_n(g["ts"], stride)
        wr_obs = float(g["tb_win"].mean())
        parent = wr_base.get(base, wr_setup.get(setup, wr_global))
        wr_pooled = _shrink(wr_obs, n_ind, parent, k_cell)

        # 이 셀 결판후보들의 prior raw 평균(δ 기준선; 라이브 base와 동일 정의)
        priors = [live_calib.prior_raw_p(setup, float(c), float(l), float(f))
                  for c, l, f in zip(g["C"], g["L"], g["F"])
                  if c is not None and l is not None and f is not None]
        p_prior_mean = sum(priors) / len(priors) if priors else None

        bm = base_macro.get(base, {"beta_illusion": False, "macro_coverage": 0,
                                   "per_macro": {}})
        rec = {
            "n": int(n), "n_indep": int(n_ind),
            "base": base, "win_rate": round(wr_obs, 4),
            "wr_pooled": round(wr_pooled, 4),
            "wr_parent": round(parent, 4),
            "macro_coverage": int(bm["macro_coverage"]),
            "beta_illusion": bool(bm["beta_illusion"]),
            "win_floor": floor, "p_source": "prior", "delta_eff": 0.0,
        }
        if p_prior_mean is not None and n >= min_dec:
            delta = _logit(wr_pooled) - _logit(p_prior_mean)
            conf = n_ind / (n_ind + k_conf) if (n_ind + k_conf) > 0 else 0.0
            if bm["beta_illusion"]:
                conf *= 0.5  # 비정상성 페널티(한쪽 거시에서만 성립)
            delta_eff = _clamp(conf * delta, -delta_cap, delta_cap)
            rec.update({
                "p_prior_mean": round(p_prior_mean, 4),
                "delta": round(delta, 4), "confidence": round(conf, 4),
                "delta_eff": round(delta_eff, 4),
                "p_source": "calibrated" if abs(delta_eff) > 1e-4 else "prior",
            })
        cells[cell] = rec
        drift[cell] = {"n": int(n), "win_rate": round(wr_obs, 4),
                       "wr_pooled": round(wr_pooled, 4)}

    n_cal = sum(1 for c in cells.values() if c["p_source"] == "calibrated")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": getattr(config, "WRF_SCHEMA_VERSION", 3),
        "params": base_params,
        "global": {"win_rate": round(wr_global, 4), "n_decided": int(len(dec))},
        "setups": {s: round(v, 4) for s, v in wr_setup.items()},
        "bases": {b: round(v, 4) for b, v in wr_base.items()},
        "n_cells": len(cells), "n_calibrated": n_cal,
        "cells": cells, "drift": drift,
    }
    return report


def _empty_report(params: dict, note: str) -> dict:
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": getattr(config, "WRF_SCHEMA_VERSION", 3),
            "params": params, "cells": {}, "n_cells": 0, "n_calibrated": 0,
            "note": note}


def _write(path: str, report: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description="WRF Phase 2 부분풀링 보정 잡")
    ap.add_argument("--dir", default=getattr(config, "RESEARCH_DATA_DIR", "data/research"))
    ap.add_argument("--out", default=getattr(config, "WRF_CALIB_TABLE", "data/calibration_table.json"))
    ap.add_argument("--dry-run", action="store_true", help="파일 쓰지 않고 요약만")
    args = ap.parse_args()

    rep = calibrate(args.dir)
    if not args.dry_run:
        _write(args.out, rep)

    g = rep.get("global", {})
    print(f"보정(부분풀링) 완료: {rep.get('n_cells', 0)}셀 중 보정활성 "
          f"{rep.get('n_calibrated', 0)}셀  (전역승률 {g.get('win_rate')}, "
          f"결판 {g.get('n_decided', 0)})")
    if rep.get("note"):
        print(f"  · {rep['note']}")
    for cell, c in sorted(rep.get("cells", {}).items(),
                          key=lambda kv: -abs(kv[1].get("delta_eff", 0))):
        flag = "✅보정" if c["p_source"] == "calibrated" else "·prior"
        extra = (f" δ_eff={c.get('delta_eff')} conf={c.get('confidence')}"
                 if c["p_source"] == "calibrated" else "")
        print(f"  {flag} {cell}: n={c['n']} indep={c['n_indep']} "
              f"wr={c['win_rate']}→pool={c['wr_pooled']}"
              f"{' 베타착시' if c['beta_illusion'] else ''}{extra}")
    if not args.dry_run:
        print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
