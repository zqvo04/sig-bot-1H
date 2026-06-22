"""backtest.py — Phase 1 백테스트/리플레이 하니스 (오프라인 전용).

저장된 72h 경로(path) × 매시간 기록 후보(candidates)를 triple-barrier로 재생해
현 prior의 **실현 성능**을 정량화한다. 라이브 코드는 건드리지 않는다 — 측정만.
("못 재면 못 고친다" — 슈퍼업그레이드 로드맵 Phase 1.)

핵심 질문 2개에 답한다:
  1) 성능: 발사 후보의 실현 승률이 플로어(W_floor)를 실제로 만족하는가?
     (셀=setup×regime×btc_macro 별 승률·발사율·기대R·Profit Factor·MaxDD·보유봉)
  2) 빈도: precond를 통과한 후보가 veto / floor / RR 중 무엇에 컷되는가(게이트 퍼널).
     → 빈도 병목을 데이터로 식별(튜닝은 Phase 2의 몫).

통계 주의: 매시간 표본은 72h 윈도가 겹치는 자기상관 표본이라 유효 n ≪ 명목 n이고,
현재 누적(≈5일·단일 거시레짐)은 결론 도출 불가 구간이다. 본 하니스는 "엣지를 켜는"
도구가 아니라 "엣지를 측정·검증"하는 도구다. 결과는 항상 out-of-sample 재검증을 전제로 본다.

CLI:
  python analysis/backtest.py                  # 전체 + setup별 + macro별 성능 요약 + 퍼널
  python analysis/backtest.py --by cell        # 셀별 성능
  python analysis/backtest.py --by setup,btc_macro
  python analysis/backtest.py --fired-only     # 발사 후보만(실거래 근사)
  python analysis/backtest.py --funnel         # 게이트 퍼널만
  python analysis/backtest.py --min-n 10       # 신뢰 표본 컷
  python analysis/backtest.py --ab             # [Phase 2] prior vs 보정 A/B(Brier/캘리브레이션)
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_dataset import load_snapshots  # noqa: E402
import labels as lab  # noqa: E402

_CAVEAT = (
    "─" * 68 + "\n"
    "⚠ 측정 도구(Phase 1): 매시간 표본은 72h 중첩(자기상관) → 유효 n ≪ 명목 n.\n"
    "  · 현재 누적(≈5일·단일 거시레짐)은 결론 도출 불가 — 인프라 검증용 출력.\n"
    "  · 승률/기대R은 결판(WIN/LOSS) 기준, 타임아웃은 실현R로만 합산(스크래치).\n"
    "  · 모든 수치는 out-of-sample(시간분할+72h embargo) 재검증을 전제로 본다.\n"
    + "─" * 68
)

_PRESETS = {
    "all": [],
    "setup": ["setup"],
    "macro": ["btc_macro"],
    "regime": ["regime_1h"],
    "cell": ["cell"],
    "setup_macro": ["setup", "btc_macro"],
}


# ════════════════════════════════════════════════════════════════════
# 성능 지표
# ════════════════════════════════════════════════════════════════════

def _max_drawdown(equity: list) -> float:
    """누적 R 곡선의 최대 낙폭(R 단위, 음수)."""
    peak = 0.0
    mdd = 0.0
    cum = 0.0
    for r in equity:
        cum += r
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return round(mdd, 3)


def perf_metrics(g: pd.DataFrame) -> dict:
    """후보 그룹 → 성능 지표 dict. g는 candidate_dataset 행(경로 보유)."""
    n = len(g)
    fired = int(g["fire"].fillna(False).sum()) if "fire" in g else 0
    resolved = g[g["tb_r"].notna()].copy()           # WIN/LOSS/TIMEOUT(실현R 있음)
    decided = g[g["tb_win"].notna()].copy()          # WIN/LOSS만(승률 모집단)
    rec = {
        "n": n,
        "fire_rate%": round(fired / n * 100, 1) if n else None,
        "resolved": len(resolved),
        "decided": len(decided),
    }
    if len(decided):
        rec["win%"] = round(decided["tb_win"].mean() * 100, 1)
    if len(resolved):
        rs = resolved.sort_values("ts")["tb_r"].astype(float)
        rec["exp_R"] = round(rs.mean(), 3)
        pos = rs[rs > 0].sum()
        neg = -rs[rs < 0].sum()
        rec["PF"] = round(pos / neg, 2) if neg > 0 else float("inf")
        rec["maxdd_R"] = _max_drawdown(rs.tolist())
        if "tb_exit_h" in resolved:
            rec["hold_med"] = round(float(resolved["tb_exit_h"].median()), 1)
        rec["timeout%"] = round(
            (resolved["tb_outcome"] == "TIMEOUT").mean() * 100, 1)
    return rec


def performance_table(df: pd.DataFrame, by: list, min_n: int = 1) -> pd.DataFrame:
    """후보 long-format → 그룹별 성능 테이블. by=[] 면 전체 1행."""
    if df.empty:
        return df
    if not by:
        rec = {"group": "ALL"}
        rec.update(perf_metrics(df))
        return pd.DataFrame([rec])
    out = []
    for keys, g in df.groupby(by):
        keys = keys if isinstance(keys, tuple) else (keys,)
        rec = dict(zip(by, keys))
        rec.update(perf_metrics(g))
        out.append(rec)
    res = pd.DataFrame(out)
    sort_col = "decided" if "decided" in res else "n"
    res = res.sort_values(sort_col, ascending=False).reset_index(drop=True)
    res["reliable"] = res["resolved"] >= min_n
    return res


# ════════════════════════════════════════════════════════════════════
# 게이트 퍼널 (빈도 병목 진단)
# ════════════════════════════════════════════════════════════════════

def gate_funnel(df: pd.DataFrame) -> pd.DataFrame:
    """precond 통과 후보가 발사까지 어디서 컷되는지 퍼널.

    발사 = p_hat ≥ floor ∧ ¬veto ∧ RR ok. 미발사 후보를 사유별로 귀속:
      · VETO    : veto_n > 0
      · FLOOR   : p_hat < win_floor (min-axis 게이트가 floor 미만으로 눌린 경우 포함)
      · RR      : floor 통과·veto 없음인데 미발사 → RR < MIN_RR(prior 경로)
    ※ precond 컷은 JSONL에 기록되지 않으므로(디텍터가 precond 통과분만 적재) 관측 불가.
      이 퍼널은 'precond 통과 후' 단계만 본다.
    """
    if df.empty:
        return df
    d = df.copy()
    d["fire"] = d["fire"].fillna(False)
    d["veto_n"] = d["veto_n"].fillna(0)
    floor = d["win_floor"].fillna(0.58)
    vetoed = d["veto_n"] > 0
    below = (~vetoed) & (d["p_hat"] < floor)
    rr_cut = (~vetoed) & (d["p_hat"] >= floor) & (~d["fire"])

    def _row(name, mask):
        gg = d[mask]
        return {"setup": name, "candidates": int(mask.sum()),
                "fired": int(gg["fire"].sum())}

    out = []
    for setup, g in d.groupby("setup"):
        v = g["veto_n"] > 0
        fl = (~v) & (g["p_hat"] < g["win_floor"].fillna(0.58))
        rr = (~v) & (g["p_hat"] >= g["win_floor"].fillna(0.58)) & (~g["fire"])
        out.append({
            "setup": setup,
            "precond_passed": len(g),
            "→VETO": int(v.sum()),
            "→FLOOR": int(fl.sum()),
            "→RR": int(rr.sum()),
            "FIRED": int(g["fire"].sum()),
        })
    res = pd.DataFrame(out).sort_values("precond_passed", ascending=False)
    total = {
        "setup": "ALL", "precond_passed": len(d),
        "→VETO": int(vetoed.sum()), "→FLOOR": int(below.sum()),
        "→RR": int(rr_cut.sum()), "FIRED": int(d["fire"].sum()),
    }
    return pd.concat([res, pd.DataFrame([total])], ignore_index=True)


# ════════════════════════════════════════════════════════════════════
# [Phase 2] A/B 그림자 평가 — prior vs 보정 (Gate-Out 계측)
# ════════════════════════════════════════════════════════════════════

def _brier(p, y) -> float:
    """Brier 점수 = mean((p−y)²). 낮을수록 잘 보정됨(확률예측 정확도)."""
    import numpy as np
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(((p - y) ** 2).mean()) if len(p) else float("nan")


def _recompute_pcal(df: pd.DataFrame):
    """라이브 보정 모듈 + 현 테이블로 각 후보의 (p_prior, p_cal) 재계산.

    스냅샷에 그림자 필드(p_prior/p_cal)가 없는 과거 데이터도 즉시 A/B 가능하게 한다.
    (※ 현 테이블로 같은 데이터를 채점 = in-sample. OOS는 데이터 누적 후 시간분할.)
    """
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "wrf"))
    import calibration as cal
    table = cal.load_table()
    pri, pcal = [], []
    for _, r in df.iterrows():
        setup, C, L, F = r["setup"], r.get("C"), r.get("L"), r.get("F")
        if None in (C, L, F):
            pri.append(None); pcal.append(None); continue
        cand = {"setup": setup, "C": float(C), "L": float(L), "F": float(F)}
        ctx = {"regime_1h": r.get("regime_1h"), "btc_macro": r.get("btc_macro")}
        e = cal.evaluate(cand, ctx, table)
        pri.append(e["p_prior"]); pcal.append(e["p_cal"])
    return pri, pcal


def ab_report(df: pd.DataFrame) -> None:
    """결판 후보에서 prior vs 보정 P̂의 Brier·캘리브레이션·승률정렬을 비교."""
    dec = df[df["tb_win"].notna()].copy()
    print("\n■ A/B 그림자 평가 — prior vs 보정 P̂ (결판 후보 기준)")
    if dec.empty:
        print("  결판 후보 없음(경로 미성숙) — A/B 보류.")
        return

    # 그림자 필드 우선, 없으면 현 테이블로 재계산
    have_shadow = dec["p_cal"].notna().any() if "p_cal" in dec else False
    if have_shadow:
        d = dec[dec["p_cal"].notna() & dec["p_prior"].notna()].copy()
        src = "스냅샷 기록(p_prior/p_cal)"
    else:
        pri, pcal = _recompute_pcal(dec)
        dec = dec.assign(p_prior=pri, p_cal=pcal)
        d = dec[dec["p_cal"].notna() & dec["p_prior"].notna()].copy()
        src = "현 테이블 재계산(in-sample 주의)"

    if d.empty:
        print("  C/L/F·확률 결측으로 비교 불가.")
        return
    y = d["tb_win"].astype(float).values
    bp, bc = _brier(d["p_prior"].values, y), _brier(d["p_cal"].values, y)
    moved = int((abs(d["p_cal"] - d["p_prior"]) > 1e-4).sum())
    print(f"  소스: {src} | 결판 n={len(d)} | 보정이 prior와 달라진 후보 {moved}건")
    print(f"  실현승률={y.mean()*100:.1f}%  "
          f"mean p_prior={d['p_prior'].mean():.4f}  mean p_cal={d['p_cal'].mean():.4f}")
    print(f"  Brier(prior)={bp:.4f}   Brier(보정)={bc:.4f}   "
          f"Δ={bc - bp:+.4f} ({'보정 우위' if bc < bp else 'prior 우위' if bc > bp else '동률'})")
    print("  ⚠ Gate-Out 판정은 OOS(시간분할+72h embargo)·충분표본에서만 유효. "
          "현재는 표본 부족 — 인프라 검증용.")


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════

def run(rows: list, by_key: str = "setup", min_n: int = 1,
        fired_only: bool = False, funnel_only: bool = False,
        ab_only: bool = False) -> None:
    floor = 0.58
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
        import config
        floor = getattr(config, "WRF_WIN_FLOOR", 0.58)
    except Exception:
        pass

    df = lab.candidate_dataset(rows)
    print(_CAVEAT)
    if df.empty:
        print("\nWRF 후보(schema v3+경로) 표본 없음 — 측정할 발사 이력이 아직 없습니다.")
        return

    if ab_only:
        ab_report(df)
        return

    # 게이트 퍼널 (빈도 병목)
    print(f"\n■ 게이트 퍼널 (precond 통과 후 → 발사, W_floor={floor})")
    print("  precond 컷은 미기록(관측 불가). VETO/FLOOR/RR 순으로 귀속.\n")
    with pd.option_context("display.width", 200):
        print(gate_funnel(df).to_string(index=False))
    if funnel_only:
        return

    work = df[df["fire"].fillna(False)] if fired_only else df
    scope = "발사 후보만(실거래 근사)" if fired_only else "전체 precond 통과 후보"

    # 전체 성능
    print(f"\n■ 성능 요약 — {scope}")
    print(performance_table(work, [], min_n).to_string(index=False))

    # 그룹별 성능
    by = _PRESETS.get(by_key, [c.strip() for c in by_key.split(",") if c.strip()])
    if by:
        print(f"\n■ 그룹 성능 — by {by} (reliable = resolved ≥ {min_n})")
        tbl = performance_table(work, by, min_n)
        with pd.option_context("display.max_rows", 200, "display.width", 220):
            print(tbl.to_string(index=False))

    # 플로어 검증 메시지
    dec = work[work["tb_win"].notna()]
    if len(dec):
        wr = dec["tb_win"].mean()
        verdict = "충족" if wr >= floor else "미달"
        print(f"\n발사(또는 후보) 실현 승률 {wr*100:.1f}% vs 플로어 {floor*100:.0f}% → {verdict} "
              f"(결판 {len(dec)}건; 표본 부족 — 참고용).")
    else:
        print("\n결판난 후보 없음(경로 미성숙) — 성능 판정 보류.")


def main():
    ap = argparse.ArgumentParser(description="WRF Phase 1 백테스트/리플레이 하니스")
    ap.add_argument("--dir", default=None, help="research 데이터 디렉터리")
    ap.add_argument("--by", default="setup",
                    help="그룹: all|setup|macro|regime|cell|setup_macro 또는 컬럼명(쉼표)")
    ap.add_argument("--min-n", type=int, default=1, help="신뢰 표본(resolved) 컷")
    ap.add_argument("--fired-only", action="store_true", help="발사 후보만 집계")
    ap.add_argument("--funnel", action="store_true", help="게이트 퍼널만 출력")
    ap.add_argument("--ab", action="store_true",
                    help="[Phase 2] prior vs 보정 A/B(Brier/캘리브레이션)")
    args = ap.parse_args()

    rows = load_snapshots(args.dir) if args.dir else load_snapshots()
    run(rows, by_key=args.by, min_n=args.min_n,
        fired_only=args.fired_only, funnel_only=args.funnel, ab_only=args.ab)


if __name__ == "__main__":
    main()
