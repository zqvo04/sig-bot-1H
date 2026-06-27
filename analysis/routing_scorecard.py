"""routing_scorecard.py — 레짐 라우팅-유틸리티 스코어카드 (오프라인 측정 · 라이브 무수정)

레짐 라벨의 '정확도'를 **방향예측이 아니라 라우팅 유틸리티**로 잰다. 레짐의 유일한
임무는 라우팅(셋업군 선택)이므로, 정답은 "그 라벨이 실제로 돈 셋업군으로 보냈는가"다.

각 스냅샷에서 경로(path)로:
  · 추종(continuation) = EMA20 위치방향(아래=숏/위=롱) triple-barrier 실현 R
  · 반전(reversion)    = 역방향 실현 R
  · 정답 truth = 1 if R_추종 > R_반전 ('추종이 돈' 환경) else 0
봇 regime_1h가 이 정답과 얼마나 정합하는지(추종이 돈 비율 + Wilson CI)를 셀별 집계한다.
TRENDING/SQUEEZE는 추종(TF/BO)을, RANGING은 반전(MR/RV) 라우팅을 허용하므로,
"추종이 돈 비율"이 높은 셀에서 TRENDING이 떠야 라우팅이 옳다.

barrier 의미는 analysis/labels.triple_barrier 와 동일(SL/TP 진입가대비 비율, sl_priority).
의존성 경량화(측정 전용)를 위해 순수 함수로 자립 구현한다.

CLI:
  python analysis/routing_scorecard.py                 # 기본(SL=2ATR·RR=2·48h·|distEMA20|≥0.3)
  python analysis/routing_scorecard.py --min-n 48 --clear-pos 0.3 --sl-atr 2.0 --rr 2.0
"""
from __future__ import annotations

import argparse
import bisect
import glob
import json
import math
import os
import statistics
from collections import Counter, defaultdict

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DATA = os.path.join(_ROOT, "data", "research")


def _load_v3(data_dir: str) -> list[dict]:
    rows = []
    for fp in sorted(glob.glob(os.path.join(data_dir, "*", "*.jsonl"))):
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    s = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if s.get("schema_version") == 3 and (s.get("path") or {}).get("c"):
                    rows.append(s)
    return rows


def _triple_barrier(path: dict, direction: str, sl_frac: float, tp_frac: float,
                    t_max: int, sl_priority: bool = True):
    """labels.triple_barrier 미러. r_multiple 반환(None=미성숙/스크래치)."""
    o = path.get("o") or []
    h = path.get("h") or []
    l = path.get("l") or []
    c = path.get("c") or []
    if not c or sl_frac <= 0 or tp_frac <= 0:
        return None
    e = float(o[0]) if o else 0.0
    base = 1.0 + e
    long = direction == "long"
    tp_lvl = base * (1 + tp_frac) if long else base * (1 - tp_frac)
    sl_lvl = base * (1 - sl_frac) if long else base * (1 + sl_frac)
    n = min(len(c), int(t_max))
    for i in range(n):
        hi = 1.0 + (h[i] if i < len(h) else c[i])
        lo = 1.0 + (l[i] if i < len(l) else c[i])
        sl_hit = (lo <= sl_lvl) if long else (hi >= sl_lvl)
        tp_hit = (hi >= tp_lvl) if long else (lo <= tp_lvl)
        if sl_hit:
            return -1.0
        if tp_hit:
            return tp_frac / sl_frac
    if len(c) < n:
        return None
    if not path.get("complete") and len(c) < int(t_max):
        return None
    realized = (1.0 + c[n - 1]) / base - 1.0
    if not long:
        realized = -realized
    return realized / sl_frac


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z = 1.96
    ph = k / n
    d = 1 + z * z / n
    centre = (ph + z * z / (2 * n)) / d
    half = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half) * 100, min(1.0, centre + half) * 100)


def _auc(pairs: list[tuple]) -> float | None:
    """Mann-Whitney AUC of (value, label∈{0,1}). <0.5 = higher value → label 0."""
    pos = sorted(v for v, y in pairs if y == 1 and v is not None)
    neg = sorted(v for v, y in pairs if y == 0 and v is not None)
    if not pos or not neg:
        return None
    w = 0.0
    for v in pos:
        lo = bisect.bisect_left(neg, v)
        hi = bisect.bisect_right(neg, v)
        w += lo + (hi - lo) * 0.5
    return w / (len(pos) * len(neg))


