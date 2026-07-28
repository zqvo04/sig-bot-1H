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
  python analysis/backtest.py --playbook       # 실행플랜 진단(fired-only OOS 기준)
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


def _oos_split(df: pd.DataFrame, test_ratio: float = 0.3, embargo_h: int = 72):
    """시간순 train/OOS 분할(+embargo). 비어 있으면 원본 반환."""
    if df.empty or "ts" not in df.columns:
        return df, df.iloc[0:0].copy(), {"cut_ts": None, "embargo_h": embargo_h}
    d = df[df["ts"].notna()].sort_values("ts").reset_index(drop=True)
    if len(d) < 2:
        return d, d.iloc[0:0].copy(), {"cut_ts": None, "embargo_h": embargo_h}
    ratio = min(0.9, max(0.1, float(test_ratio)))
    cut = int(len(d) * (1.0 - ratio))
    cut = min(len(d) - 1, max(1, cut))
    cut_ts = d["ts"].iloc[cut - 1]
    emb = pd.Timedelta(hours=max(0, int(embargo_h)))
    train = d[d["ts"] <= cut_ts - emb].copy()
    oos = d[d["ts"] >= cut_ts + emb].copy()
    # 데이터가 매우 적어 embargo로 비면, 분할은 유지하되 embargo만 완화.
    if train.empty or oos.empty:
        train = d.iloc[:cut].copy()
        oos = d.iloc[cut:].copy()
    return train, oos, {"cut_ts": cut_ts, "embargo_h": int(embargo_h)}


def _cell_loss_tables(decided_fired: pd.DataFrame, floor: float, min_decided: int = 8):
    """셀×방향 손실 식별(신뢰/관찰 분리)."""
    if decided_fired.empty:
        z = decided_fired.iloc[0:0].copy()
        return z, z
    recs = []
    keys = ["cell", "setup", "regime_1h", "btc_macro", "dir"]
    for ks, g in decided_fired.groupby(keys):
        c, s, r, m, d = ks
        n = int(len(g))
        wr = float(g["tb_win"].mean())
        rs = g["tb_r"].dropna().astype(float)
        recs.append({
            "cell": c, "setup": s, "regime_1h": r, "btc_macro": m, "dir": d,
            "decided": n, "win%": round(wr * 100, 1),
            "exp_R": round(float(rs.mean()), 3) if len(rs) else None,
            "reliable": bool(n >= min_decided),
            "status": "LOSING" if (n >= min_decided and wr < floor) else ("OBSERVE" if n < min_decided else "OK"),
        })
    t = pd.DataFrame(recs).sort_values(["status", "decided"], ascending=[True, False]).reset_index(drop=True)
    losers = t[t["status"] == "LOSING"].sort_values(["win%", "decided"], ascending=[True, False]).reset_index(drop=True)
    observe = t[t["status"] == "OBSERVE"].sort_values("decided", ascending=False).reset_index(drop=True)
    return losers, observe


def _coverage_table(df: pd.DataFrame) -> pd.DataFrame:
    """거시/방향 커버리지 진단."""
    if df.empty:
        return df
    out = []
    for (m, d), g in df.groupby(["btc_macro", "dir"]):
        dec = g[g["tb_win"].notna()]
        out.append({
            "btc_macro": m, "dir": d, "n": len(g),
            "decided": len(dec),
            "win%": round(dec["tb_win"].mean() * 100, 1) if len(dec) else None,
        })
    return pd.DataFrame(out).sort_values(["btc_macro", "dir"]).reset_index(drop=True)


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


def _ab_metrics(df: pd.DataFrame):
    """A/B 비교 핵심 수치(dict). 비교 불가면 None."""
    dec = df[df["tb_win"].notna()].copy()
    if dec.empty:
        return None
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
        return None
    y = d["tb_win"].astype(float).values
    bp, bc = _brier(d["p_prior"].values, y), _brier(d["p_cal"].values, y)
    moved = int((abs(d["p_cal"] - d["p_prior"]) > 1e-4).sum())
    return {
        "source": src, "n": len(d), "moved": moved,
        "win_rate": float(y.mean()),
        "p_prior_mean": float(d["p_prior"].mean()),
        "p_cal_mean": float(d["p_cal"].mean()),
        "brier_prior": float(bp), "brier_cal": float(bc),
    }


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
    print("\n■ A/B 그림자 평가 — prior vs 보정 P̂ (결판 후보 기준)")
    m = _ab_metrics(df)
    if not m:
        print("  결판 후보 없음(경로 미성숙) — A/B 보류.")
        return
    bp, bc = m["brier_prior"], m["brier_cal"]
    print(f"  소스: {m['source']} | 결판 n={m['n']} | 보정이 prior와 달라진 후보 {m['moved']}건")
    print(f"  실현승률={m['win_rate']*100:.1f}%  mean p_prior={m['p_prior_mean']:.4f}  mean p_cal={m['p_cal_mean']:.4f}")
    print(f"  Brier(prior)={bp:.4f}   Brier(보정)={bc:.4f}   "
          f"Δ={bc - bp:+.4f} ({'보정 우위' if bc < bp else 'prior 우위' if bc > bp else '동률'})")
    print("  ⚠ Gate-Out 판정은 OOS(시간분할+72h embargo)·충분표본에서만 유효. "
          "현재는 표본 부족 — 인프라 검증용.")


