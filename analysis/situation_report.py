"""
situation_report.py — 상황(지문)별 경로 분포 리포트 (오프라인 전용)
────────────────────────────────────────────────────────────────────
"이런 상황(레짐·바이어스·RSI존 등)에서 이후 차트가 어떻게 움직였나"를
지문(fp.key) 또는 굵은 차원(regime_1h×regime_4h×bias_1d)으로 묶어 집계한다.

출력:
  · 셀별 n, 24h/72h 수익률 분위수, MFE/MAE 중앙값, 경로효율, UP/DOWN 비율
  · (옵션) 간단한 TP/SL 재생 승률·기대값 — 봇 현행 R 기하 검증용

통계 주의(LEARNING_DATA_DESIGN.md §4) — 리포트 머리말에 항상 출력:
  · 매시간 표본은 72h 윈도가 겹치는 자기상관 표본 → 유효 n ≪ 명목 n
  · 셀 최소 표본(기본 n≥30) 미만은 '참고'로만, 결론 금지
  · 다중 비교(수백 셀)로 우연한 '성배'가 반드시 나옴 → out-of-sample 재검증 필수

CLI:
  python analysis/situation_report.py                    # regime_1h×regime_4h×bias_1d
  python analysis/situation_report.py --by key           # 전체 지문 키
  python analysis/situation_report.py --by fp_regime_1h  # 단일 차원
  python analysis/situation_report.py --sim long --tp 0.036 --sl 0.02
"""
from __future__ import annotations

import argparse

import pandas as pd

from build_dataset import (
    load_snapshots, to_dataframe, simulate_tp_sl,
)

_CAVEAT = (
    "─" * 64 + "\n"
    "⚠ 통계 주의(§4): 매시간 표본은 72h 윈도 중첩(자기상관) → 유효 n ≪ 명목 n.\n"
    "  · 셀 최소 표본 미만(--min-n, 기본 30)은 참고용. 결론·실거래 반영 금지.\n"
    "  · 수백 셀 다중비교 → 우연한 성배 발생. 반드시 out-of-sample 재검증.\n"
    "  · train/test는 시간순 분할 + 72h embargo(purged CV). 무작위 분할 금지.\n"
    + "─" * 64
)

_GROUP_PRESETS = {
    "coarse": ["fp_regime_1h", "fp_regime_4h", "fp_bias_1d"],
    "key": ["fp_key"],
    "regime": ["fp_regime_1h", "fp_regime_4h"],
}


def _q(s: pd.Series, q: float):
    return s.quantile(q) * 100.0 if s.notna().any() else float("nan")


def _frac(s: pd.Series, cond) -> float:
    v = s.dropna()
    return (cond(v).mean() * 100.0) if len(v) else float("nan")


def situation_table(df: pd.DataFrame, by: list[str], min_n: int = 30,
                    sim: str = None, tp: float = 0.036, sl: float = 0.02,
                    rows_with_path=None) -> pd.DataFrame:
    lab = df[df["ret_24h"].notna()].copy() if "ret_24h" in df else df.iloc[0:0].copy()
    if lab.empty:
        return lab

    out = []
    for keys, g in lab.groupby(by):
        keys = keys if isinstance(keys, tuple) else (keys,)
        rec = dict(zip(by, keys))
        rec["n"] = len(g)
        rec["ret24_med"] = round(g["ret_24h"].median() * 100, 3)
        rec["ret72_med"] = round(_q(g["ret_72h"], 0.5), 3) if "ret_72h" in g else None
        rec["ret24_p25"] = round(_q(g["ret_24h"], 0.25), 3)
        rec["ret24_p75"] = round(_q(g["ret_24h"], 0.75), 3)
        rec["mfe72_med"] = round(g["mfe_72h"].median() * 100, 3) if "mfe_72h" in g else None
        rec["mae72_med"] = round(g["mae_72h"].median() * 100, 3) if "mae_72h" in g else None
        rec["patheff_med"] = round(g["path_eff"].median(), 3) if "path_eff" in g else None
        rec["up24_%"] = round(_frac(g["ret_24h"], lambda v: v > 0), 1)

        if sim and rows_with_path is not None:
            sims = [rows_with_path.get(sid) for sid in g["snapshot_id"]]
            res = [simulate_tp_sl(p, sim, sl, tp) for p in sims if p]
            res = [x for x in res if x]
            if res:
                wins = sum(1 for x in res if x["result"] == "WIN")
                rec["sim_n"] = len(res)
                rec["sim_win%"] = round(wins / len(res) * 100, 1)
                rec["sim_exp_R"] = round(sum(x["r_multiple"] for x in res) / len(res), 3)
        out.append(rec)

    res_df = pd.DataFrame(out).sort_values("n", ascending=False).reset_index(drop=True)
    res_df["reliable"] = res_df["n"] >= min_n
    return res_df


def main():
    ap = argparse.ArgumentParser(description="상황별 경로 분포 리포트")
    ap.add_argument("--dir", default=None, help="research 데이터 디렉터리")
    ap.add_argument("--by", default="coarse",
                    help="그룹 기준: coarse|key|regime 프리셋 또는 fp_* 컬럼명(쉼표구분)")
    ap.add_argument("--min-n", type=int, default=30, help="신뢰 셀 최소 표본")
    ap.add_argument("--sim", choices=["long", "short"], help="TP/SL 재생 방향")
    ap.add_argument("--tp", type=float, default=0.036, help="익절 거리(비율)")
    ap.add_argument("--sl", type=float, default=0.020, help="손절 거리(비율)")
    args = ap.parse_args()

    rows = load_snapshots(args.dir) if args.dir else load_snapshots()
    df = to_dataframe(rows, min_n=4)

    print(_CAVEAT)
    if df.empty or ("ret_24h" in df and not df["ret_24h"].notna().any()):
        print("\n라벨 가능한 표본이 아직 없습니다(경로 미성숙). "
              "스냅샷 후 최소 24h 경과분이 필요합니다.")
        return

    by = _GROUP_PRESETS.get(args.by, [c.strip() for c in args.by.split(",")])
    by = [c for c in by if c in df.columns]
    if not by:
        print(f"\n유효한 그룹 컬럼 없음: {args.by}")
        return

    rows_with_path = None
    if args.sim:
        rows_with_path = {r.get("snapshot_id"): r.get("path")
                          for r in rows if r.get("path")}

    table = situation_table(df, by, min_n=args.min_n,
                            sim=args.sim, tp=args.tp, sl=args.sl,
                            rows_with_path=rows_with_path)
    print(f"\n그룹 기준: {by} | 신뢰 최소 n={args.min_n}\n")
    if table.empty:
        print("집계 표본 없음.")
        return
    with pd.option_context("display.max_rows", 200, "display.width", 200):
        print(table.to_string(index=False))

    rel = table[table["reliable"]]
    print(f"\n신뢰 셀(n≥{args.min_n}): {len(rel)} / 전체 {len(table)} 셀")
    if args.sim and "sim_exp_R" in table:
        print(f"TP/SL 재생: {args.sim.upper()} tp={args.tp:.3f} sl={args.sl:.3f} "
              f"(R={args.tp / args.sl:.2f}) — sim_exp_R는 기대 R배수")


if __name__ == "__main__":
    main()