def build(rows: list[dict], min_n: int, clear_pos: float,
          sl_atr: float, rr: float) -> list[dict]:
    """스냅샷 → 추종/반전 실현 R + 정답 라벨 레코드."""
    recs = []
    for s in rows:
        path = s["path"]
        if (path.get("n") or 0) < min_n:
            continue
        atr_pct = (s.get("raw") or {}).get("atr_pct")
        d20 = (s.get("raw") or {}).get("dist_ema20_atr")
        if not atr_pct or d20 is None or abs(d20) < clear_pos:
            continue  # 명확한 포지션(추종 방향 정의 가능)만
        af = atr_pct / 100.0
        cont = "short" if d20 < 0 else "long"
        rev = "long" if d20 < 0 else "short"
        r_cont = _triple_barrier(path, cont, sl_atr * af, sl_atr * rr * af, 48)
        r_rev = _triple_barrier(path, rev, sl_atr * af, sl_atr * rr * af, 48)
        if r_cont is None or r_rev is None:
            continue
        ctx = s.get("ctx") or {}
        recs.append({
            "regime_1h": ctx.get("regime_1h"), "btc_macro": ctx.get("btc_macro"),
            "symbol": s.get("symbol"), "adx": (s.get("raw") or {}).get("adx"),
            "r_cont": r_cont, "r_rev": r_rev, "truth": 1 if r_cont > r_rev else 0,
        })
    return recs


def report(recs: list[dict]) -> str:
    if not recs:
        return "표본 0건 — 경로(path≥min_n)·명확포지션 스냅샷이 없습니다."
    n = len(recs)
    base = statistics.mean(r["truth"] for r in recs)
    out = [
        "═══ 레짐 라우팅-유틸리티 스코어카드 ═══",
        f"표본 {n}건 | 기준 추종이 돈 비율 = {base*100:.0f}%  "
        f"(R_추종 {statistics.mean(r['r_cont'] for r in recs):+.2f} / "
        f"R_반전 {statistics.mean(r['r_rev'] for r in recs):+.2f})",
        "",
        "▸ bot regime_1h 별 — '추종이 돈 비율'이 높을수록 추종(TF/BO) 라우팅이 정답:",
        f"  {'regime':10}{'n':>5}{'cont-paid':>11}{'95%CI':>14}{'R_추종':>9}{'R_반전':>9}",
    ]
    for reg in ("TRENDING", "SQUEEZE", "RANGING", "EXPLOSIVE", "UNKNOWN"):
        sub = [r for r in recs if r["regime_1h"] == reg]
        if not sub:
            continue
        k = sum(r["truth"] for r in sub)
        lo, hi = _wilson(k, len(sub))
        skill = "←음(−)스킬" if k / len(sub) < base - 0.05 else ("←양(+)스킬" if k / len(sub) > base + 0.05 else "")
        out.append(f"  {reg:10}{len(sub):>5}{k/len(sub)*100:>10.0f}%"
                   f"{f'[{lo:.0f},{hi:.0f}]':>14}"
                   f"{statistics.mean(r['r_cont'] for r in sub):>+9.2f}"
                   f"{statistics.mean(r['r_rev'] for r in sub):>+9.2f}  {skill}")
    # regime × macro
    out += ["", "▸ regime_1h × btc_macro 별 추종이 돈 비율:"]
    cells = defaultdict(list)
    for r in recs:
        cells[(r["regime_1h"], r["btc_macro"])].append(r["truth"])
    for (reg, mac), ts in sorted(cells.items()):
        out.append(f"  {str(reg):10} {str(mac):8} n={len(ts):>3}  cont-paid={statistics.mean(ts)*100:>3.0f}%")
    # ADX 역전(라우팅에서 빼야 하는 신호) — AUC<0.5면 고ADX→페이드
    a = _auc([(r["adx"], r["truth"]) for r in recs])
    if a is not None:
        verdict = ("역전(고ADX→페이드) — 추세 트리거에서 제거 권고" if a < 0.45
                   else "정상(고ADX→추종)" if a > 0.55 else "무정보")
        out += ["", f"▸ ADX → 추종 AUC = {a:.3f}  ({verdict})",
                "  (라이브 강등 토글: WRF_REGIME_ADX_SOLE, 기본 강등)"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="레짐 라우팅-유틸리티 스코어카드(오프라인)")
    ap.add_argument("--dir", default=_DATA)
    ap.add_argument("--min-n", type=int, default=48, help="라벨 최소 경로 캔들 수")
    ap.add_argument("--clear-pos", type=float, default=0.3, help="|dist_ema20_atr| 최소(명확포지션)")
    ap.add_argument("--sl-atr", type=float, default=2.0, help="SL = N×ATR")
    ap.add_argument("--rr", type=float, default=2.0, help="TP = RR×SL")
    args = ap.parse_args()
    rows = _load_v3(args.dir)
    recs = build(rows, args.min_n, args.clear_pos, args.sl_atr, args.rr)
    print(report(recs))


if __name__ == "__main__":
    main()
