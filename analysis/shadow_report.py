"""shadow_report.py — 트랙1(라이브 발사) vs 트랙2(D-shadow) 스코어보드 + 승격 게이트.

D-shadow(섀도 전용)가 라이브 발사 대비 false-negative를 실제로 회수하는지, 그러면서
false-positive를 관리하는지 데이터로 대조하고, '언제 라이브로 승격할지'를 즉흥이 아니라
명시적 규칙으로 판정한다(공통 거버넌스). 저장 후보 + 72h 경로(triple-barrier) 재생 기준.

트랙 정의(JSONL 후보 플래그):
  · live    : fire=True           (실제 발사 — 트랙1)
  · shadow  : d_shadow=True        (D 트리거 무장 — 트랙2 전량)
  · logged  : d_shadow ∧ shadow_logged=True  (쿨다운 통과 = 실제 '(shadow)' 기록분)

승격 게이트(전부 충족 시 해당 '방향' PROMOTE-READY):
  ① 독립표본(24h stride 탈중첩) 결판 ≥ MIN_INDEP
  ② 섀도(logged) 승률 ≥ 라이브 승률 + MARGIN  그리고  ≥ 플로어(W_floor)
  ③ 섀도 기대R > 0
  ④ ≥ MIN_MACRO 종의 거시레짐(btc_macro) 커버 (단일레짐 과적합 차단)
표본 부족/단일레짐이면 HOLD — 현재 누적은 대개 HOLD(정상).

CLI:
  python analysis/shadow_report.py                 # 트랙×방향 + 레짐 + 승격판정
  python analysis/shadow_report.py --by macro      # 거시레짐별
  python analysis/shadow_report.py --min-indep 20 --margin 0.0
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
    "─" * 70 + "\n"
    "⚠ 섀도 스코어보드: 매시간 표본은 72h 중첩(자기상관) → 유효 n ≪ 명목 n.\n"
    "  · 승격 게이트의 '결판'은 24h stride 탈중첩 독립표본 기준(정직).\n"
    "  · 섀도는 발사·손익 무관 — 본 보고서는 '승격 가치' 측정 도구다.\n"
    + "─" * 70
)


def _tb(path, c):
    e, tp, sl = c.get("entry"), c.get("tp"), c.get("sl")
    if not path or not path.get("c") or not e or not tp or not sl:
        return None
    return lab.triple_barrier(path, c["dir"], abs(e - sl) / e, abs(tp - e) / e,
                              c.get("t_max", 48))


def collect(rows: list) -> pd.DataFrame:
    """라이브/섀도 후보 → 경로라벨 long-format."""
    recs = []
    for r in rows:
        path = r.get("path")
        ctx = r.get("ctx") or {}
        for c in r.get("candidates", []):
            if c.get("fire"):
                track = "live"
            elif c.get("d_shadow"):
                track = "shadow"
            else:
                continue
            tb = _tb(path, c) or {}
            recs.append({
                "ts": r.get("ts"), "symbol": r.get("symbol"), "dir": c.get("dir"),
                "track": track, "setup": c.get("setup"),
                "regime_1h": ctx.get("regime_1h"), "btc_macro": ctx.get("btc_macro"),
                "logged": bool(c.get("shadow_logged")),
                "win": tb.get("tb_win"), "r": tb.get("r_multiple"),
                "outcome": tb.get("outcome"),
            })
    df = pd.DataFrame(recs)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df = df.sort_values("ts").reset_index(drop=True)
    return df


def _indep(df: pd.DataFrame, stride_h: int = 24) -> pd.DataFrame:
    """(symbol,dir,track)별 24h stride 탈중첩 — 자기상관 완화 독립표본."""
    keep = []
    for _, g in df.groupby(["symbol", "dir", "track"]):
        last = None
        for _, row in g.sort_values("ts").iterrows():
            if last is None or (row["ts"] - last) >= pd.Timedelta(hours=stride_h):
                keep.append(row)
                last = row["ts"]
    return pd.DataFrame(keep) if keep else df.iloc[0:0]


def _metrics(g: pd.DataFrame) -> dict:
    dec = g[g["win"].notna()]
    res = g[g["r"].notna()]
    rr = res["r"].astype(float)
    pos, neg = rr[rr > 0].sum(), -rr[rr < 0].sum()
    return {
        "n": len(g), "decided": len(dec),
        "win%": round(dec["win"].mean() * 100, 1) if len(dec) else None,
        "expR": round(rr.mean(), 3) if len(res) else None,
        "PF": (round(pos / neg, 2) if neg > 0 else float("inf")) if len(res) else None,
    }


def table(df: pd.DataFrame, by: list) -> pd.DataFrame:
    out = []
    for keys, g in df.groupby(by):
        keys = keys if isinstance(keys, tuple) else (keys,)
        rec = dict(zip(by, keys))
        rec.update(_metrics(g))
        out.append(rec)
    return pd.DataFrame(out)


def promotion(df: pd.DataFrame, floor: float, min_indep: int,
              margin: float, min_macro: int) -> None:
    print(f"\n■ 승격 게이트 (독립표본 결판≥{min_indep} · 섀도승률≥라이브+{margin:.0%}"
          f" 且 ≥{floor:.0%} · expR>0 · 거시≥{min_macro}종)")
    indep = _indep(df)
    for direction in ("long", "short"):
        live = indep[(indep["track"] == "live") & (indep["dir"] == direction)]
        shad = indep[(indep["track"] == "shadow") & (indep["dir"] == direction) & (indep["logged"])]
        sm = _metrics(shad)
        lm = _metrics(live)
        n_macro = shad["btc_macro"].nunique()
        sw = (sm["win%"] or 0) / 100.0
        lw = (lm["win%"] or 0) / 100.0
        checks = {
            "독립결판": sm["decided"] >= min_indep,
            "승률우위": sm["win%"] is not None and sw >= lw + margin and sw >= floor,
            "기대R>0": (sm["expR"] or -1) > 0,
            f"거시≥{min_macro}": n_macro >= min_macro,
        }
        verdict = "PROMOTE-READY" if all(checks.values()) else "HOLD"
        detail = ", ".join(f"{k}:{'✓' if v else '✗'}" for k, v in checks.items())
        print(f"  [{direction:<5}] {verdict}  (섀도 독립결판 {sm['decided']}, "
              f"승률 {sm['win%']}% vs 라이브 {lm['win%']}%, expR {sm['expR']}, "
              f"거시 {n_macro}종) | {detail}")
    print("  ※ 승격 = 라이브 게이트 완화/보정(δ) 반영 결정의 '근거'. 코드 자동전환 아님(사람이 결정).")


def main():
    ap = argparse.ArgumentParser(description="D-shadow vs 라이브 스코어보드/승격 게이트")
    ap.add_argument("--dir", default=None, help="research 데이터 디렉터리")
    ap.add_argument("--by", default="dir", help="dir|macro|regime|setup")
    ap.add_argument("--min-indep", type=int, default=20)
    ap.add_argument("--margin", type=float, default=0.0)
    ap.add_argument("--min-macro", type=int, default=2)
    args = ap.parse_args()

    floor = 0.58
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
        import config
        floor = getattr(config, "WRF_WIN_FLOOR", 0.58)
    except Exception:
        pass

    rows = load_snapshots(args.dir) if args.dir else load_snapshots()
    df = collect(rows)
    print(_CAVEAT)
    if df.empty:
        print("\n라이브/섀도 후보(경로 보유) 표본 없음 — 측정할 이력이 아직 없습니다.")
        return

    print(f"\n■ 트랙×방향 (전체 후보, 중첩 포함)")
    t = table(df, ["track", "dir"]).sort_values(["track", "dir"])
    print(t.to_string(index=False))

    # logged(쿨다운 통과=실제 기록분)만 따로
    lg = df[(df["track"] == "live") | (df["logged"])]
    print(f"\n■ 실제 기록분만 (live + shadow_logged)")
    print(table(lg, ["track", "dir"]).sort_values(["track", "dir"]).to_string(index=False))

    key = {"dir": ["dir"], "macro": ["track", "btc_macro"], "regime": ["track", "regime_1h"],
           "setup": ["track", "setup"]}.get(args.by, ["track", "dir"])
    if args.by in ("macro", "regime", "setup"):
        print(f"\n■ {args.by}별")
        with pd.option_context("display.width", 200):
            print(table(df, key).to_string(index=False))

    promotion(df, floor, args.min_indep, args.margin, args.min_macro)


if __name__ == "__main__":
    main()
