"""본전스톱(break-even) 검증 — 저장 72h 경로 봉순서 리플레이. {0.8,1.0,1.2} 플래토.

규칙: 진입 후 유리방향 MFE가 X·R 도달 시 SL을 진입가(0R)로 이동. 이후 진입가 터치 시
스크래치(0R). 봉 순서 보존(MFE/MAE 요약이 아니라 h/l 배열 순회) — 정직한 리플레이.

사전등록 판정(과적합 규율): 신규 자유도 1개(X). **전방 관련 모집단(non-BR 발사)** 에서
세 X가 함께 기대R·MaxDD 개선(플래토)일 때만 채택. 특정 X에서만 좋으면 곡선맞춤 → 보류.

[2026-07 판정] non-BR 발사(n≈7)에서 효과 정확히 0(전부 TP직행/SL직행 — arming-후-반전
패턴 부재). 측정된 이득은 전부 섀도 처리된 BR 모집단에 국한 → **미채택(HOLD)**. C축 v2와
동일 구조의 '제거된 모집단 신기루'. 데이터 축적 후 재실행으로 자동 재판정. 재실행:
  python analysis/audit/verify_breakeven.py
"""
import os
import sys
from statistics import mean

sys.path.insert(0, "analysis")
sys.path.insert(0, "src")
sys.path.insert(0, "src/wrf")

import build_dataset as bd
import labels as lab


def replay_be(path, direction, sl_frac, tp_frac, t_max, be_x, sl_priority=True):
    """triple_barrier + 본전스톱(be_x=None → 순수 baseline). 반환 (outcome, r_multiple)."""
    o = path.get("o") or []
    h = path.get("h") or []
    l = path.get("l") or []
    c = path.get("c") or []
    if not c or sl_frac <= 0 or tp_frac <= 0:
        return None
    e = (o[0] if o else 0.0)
    base = 1.0 + e
    long = direction == "long"
    tp_lvl = base * (1 + tp_frac) if long else base * (1 - tp_frac)
    sl_lvl = base * (1 - sl_frac) if long else base * (1 + sl_frac)
    arm_lvl = (base * (1 + be_x * sl_frac) if long else base * (1 - be_x * sl_frac)) \
        if be_x is not None else None
    n = min(len(c), int(t_max))
    armed = False
    for i in range(n):
        hi = 1.0 + (h[i] if i < len(h) else c[i])
        lo = 1.0 + (l[i] if i < len(l) else c[i])
        stop = base if armed else sl_lvl           # armed → 진입가(0R)
        sl_hit = (lo <= stop) if long else (hi >= stop)
        tp_hit = (hi >= tp_lvl) if long else (lo <= tp_lvl)
        if sl_hit and tp_hit:                       # 동일봉 → 보수적 stop 우선
            return ("SCRATCH", 0.0) if armed else ("LOSS", -1.0)
        if sl_hit:
            return ("SCRATCH", 0.0) if armed else ("LOSS", -1.0)
        if tp_hit:
            return ("WIN", tp_frac / sl_frac)
        if be_x is not None and not armed:          # 봉 마감까지 무청산 → arming(다음 봉부터)
            if (hi >= arm_lvl) if long else (lo <= arm_lvl):
                armed = True
    if len(c) < n or (not path.get("complete") and len(c) < int(t_max)):
        return None
    realized = (1.0 + c[n - 1]) / base - 1.0
    if not long:
        realized = -realized
    return ("TIMEOUT", realized / sl_frac if sl_frac > 0 else 0.0)


def _maxdd(rs):
    peak = cum = mdd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return round(mdd, 2)


def evaluate(pop, be_x):
    recs = []
    for r, cd in pop:
        path = r.get("path")
        if not path or not path.get("c"):
            continue
        entry, tp, sl = cd.get("entry"), cd.get("tp"), cd.get("sl")
        if not entry or not tp or not sl:
            continue
        res = replay_be(path, cd["dir"], abs(entry - sl) / entry,
                        abs(tp - entry) / entry, cd.get("t_max", 48), be_x)
        if res:
            recs.append(res)
    rs = [r for _, r in recs]
    dec = [o for o, _ in recs if o in ("WIN", "LOSS")]
    win = sum(1 for o in dec if o == "WIN")
    pos = sum(r for r in rs if r > 0)
    neg = -sum(r for r in rs if r < 0)
    return {"n": len(recs), "expR": round(mean(rs), 3) if rs else None,
            "maxdd": _maxdd(rs), "win%": round(100 * win / len(dec), 1) if dec else None,
            "scratch": sum(1 for o, _ in recs if o == "SCRATCH"),
            "PF": round(pos / neg, 2) if neg > 0 else float("inf")}


def main():
    rows = bd.load_snapshots("data/research")
    lab.candidate_dataset(rows)   # in-place BR split
    all_fired, nonbr = [], []
    for r in rows:
        for cd in r.get("candidates", []):
            if cd.get("fire"):
                all_fired.append((r, cd))
                if cd.get("setup") != "BR":
                    nonbr.append((r, cd))

    print("=" * 72)
    print("본전스톱 검증 — 플래토(전방 non-BR 모집단에서 X 전체 개선)일 때만 채택")
    print("=" * 72)
    for label, pop in [("전체 발사(역사적·BR 포함)", all_fired),
                       ("non-BR 발사(★전방 관련·판정 기준)", nonbr)]:
        print(f"\n【{label}】 n={len(pop)}")
        print(f"  {'변형':<12}{'n':>4}{'기대R':>8}{'MaxDD':>8}{'승률%':>7}{'스크':>5}{'PF':>7}")
        base = evaluate(pop, None)
        print(f"  {'baseline':<12}{base['n']:>4}{str(base['expR']):>8}{base['maxdd']:>8}"
              f"{str(base['win%']):>7}{base['scratch']:>5}{str(base['PF']):>7}")
        for x in (0.8, 1.0, 1.2):
            ev = evaluate(pop, x)
            d = (f"  ΔexpR={ev['expR'] - base['expR']:+.3f}"
                 if ev['expR'] is not None and base['expR'] is not None else "")
            print(f"  {'BE X=' + str(x):<12}{ev['n']:>4}{str(ev['expR']):>8}{ev['maxdd']:>8}"
                  f"{str(ev['win%']):>7}{ev['scratch']:>5}{str(ev['PF']):>7}{d}")
    print("\n판정: non-BR 모집단에서 X 전체 개선(플래토) 시 채택. 아니면 HOLD.")


if __name__ == "__main__":
    main()
