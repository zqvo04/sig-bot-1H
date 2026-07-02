"""BR 도입 + 반전형 C축 v2 백테스트 검증 (재현 가능·사전등록 판정).

저장된 반전 후보(MR/RV/BR)의 L/F/rr/tb_win/tb_r 은 그대로 두고, C축만 v1(macro echo)
vs v2(심볼-로컬 구조)로 재계산 → P̂ → 발사판정을 라이브 모듈(detectors._ctx_exhaustion,
calibration.prior_p_hat)로 재생한다. C축 버전은 오직 C→P̂→발사집합만 바꾸고 RR·veto·
경로결과(tb_win/tb_r)는 불변 → 저장 라벨 재사용이 정당한 A/B.

사전등록 판정(결과 보고 후 기준 변경 금지):
  [BR ON=섀도해제] 발사분 실현 win% ≥ 55 ∧ exp_R>0 ∧ PF>1
  [C v2 ON]        v1 대비 (a)Brier 비열등 ∧ (b)IC 비열등 ∧ (c)발사 exp_R 비열등
                   ∧ (d)발사빈도 ≥50% 유지

통계 주의: 누적이 DOWNLEG/CHOP 단일레짐·소표본 → 결론이 아니라 '점등 게이트'. fade
방향의 확증/반증은 UPLEG 관측 후에만. 재실행: `python analysis/audit/verify_br_caxis.py`
"""
import os
import sys
import math
from statistics import mean

sys.path.insert(0, "src")
sys.path.insert(0, "src/wrf")
sys.path.insert(0, "analysis")

import config
from wrf import detectors, calibration
from build_dataset import load_snapshots
import labels as lab

FLOOR = getattr(config, "WRF_WIN_FLOOR", 0.58)
EV_MIN = getattr(config, "WRF_EV_MIN", 0.15)
EV_RR_FLOOR = getattr(config, "WRF_EV_RR_FLOOR", 0.85)


def _nn(v):
    """pandas 경유 NaN → None (None/NaN 판정 단일화)."""
    try:
        return None if (v is None or v != v) else v
    except Exception:
        return v


def _fire_gate(phat, rr, veto_n):
    if phat < FLOOR or (veto_n or 0) > 0:
        return False
    ev = phat * rr - (1.0 - phat)
    return bool(ev >= EV_MIN and rr >= EV_RR_FLOOR)


def build(df, meta, version):
    """반전 후보에 C/P̂/fire 를 version(v1|v2)으로 재계산."""
    config.WRF_REV_CTX_V2 = (version == "v2")
    recs = []
    for _, r in df.iterrows():
        setup = r["setup"]
        if setup not in ("MR", "RV", "BR"):
            continue
        raw, ctx = meta.get(r["snapshot_id"], ({}, {}))
        L, F, rr = _nn(r.get("L")), _nn(r.get("F")), _nn(r.get("rr"))
        if L is None or F is None or rr is None:
            continue
        vn = int(_nn(r.get("veto_n")) or 0)
        C = detectors._ctx_exhaustion(ctx, raw, r["dir"])
        ph = calibration.prior_p_hat(setup, float(C), float(L), float(F))
        recs.append({"setup": setup, "dir": r["dir"], "ts": r["ts"], "C": C,
                     "phat": ph, "rr": float(rr), "veto_n": vn,
                     "fire": _fire_gate(ph, float(rr), vn),
                     "tb_win": _nn(r.get("tb_win")), "tb_r": _nn(r.get("tb_r"))})
    return recs


def perf(recs, fired_only=True):
    pop = [x for x in recs if x["fire"]] if fired_only else recs
    dec = [x for x in pop if x["tb_win"] is not None]
    rs = [float(x["tb_r"]) for x in pop if x["tb_r"] is not None]
    win = mean(x["tb_win"] for x in dec) if dec else None
    exp = mean(rs) if rs else None
    pos = sum(r for r in rs if r > 0)
    neg = -sum(r for r in rs if r < 0)
    pf = (pos / neg) if neg > 0 else (float("inf") if pos > 0 else None)
    return {"n": len(pop), "decided": len(dec),
            "win%": None if win is None else round(win * 100, 1),
            "exp_R": None if exp is None else round(exp, 3),
            "PF": None if pf is None else (round(pf, 2) if pf != float("inf") else "inf")}


