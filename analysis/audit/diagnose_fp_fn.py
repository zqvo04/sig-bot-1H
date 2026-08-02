"""diagnose_fp_fn.py — FP/FN 사전등록 진단 하니스 (오프라인 전용·측정만).

docs/DIAGNOSTIC_2026-08_FPFN.md 의 모든 수치를 재현한다. 라이브 코드는 건드리지 않는다.

핵심 질문 4개:
  Q1 현행 config 로 저장 후보를 재채점하면 무엇이 발사되고 무엇이 어느 게이트에 막히는가.
     (JSONL 의 fire 플래그는 '수집 당시' config 산물이라 현행 로직 진단에 쓸 수 없다.)
  Q2 FP: 발사집합의 실현 승률·avgR. 셋업×방향 어느 코호트가 손실을 만드는가.
  Q3 FN: 차단집합 중 WIN. 사유(VETO/격리/FLOOR/EV)별로 귀속하고, 코호트 단위
     기대값(승률 − 손익분기승률 1/(1+RR))으로 '정당한 차단'과 '구조적 FN'을 가른다.
  Q4 P̂ 이 순위정보를 갖는가 — 전체 AUC / 셋업내부 AUC / 셋업 base-rate AUC 분해.
     셋업내부 AUC ≈ 0.5 면 P̂ 은 사실상 '셋업 화이트리스트'다.

통계 주의: 매시간 후보는 t_max(24~72h) 윈도가 겹치는 자기상관 표본 → 유효 n ≪ 명목 n.
모든 수치는 방향성 증거이지 확증이 아니다. --stride 로 탈중첩 표본 재검을 함께 본다.

CLI:
  python analysis/audit/diagnose_fp_fn.py              # 전체 진단
  python analysis/audit/diagnose_fp_fn.py --geometry   # TP/SL 기하 스윕 추가(느림)
  python analysis/audit/diagnose_fp_fn.py --walkforward# 워크포워드 base-rate 대조 추가
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "analysis"))
sys.path.insert(0, os.path.join(_ROOT, "src"))
os.chdir(_ROOT)

import config  # noqa: E402
from wrf import calibration as cal  # noqa: E402
from build_dataset import load_snapshots  # noqa: E402
import labels as lab  # noqa: E402

_CAVEAT = (
    "─" * 72 + "\n"
    "⚠ 중첩표본(자기상관) — 유효 n ≪ 명목 n. 방향성 증거이지 통계적 확증이 아니다.\n"
    "  JSONL fire 플래그는 수집 당시 config 산물 → 현행 진단은 전부 '재채점' 기준.\n"
    + "─" * 72
)


def auc(y, s) -> float:
    """Mann-Whitney AUC. 결측 제외, 단일클래스면 nan."""
    t = pd.DataFrame({"y": y, "s": s}).dropna()
    if t["y"].nunique() < 2:
        return float("nan")
    r = t["s"].rank()
    n1 = int((t["y"] == 1).sum())
    n0 = int((t["y"] == 0).sum())
    return float((r[t["y"] == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def load_decided() -> pd.DataFrame:
    """후보 전량 → triple-barrier 결판분만."""
    rows = load_snapshots(os.path.join(_ROOT, "data", "research"))
    df = lab.candidate_dataset(rows)
    d = df[df["tb_outcome"].isin(["WIN", "LOSS"])].copy()
    d["win"] = (d["tb_outcome"] == "WIN").astype(int)
    d["half"] = np.where(d["ts"] < d["ts"].quantile(0.5), "H1", "H2")
    return d.reset_index(drop=True)


def rescore(d: pd.DataFrame) -> pd.DataFrame:
    """현행 config + 발행 테이블로 P̂·발사판정 재계산 → 게이트 귀속(reason)."""
    table = cal.load_table()
    shadow = getattr(config, "WRF_SHADOW_SETUPS", set())
    out = []
    for r in d.itertuples():
        pe = cal.evaluate({"setup": r.setup, "dir": getattr(r, "dir"),
                           "C": r.C, "L": r.L, "F": r.F},
                          {"regime_1h": r.regime_1h, "btc_macro": r.btc_macro}, table)
        p, fl = pe["p_hat"], pe["floor"]
        q = []
        if r.setup in shadow:
            q.append("SHADOW_SETUP")
        if getattr(config, "WRF_FIRE_RIGHTS_ENABLED", True) and pe.get("fire_rights") == "shadow":
            q.append("FIRE_RIGHTS")
        ev = p * r.rr - (1.0 - p)
        rr_ok = (ev >= getattr(config, "WRF_EV_MIN", 0.15)
                 and r.rr >= getattr(config, "WRF_EV_RR_FLOOR", 0.85))
        veto = r.veto_n > 0
        if veto:
            reason = "VETO"
        elif q:
            reason = "격리:" + q[0]
        elif p < fl:
            reason = "FLOOR"
        elif not rr_ok:
            reason = "EV/RR"
        else:
            reason = "FIRE"
        out.append({"p_new": p, "floor_new": fl, "reason": reason,
                    "fire_new": reason == "FIRE", "p_src": pe["source"]})
    return pd.concat([d, pd.DataFrame(out)], axis=1)


def _cohort(g: pd.DataFrame) -> pd.Series:
    """코호트 요약 — 승률·평균RR·손익분기승률·엣지."""
    be = 1.0 / (1.0 + g["rr"].mean())
    return pd.Series({"n": len(g), "wr": g["win"].mean(), "rr": g["rr"].mean(),
                      "be_wr": be, "edge": g["win"].mean() - be,
                      "sumR": g["tb_r"].sum(), "avgR": g["tb_r"].mean()})


def q0_live_timeline() -> None:
    """기록된 fire 플래그의 주간 추이 — 테이블 발행(prior 재적합) 전후 라이브 발사 변화."""
    rows = load_snapshots(os.path.join(_ROOT, "data", "research"))
    recs = []
    for r in rows:
        for c in r.get("candidates", []):
            recs.append({"ts": r["ts"], "setup": c["setup"], "fire": bool(c.get("fire")),
                         "p": c.get("p_hat")})
    t = pd.DataFrame(recs)
    t["ts"] = pd.to_datetime(t["ts"], utc=True)
    t["주"] = t["ts"].dt.strftime("%G-W%V")
    print("\n■ Q0. 라이브 발사 추이 (기록된 fire 플래그 — 수집 당시 config 기준)")
    print(t.groupby("주").agg(후보=("fire", "size"), 발사=("fire", "sum"),
                             P̂평균=("p", "mean")).round(3).to_string())
    gen = cal.load_table().get("generated_at")
    if gen:
        post = t[t["ts"] >= pd.to_datetime(gen, utc=True)]
        print(f"\n  보정테이블 발행({gen[:16]}) 이후: 후보 {len(post)}건 → 발사 "
              f"{int(post['fire'].sum())}건")


def q1_funnel(d: pd.DataFrame) -> None:
    print("\n■ Q1. 현행 config 재채점 — 게이트 퍼널")
    g = d.groupby("reason").apply(_cohort, include_groups=False)
    print(g.round(3).sort_values("n", ascending=False).to_string())
    print("\n  셋업별 P̂ 도달범위 vs 플로어 (플로어 초과 불가 = 구조적 FN)")
    s = d.groupby("setup").agg(n=("win", "size"), p_med=("p_new", "median"),
                               p_max=("p_new", "max"), floor=("floor_new", "median"),
                               fired=("fire_new", "sum"))
    s["도달가능"] = s["p_max"] >= s["floor"]
    print(s.round(3).to_string())


def q2_fp(d: pd.DataFrame) -> None:
    print("\n■ Q2. FP — 발사집합")
    f = d[d["fire_new"]]
    if f.empty:
        print("  발사 0건 (현행 로직은 이 표본에서 사실상 침묵).")
    else:
        print(_cohort(f).round(3).to_string())
        print(f.groupby(["setup", "dir"]).apply(_cohort, include_groups=False).round(3).to_string())
        print("\n  반기 분할:")
        print(f.groupby("half").apply(_cohort, include_groups=False).round(3).to_string())


def q3_fn(d: pd.DataFrame) -> None:
    print("\n■ Q3. FN — 차단집합의 코호트 기대값 (edge = wr − 1/(1+RR))")
    b = d[~d["fire_new"]]
    print(f"  차단 {len(b)}건 중 WIN {int(b['win'].sum())}건 (차단 승률 {b['win'].mean():.3f})")
    g = b.groupby(["reason", "setup", "dir"]).apply(_cohort, include_groups=False)
    g = g[g["n"] >= 5].sort_values("edge", ascending=False)
    print("\n  edge > 0 = 차단이 손해(구조적 FN) / edge < 0 = 차단이 정당")
    print(g.round(3).to_string())


def q4_discrimination(d: pd.DataFrame) -> None:
    print("\n■ Q4. P̂ 변별력 분해")
    print(f"  전체 AUC(P̂)          = {auc(d['win'], d['p_new']):.3f}")
    d = d.copy()
    d["p_within"] = d.groupby("setup")["p_new"].rank(pct=True)
    d["setup_base"] = d.groupby("setup")["win"].transform("mean")
    print(f"  셋업내부 AUC(P̂ 랭크) = {auc(d['win'], d['p_within']):.3f}   ← 0.5면 셋업 화이트리스트")
    print(f"  셋업 base-rate AUC   = {auc(d['win'], d['setup_base']):.3f}   ← 변별력의 실제 출처")
    print("\n  축 IC의 셋업 이질성 (n≥25) — 단일 pooled slope 가 표현 불가한 구조")
    for s, g in d.groupby("setup"):
        if len(g) >= 25:
            print(f"    {s:3s} n={len(g):3d} wr={g['win'].mean():.3f}  "
                  f"C={auc(g['win'], g['C']):.3f} L={auc(g['win'], g['L']):.3f} "
                  f"F={auc(g['win'], g['F']):.3f}")
    print("\n  반기 안정성 (부호가 뒤집히면 재적합은 잡음을 적합한 것)")
    for h, g in d.groupby("half"):
        print(f"    {h} n={len(g):3d} base={g['win'].mean():.3f}  " +
              "  ".join(f"{c}={auc(g['win'], g[c]):.3f}" for c in ("p_new", "C", "L", "F")))


def q5_refit_population(d: pd.DataFrame) -> None:
    """재적합 기울기가 학습 모집단·ridge 에 얼마나 좌우되는가(비식별성 점검)."""
    from calibrate import _prior_refit_fit  # noqa: E402
    print("\n■ Q5. prior 재적합 계수의 비식별성")
    shadow = getattr(config, "WRF_SHADOW_SETUPS", set())
    dd = d.drop(columns=["tb_win"]).rename(columns={"win": "tb_win"})
    dd = dd.dropna(subset=["C", "L", "F", "tb_win"])
    for name, sub in (("전량(현행 모집단)", dd),
                      ("비섀도만(발사가능)", dd[~dd["setup"].isin(shadow)])):
        if len(sub) < getattr(config, "WRF_PRIOR_REFIT_MIN_N", 40):
            continue
        fit = _prior_refit_fit(sub, getattr(config, "WRF_PRIOR_REFIT_RIDGE", 8.0))
        print(f"  {name:18s} n={len(sub):3d}  wC={fit['wC']:.3f} wL={fit['wL']:.3f} wF={fit['wF']:.3f}")
    print("  ridge 민감도(전량):")
    for ridge in (0.5, 2.0, 8.0, 32.0):
        fit = _prior_refit_fit(dd, ridge)
        print(f"    ridge={ridge:5.1f}  wC={fit['wC']:.3f} wL={fit['wL']:.3f} wF={fit['wF']:.3f}")


def q6_stride(d: pd.DataFrame, hours: int = 24) -> None:
    print(f"\n■ Q6. 탈중첩 독립표본 (stride {hours}h, (symbol,setup,dir) 별)")
    last: dict = {}
    keep = []
    for r in d.sort_values("ts").itertuples():
        k = (r.symbol, r.setup, getattr(r, "dir"))
        if k not in last or (r.ts - last[k]).total_seconds() >= hours * 3600:
            keep.append(r.Index)
            last[k] = r.ts
    ind = d.loc[keep]
    print(f"  n_indep={len(ind)} (명목 {len(d)})  전체 승률={ind['win'].mean():.3f}")
    print(ind.groupby("setup").apply(_cohort, include_groups=False).round(3).to_string())


def geometry_sweep() -> None:
    """같은 진입·방향에 TP/SL 배수만 바꿔 재채점 — FP가 기하 문제인지 방향 문제인지."""
    print("\n■ 부록. 기하 스윕 (sl_x = 현행 SL 배수, rr = TP/SL)")
    rows = lab.split_band_reversal(load_snapshots(os.path.join(_ROOT, "data", "research")))
    cands = []
    for r in rows:
        path = r.get("path")
        if not path or not path.get("c"):
            continue
        for c in r.get("candidates", []):
            e, tp, sl = c.get("entry"), c.get("tp"), c.get("sl")
            if e and tp and sl:
                cands.append((path, c["dir"], abs(e - sl) / e, c.get("t_max", 48), c["setup"]))
    shadow = getattr(config, "WRF_SHADOW_SETUPS", set())
    out = []
    for sl_x in (0.75, 1.0, 1.5, 2.0):
        for rr in (0.75, 1.0, 1.5, 2.0, 3.0):
            res = []
            for path, direction, slf, t_max, setup in cands:
                tb = lab.triple_barrier(path, direction, slf * sl_x, slf * sl_x * rr, t_max, True)
                if tb:
                    res.append({"setup": setup, "out": tb["outcome"], "r": tb["r_multiple"]})
            df = pd.DataFrame(res)
            ns = df[~df["setup"].isin(shadow)]
            ad = df[df["out"].isin(["WIN", "LOSS"])]
            nd = ns[ns["out"].isin(["WIN", "LOSS"])]
            out.append({"sl_x": sl_x, "rr": rr, "be_wr": 1 / (1 + rr),
                        "전체_wr": ad["out"].eq("WIN").mean() if len(ad) else np.nan,
                        "전체_avgR": df["r"].mean(),
                        "비섀도_n": len(nd),
                        "비섀도_wr": nd["out"].eq("WIN").mean() if len(nd) else np.nan,
                        "비섀도_avgR": ns["r"].mean()})
    o = pd.DataFrame(out)
    o["전체_edge"] = o["전체_wr"] - o["be_wr"]
    o["비섀도_edge"] = o["비섀도_wr"] - o["be_wr"]
    print(o.round(3).to_string(index=False))
    print("  → 전체 풀에서 전 격자 edge<0 이면 FP는 기하가 아니라 방향(진입) 문제다.\n"
          "     비섀도 풀의 edge 크기가 곧 '기하 재설계로 얻을 수 있는 상한'이다.")


def walkforward(d: pd.DataFrame) -> None:
    """시점 이전(+embargo) 결판만으로 추정한 (setup,dir) 수축승률의 변별력 — P̂ 대조군."""
    print("\n■ 부록. 워크포워드 (setup,dir) base-rate 대조 (look-ahead 없음)")
    k_shrink = 20.0
    emb = pd.Timedelta(hours=getattr(config, "WRF_EMBARGO_HOURS", 72))
    d = d.sort_values("ts").reset_index(drop=True)
    exit_ts = d["ts"] + pd.to_timedelta(d["tb_exit_h"].fillna(48), unit="h")
    p_wf = []
    for i, r in enumerate(d.itertuples()):
        hist = d[(exit_ts + emb) <= r.ts]
        if len(hist) < 30:
            p_wf.append(np.nan)
            continue
        glob = hist["win"].mean()
        hs = hist[hist["setup"] == r.setup]
        p_s = (hs["win"].sum() + k_shrink * glob) / (len(hs) + k_shrink)
        hsd = hs[hs["dir"] == getattr(r, "dir")]
        p_wf.append((hsd["win"].sum() + k_shrink * p_s) / (len(hsd) + k_shrink))
    d = d.assign(p_wf=p_wf).dropna(subset=["p_wf"])
    print(f"  평가 n={len(d)}  AUC(p_wf)={auc(d['win'], d['p_wf']):.3f}  "
          f"AUC(P̂ 현행)={auc(d['win'], d['p_new']):.3f}")
    for h, g in d.groupby("half"):
        print(f"    {h}: AUC(p_wf)={auc(g['win'], g['p_wf']):.3f}  "
              f"AUC(P̂)={auc(g['win'], g['p_new']):.3f}  base={g['win'].mean():.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--geometry", action="store_true", help="TP/SL 기하 스윕(느림)")
    ap.add_argument("--walkforward", action="store_true", help="워크포워드 base-rate 대조")
    ap.add_argument("--stride", type=int, default=24, help="탈중첩 독립표본 간격(시간)")
    args = ap.parse_args()

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)
    print(_CAVEAT)

    d = load_decided()
    print(f"\n결판 후보 {len(d)}건 · {d['ts'].min():%Y-%m-%d} ~ {d['ts'].max():%Y-%m-%d} · "
          f"전체 승률 {d['win'].mean():.3f} · 평균RR {d['rr'].mean():.2f} "
          f"(손익분기 승률 {1 / (1 + d['rr'].mean()):.3f})")

    q0_live_timeline()
    d = rescore(d)
    q1_funnel(d)
    q2_fp(d)
    q3_fn(d)
    q4_discrimination(d)
    q5_refit_population(d)
    q6_stride(d, args.stride)
    if args.walkforward:
        walkforward(d)
    if args.geometry:
        geometry_sweep()


if __name__ == "__main__":
    main()