def playbook_report(df: pd.DataFrame, floor: float, min_n: int,
                    oos_ratio: float, oos_embargo_h: int, calib_gate_min_decided: int) -> None:
    """승률 개선 실행 플랜 진단 리포트(라이브 무수정·오프라인 측정 전용)."""
    fired = df[df["fire"].fillna(False)].copy()
    train, oos, meta = _oos_split(fired, test_ratio=oos_ratio, embargo_h=oos_embargo_h)
    print("\n■ 실행 플랜 리포트 (fired-only OOS 기준)")
    print(f"  fired 총 {len(fired)}건 | train {len(train)}건 / OOS {len(oos)}건"
          f" | cut={meta.get('cut_ts')} | embargo={meta.get('embargo_h')}h")

    if oos.empty:
        print("  OOS 표본 0건 — 시간 누적 후 재측정 필요.")
        return

    dec_oos = oos[oos["tb_win"].notna()].copy()
    print("\n[1] 승률 목표 고정: fired-only OOS 성능")
    print(performance_table(oos, [], min_n).to_string(index=False))
    for by in (["setup"], ["btc_macro"], ["dir"]):
        print(f"\n  - by {by}")
        with pd.option_context("display.max_rows", 200, "display.width", 220):
            print(performance_table(oos, by, min_n).to_string(index=False))

    print("\n[2] 셀×방향 손실 식별")
    losers, observe = _cell_loss_tables(dec_oos, floor=floor, min_decided=min_n)
    if losers.empty:
        print("  신뢰표본 기준(결판≥min_n) floor 미달 셀 없음.")
    else:
        with pd.option_context("display.max_rows", 200, "display.width", 240):
            print(losers.to_string(index=False))
    print("\n  관찰대기 셀(저표본):")
    if observe.empty:
        print("  없음")
    else:
        with pd.option_context("display.max_rows", 60, "display.width", 240):
            print(observe.head(20).to_string(index=False))

    print("\n[3] 커버리지 진단 (거시×방향)")
    cov = _coverage_table(oos)
    if cov.empty:
        print("  커버리지 표본 없음.")
    else:
        with pd.option_context("display.max_rows", 200, "display.width", 220):
            print(cov.to_string(index=False))
        up = cov[cov["btc_macro"] == "UPLEG"]["decided"].fillna(0).sum()
        if up <= 0:
            print("  ⚠ UPLEG 결판 0건: 롱측 승률 판단 왜곡 가능(커버리지 우선 보강).")

    print("\n[4] 보수 운영 가이드")
    if not losers.empty:
        print("  · floor 미달 신뢰 셀은 fire_rights/shadow 보수 유지(상위 스위치 해제 보류).")
    else:
        print("  · 신뢰 셀 기준 즉시 강등 대상은 없음(현 상태 유지).")
    if not observe.empty:
        print("  · 저표본 셀은 개선 확정 금지, 관찰대기 유지.")

    print("\n[5] 보정 실전 반영 Gate-Out 점검")
    m = _ab_metrics(df)
    if not m:
        print("  · A/B 비교 불가: 결판/확률 표본 부족 → WRF_CALIB_DISABLED=true 유지 권고.")
        return
    delta = m["brier_cal"] - m["brier_prior"]
    print(f"  · A/B n={m['n']} | Brier Δ(보정-prior)={delta:+.4f}")
    if m["n"] < calib_gate_min_decided or delta >= 0:
        print("  · 우위 불충분/불안정: prior 발사 + 보정 그림자 기록 유지 권고.")
    else:
        print("  · 보정 우위 신호: 반복 OOS 검증 누적 후 WRF_CALIB_DISABLED 해제 검토.")


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════

def run(rows: list, by_key: str = "setup", min_n: int = 1,
        fired_only: bool = False, funnel_only: bool = False,
        ab_only: bool = False, playbook_only: bool = False,
        oos_ratio: float = 0.3, oos_embargo_h: int = 72,
        calib_gate_min_decided: int = 30) -> None:
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

    if playbook_only:
        playbook_report(df, floor=floor, min_n=min_n, oos_ratio=oos_ratio,
                        oos_embargo_h=oos_embargo_h,
                        calib_gate_min_decided=calib_gate_min_decided)
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
    ap.add_argument("--playbook", action="store_true",
                    help="승률 개선 실행플랜 진단(fired-only OOS·손실셀·커버리지·Gate-Out)")
    ap.add_argument("--oos-ratio", type=float, default=0.3,
                    help="playbook OOS 비중(시간순 분할)")
    ap.add_argument("--oos-embargo-h", type=int, default=72,
                    help="playbook train/OOS 사이 embargo 시간")
    ap.add_argument("--calib-gate-min-decided", type=int, default=30,
                    help="보정 Gate-Out 최소 결판 표본")
    args = ap.parse_args()

    rows = load_snapshots(args.dir) if args.dir else load_snapshots()
    run(rows, by_key=args.by, min_n=args.min_n,
        fired_only=args.fired_only, funnel_only=args.funnel, ab_only=args.ab,
        playbook_only=args.playbook, oos_ratio=args.oos_ratio,
        oos_embargo_h=args.oos_embargo_h,
        calib_gate_min_decided=args.calib_gate_min_decided)


if __name__ == "__main__":
    main()
