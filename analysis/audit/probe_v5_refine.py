"""probe_v5_refine.py — C축 V5 실전점등 전 정교화 근거 재현 (탐색적·판정 아님).

README `#changelog` "[C축 V5 실전실험]" 항목의 두 정교화 결정을 재현한다:
  ① 부스트 지각조건: slow-lag(심볼 자체 4H/일봉/macro 블렌드<0) vs macro-only(btc_macro만)
     → macro-only는 새발사 0(과엄격·자기FN)로 기각, slow-lag 채택.
  ② 부스트 신선윈도 K 민감도(4~18) → 무감이면 기본 6 유지(샘플튜닝 금지).

저장 스냅샷 반사실(verify_caxis_v5.py Part B와 동일한 재생 로직 — 추종 후보의 저장 C에
부스트 max-클램프를 적용해 '새로 열린 발사'만 격리 채점). 판정 아님(단일레짐·소표본).

CLI: python analysis/audit/probe_v5_refine.py
"""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "src", "wrf"))
sys.path.insert(0, os.path.join(_ROOT, "analysis"))

import config  # noqa: E402
import detectors as D  # noqa: E402
import calibration as CAL  # noqa: E402
import labels as LAB  # noqa: E402

FLOOR = getattr(config, "WRF_WIN_FLOOR", 0.58)
_CONT = {"TF", "BO"}


def load_rows():
    rows = []
    for fp in sorted(glob.glob(os.path.join(_ROOT, "data", "research", "*", "*.jsonl"))):
        for line in open(fp, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
            except json.JSONDecodeError:
                continue
            if s.get("schema_version") == 3 and (s.get("path") or {}).get("c"):
                rows.append(s)
    return LAB.split_band_reversal(rows)


def _fixed_r(c, path):
    e, tp, sl = c.get("entry"), c.get("tp"), c.get("sl")
    if not e or not tp or not sl:
        return None
    return LAB.triple_barrier(path, c["dir"], abs(e - sl) / e, abs(tp - e) / e, c.get("t_max", 48))


def _fire(setup, C, L, F, rr, vn):
    p = CAL.prior_p_hat(setup, C, L, F)
    if vn > 0:
        return False, p
    ev = p * rr - (1.0 - p)
    return bool(p >= FLOOR and ev >= getattr(config, "WRF_EV_MIN", 0.15)
                and rr >= getattr(config, "WRF_EV_RR_FLOOR", 0.85)), p


def _flip_hist(by_sym):
    out = {}
    for sym, tsmap in by_sym.items():
        tss = sorted(tsmap)
        for i, ts in enumerate(tss):
            res = []
            for key in ("dist_vwap_atr", "dist_ema20_atr"):
                cur = (tsmap[ts]["raw"] or {}).get(key)
                if cur is None or cur == 0:
                    res.append(None)
                    continue
                bars = None
                for k in range(1, i + 1):
                    pt, ct = tss[i - k], tss[i - k + 1]
                    if (ct - pt).total_seconds() > 5400:
                        break
                    x = (tsmap[pt]["raw"] or {}).get(key)
                    if x is None:
                        break
                    if x * cur <= 0:
                        bars = k - 1
                        break
                res.append(bars)
            out[(sym, ts)] = tuple(res)
    return out


def _boost_c(C, ctx, raw, direction, fv, fe, lag_mode, k):
    n = D._reclaim_n(raw, direction)
    if n < getattr(config, "WRF_REV_RECLAIM_MIN", 2):
        return C
    sgn = 1 if direction == "long" else -1
    dv, de = raw.get("dist_vwap_atr"), raw.get("dist_ema20_atr")
    fresh = ((fv is not None and fv <= k and (dv or 0) * sgn > 0)
             or (fe is not None and fe <= k and (de or 0) * sgn > 0))
    if not fresh:
        return C
    ev = D._struct_evidence(ctx, raw)
    if lag_mode == "slow":
        val = D._slow_align(ev)
    else:  # macro-only
        val = ev["m"]
    lag = (val < 0) if direction == "long" else (val > 0)
    if not lag:
        return C
    return max(C, 0.50 if n >= 3 else 0.25)


def _agg(tbs):
    dec = [t for t in tbs if t and t.get("tb_win") is not None]
    rs = [t["r_multiple"] for t in tbs if t and t.get("r_multiple") is not None]
    return (f"새발사 n={len(tbs)} 결판={len(dec)} "
            f"win%={round(100 * sum(t['tb_win'] for t in dec) / len(dec), 1) if dec else None} "
            f"expR={round(st.mean(rs), 3) if rs else None}")


def _run(rows, flips, lag_mode, k):
    opened = []
    for r in rows:
        raw, ctx, path = r["raw"], r.get("ctx") or {}, r["path"]
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (ValueError, TypeError):
            continue
        fv, fe = flips.get((r["symbol"], ts), (None, None))
        fv = raw.get("bars_since_vwap_flip", fv)
        fe = raw.get("bars_since_ema20_flip", fe)
        for c in r.get("candidates") or []:
            if c.get("setup") not in _CONT or None in (c.get("C"), c.get("L"), c.get("F")):
                continue
            f0, _ = _fire(c["setup"], c["C"], c["L"], c["F"], c.get("rr", 2.0), len(c.get("veto") or []))
            C2 = _boost_c(c["C"], ctx, raw, c["dir"], fv, fe, lag_mode, k)
            if C2 == c["C"]:
                continue
            f1, _ = _fire(c["setup"], C2, c["L"], c["F"], c.get("rr", 2.0), len(c.get("veto") or []))
            if f1 and not f0:
                opened.append(_fixed_r(c, path))
    return opened


def main():
    rows = load_rows()
    by_sym = defaultdict(dict)
    for r in rows:
        try:
            by_sym[r["symbol"]][datetime.fromisoformat(r["ts"])] = r
        except (ValueError, TypeError):
            continue
    flips = _flip_hist(by_sym)

    print("① 부스트 지각조건: slow-lag vs macro-only (K=6)")
    for mode in ("slow", "macro"):
        print(f"   [{mode:5}] {_agg(_run(rows, flips, mode, 6))}")
    print("   → macro-only가 0발사면 slow-lag 채택(심볼-로컬 지각을 macro-only가 못 잡음).")

    print("\n② 신선윈도 K 민감도 (slow-lag)")
    for k in (4, 6, 8, 12, 18):
        print(f"   K={k:2}: {_agg(_run(rows, flips, 'slow', k))}")
    print("   → 무감이면 기본 K=6 유지(샘플튜닝 금지).")


if __name__ == "__main__":
    main()