def _spearman(pairs):
    n = len(pairs)
    if n < 3:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        rk = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            a = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                rk[order[k]] = a
            i = j + 1
        return rk

    rx, ry = ranks(xs), ranks(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n))
                    * sum((ry[i] - my) ** 2 for i in range(n)))
    return round(num / den, 3) if den else None


def brier(recs):
    dec = [x for x in recs if x["tb_win"] is not None]
    return round(mean((x["phat"] - x["tb_win"]) ** 2 for x in dec), 4) if dec else None


def ic(recs):
    return _spearman([(x["phat"], x["tb_win"]) for x in recs if x["tb_win"] is not None])


def main():
    rows = load_snapshots("data/research")
    df = lab.candidate_dataset(rows)   # rows in-place BR split
    meta = {r["snapshot_id"]: (r.get("raw") or {}, r.get("ctx") or {}) for r in rows}
    v1, v2 = build(df, meta, "v1"), build(df, meta, "v2")

    print("=" * 74)
    print(f"BR + 반전 C축 v2 검증  (floor={FLOOR} EV_MIN={EV_MIN} EV_RR_FLOOR={EV_RR_FLOOR})")
    print("  ⚠ DOWNLEG/CHOP 단일레짐·소표본 — 점등 게이트(결론 아님). fade 방향은 UPLEG 후 재검증.")
    print("=" * 74)

    # ① BR 도입 (라이브 발사 시 성능)
    br1 = perf([x for x in v1 if x["setup"] == "BR"])
    br2 = perf([x for x in v2 if x["setup"] == "BR"])
    print("\n【① BR 도입 — 섀도 해제(라이브 발사) 시 성능】")
    print(f"  v1 C축: 발사 {br1['n']} 결판 {br1['decided']} win%={br1['win%']} "
          f"exp_R={br1['exp_R']} PF={br1['PF']}")
    print(f"  v2 C축: 발사 {br2['n']} 결판 {br2['decided']} win%={br2['win%']} "
          f"exp_R={br2['exp_R']} PF={br2['PF']}  (C축이 BR을 구제하는가?)")
    br_ok = (br1["win%"] is not None and br1["win%"] >= 55 and br1["exp_R"] is not None
             and br1["exp_R"] > 0 and br1["PF"] not in (None,)
             and (br1["PF"] == "inf" or br1["PF"] > 1))
    print(f"  판정[win%≥55 ∧ exp_R>0 ∧ PF>1] → {'긍정(섀도 해제)' if br_ok else '부정(섀도 유지)'}")

    # ② 반전형 C축 v2 (전 반전 A/B)
    p1, p2 = perf(v1), perf(v2)
    b1, b2, i1, i2 = brier(v1), brier(v2), ic(v1), ic(v2)
    print("\n【② 반전형 C축 v2 — 전 반전(MR/RV/BR) A/B】")
    print(f"  v1: 발사 {p1['n']} 결판 {p1['decided']} win%={p1['win%']} exp_R={p1['exp_R']} "
          f"PF={p1['PF']} | Brier={b1} IC={i1}")
    print(f"  v2: 발사 {p2['n']} 결판 {p2['decided']} win%={p2['win%']} exp_R={p2['exp_R']} "
          f"PF={p2['PF']} | Brier={b2} IC={i2}")
    crit = {
        "Brier 비열등(v2≤v1)": (b2 is not None and b1 is not None and b2 <= b1 + 1e-9),
        "IC 비열등(v2≥v1)": (i2 is not None and i1 is not None and i2 >= i1 - 1e-9),
        "발사 exp_R 비열등": (p2["exp_R"] is not None and p1["exp_R"] is not None
                          and p2["exp_R"] >= p1["exp_R"] - 1e-9),
        "발사빈도 유지(≥50%)": (p1["n"] > 0 and p2["n"] >= 0.5 * p1["n"]),
    }
    for k, ok in crit.items():
        print(f"    {'✔' if ok else '✗'} {k}: {ok}")
    c_ok = all(crit.values())
    print(f"  판정 → {'긍정(ON)' if c_ok else '부정(OFF 유지 — IC↑이나 실현성능 미확증)'}")

    print("\n" + "=" * 74)
    print(f"최종: BR = {'라이브' if br_ok else '섀도 유지'}  ·  "
          f"C축 v2 = {'ON' if c_ok else 'OFF 유지'}")
    print("=" * 74)
    return br_ok, c_ok


if __name__ == "__main__":
    main()
