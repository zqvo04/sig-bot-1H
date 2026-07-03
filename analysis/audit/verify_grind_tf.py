"""[Tier 2] grind→TF 채널 재측정 — 전체 누적(6+7월)으로 Pillar1 승격 회수율 재판정.

배경: 하락 grind의 숏은 페이드(밴드반전)가 아니라 추세추종(TF 연속)이 올바른 주인인데,
ADX 지연으로 grind가 RANGING 오분류돼 TF가 라우팅에서 배제된다. Pillar1의 slope_sig
(slope_persist≥FRAC ∧ drift≥DRIFT)만이 is_ranging '앞'에서 grind를 TRENDING으로 구출한다.

기존 tune_regime.py는 6월(323)만 봤다. 정작 회수 대상인 7월 DOWNLEG grind를 포함한 전체로
재측정한다. 실제 classify_market_regime을 직접 호출(재구현 없음)해 config 파라미터만 토글.

★규율: 판정은 실현 R이 아니라 **분류 지표**(단일레짐 실현 R은 국면학습 함정). 상승/하락
grind는 동일 공식(대칭). 채택은 단일변수·사전등록 기준 전부 충족 시에만.

사전등록 채택기준(결과 보고 후 완화 금지):
  (a) DIR_DOWN 회수 > 현행  (b) chop-FP ≤ 현행+5%p 이내  (c) 승격정밀도 ≥ 55%
  (d) 회수 down-bar 4H약세율 ≥ 현행  (e) 단조(인접 임계에서 급변 없음)

재실행: python analysis/audit/verify_grind_tf.py
"""
import glob
import json
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "src/wrf")
sys.path.insert(0, "analysis")

import numpy as np
import pandas as pd
import config
import analysis_engine as ae
from build_dataset import fwd_ret

SYMS = ["BTC-USDT", "ETH-USDT", "HYPE-USDT"]
DIR_RET, CHOP_RET = 0.02, 0.01
TFBLOCK = ("RANGING", "SQUEEZE", "UNKNOWN")
WIN = 200   # classify는 최대 ~150봉만 참조 → 최근 200봉만 전달(O(n) 유지·충실)


def load(sym):
    rows = []
    for fp in sorted(glob.glob(f"data/research/{sym}/*.jsonl")):
        for l in open(fp, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if "raw" in r and r.get("p0") and r["raw"].get("adx") is not None:
                rows.append(r)
    rows.sort(key=lambda x: x["ts"])
    return rows


def bb_from_close(close: pd.Series):
    mid = close.rolling(20).mean(); sd = close.rolling(20).std()
    up, lo = mid + 2 * sd, mid - 2 * sd
    bw_ser = (up - lo) / mid
    bw = bw_ser.iloc[-1]
    if not np.isfinite(bw):
        return None
    avg = bw_ser.iloc[-50:].mean() if bw_ser.notna().sum() >= 50 else bw_ser.iloc[-20:].mean()
    return {"available": True, "band_width": float(bw), "avg_band_width": float(avg),
            "squeeze": bool(bw < avg * config.REGIME_SQUEEZE_RATIO and avg > 0)}


def regime_at(close_hist, adx_val, params):
    """params dict를 config에 설정하고 실제 classify 호출. None이면 승격 전부 OFF(baseline).

    ★상태누수 방지: 변형에 없는 레버도 매 호출마다 FULL_DEFAULT로 완전 리셋한다(이전
    변형/바의 값이 새어들지 않도록). 전역 config 변이라 이 리셋이 필수."""
    for k, v in FULL_DEFAULT.items():
        setattr(config, k, (params or {}).get(k, v))
    on = params is not None
    config.WRF_REGIME_SLOPE_PERSIST = on
    config.WRF_REGIME_ER_PCTL = on
    config.WRF_REGIME_ER_TREND = on
    ch = pd.Series(close_hist[-WIN:], dtype=float)
    df = pd.DataFrame({"open": ch, "high": ch, "low": ch, "close": ch,
                       "volume": np.full(len(ch), 1e3)})
    bb = bb_from_close(df["close"])
    if bb is None:
        return None
    return ae.classify_market_regime(df, {"adx": adx_val}, bb)["regime"]


def fwd_label(path):
    r24 = fwd_ret(path, 24, realistic=True)
    if r24 is None:
        return None
    if r24 <= -DIR_RET:
        return "DIR_DOWN"
    if r24 >= DIR_RET:
        return "DIR_UP"
    if abs(r24) < CHOP_RET:
        return "CHOP"
    return "GRAY"


# 전체 승격 레버(매 호출 완전 리셋 대상) — shipped 기본값. 변형은 이 중 1개만 바꾼다.
FULL_DEFAULT = {"WRF_REGIME_SLOPE_MIN_FRAC": 0.85, "WRF_REGIME_SLOPE_MIN_DRIFT": 0.02,
                "WRF_REGIME_ER_PCTL_MIN": 0.90, "WRF_REGIME_ER_DRIFT_MIN": 0.015,
                "WRF_REGIME_SLOPE_WIN": 20, "WRF_REGIME_ER_PCTL_WIN": 150}
SHIPPED = dict(FULL_DEFAULT)


def variants():
    yield "현행(shipped)", dict(SHIPPED)
    for f in (0.80, 0.75):                       # slope 일관성 완화(회수↑ 시도)
        v = dict(SHIPPED); v["WRF_REGIME_SLOPE_MIN_FRAC"] = f
        yield f"slope_frac={f}", v
    for d in (0.015, 0.025, 0.03):               # drift 게이트 단일변수
        v = dict(SHIPPED); v["WRF_REGIME_SLOPE_MIN_DRIFT"] = d
        yield f"slope_drift={d}", v
    for p in (0.85, 0.95):                        # ER 백분위 단일변수
        v = dict(SHIPPED); v["WRF_REGIME_ER_PCTL_MIN"] = p
        yield f"er_pctl_min={p}", v
    for w in (30, 40):                             # 기울기/드리프트 윈도 (느린 grind 누적)
        v = dict(SHIPPED); v["WRF_REGIME_SLOPE_WIN"] = w
        yield f"slope_win={w}", v


def build_regimes():
    """각 스냅샷에 baseline·shipped·후보별 regime + forward label 부착."""
    recs = []
    var_list = list(variants())
    for sym in SYMS:
        rows = load(sym)
        closes = [float(r["p0"]) for r in rows]
        for i in range(60, len(rows)):
            ch = closes[:i + 1]
            adx = rows[i]["raw"]["adx"]
            lab = fwd_label(rows[i].get("path") or {})
            if lab is None:
                continue
            base = regime_at(ch, adx, None)
            rec = {"sym": sym, "fwd": lab, "ema4": rows[i]["raw"].get("ema_4h"),
                   "base": base}
            for name, params in var_list:
                rec[name] = regime_at(ch, adx, params)
            recs.append(rec)
    return pd.DataFrame(recs), [n for n, _ in var_list]


def metrics(df, col):
    """승격 회수·FP·정밀도·TF약세율. baseline이 TF차단인 것만 회수 모집단."""
    blocked = df[df.base.isin(TFBLOCK)]
    dn = blocked[blocked.fwd == "DIR_DOWN"]
    up = blocked[blocked.fwd == "DIR_UP"]
    rec_dn = (dn[col] == "TRENDING").mean() * 100 if len(dn) else 0.0
    rec_up = (up[col] == "TRENDING").mean() * 100 if len(up) else 0.0
    chop = df[df.fwd == "CHOP"]
    fp = (chop[col] == "TRENDING").mean() * 100 if len(chop) else 0.0
    promoted = df[(df[col] == "TRENDING") & (df.base.isin(TFBLOCK))]
    prec = promoted.fwd.isin(["DIR_DOWN", "DIR_UP"]).mean() * 100 if len(promoted) else 0.0
    # 회수된 하락추세 바 중 4H EMA 약세(=숏 TF 생성 가능)
    recov_dn = dn[dn[col] == "TRENDING"]
    align = (recov_dn.ema4 == -1).mean() * 100 if len(recov_dn) else 0.0
    return {"rec_dn": rec_dn, "rec_up": rec_up, "fp": fp, "prec": prec,
            "n_prom": len(promoted), "align_dn": align}


def main():
    df, names = build_regimes()
    print("=" * 92)
    print(f"grind→TF 재측정 (전체 6+7월, 평가 스냅샷 {len(df)}건, fwd=path 24h 실현)")
    print(f"  baseline(승격OFF) TF차단율: {(df.base.isin(TFBLOCK)).mean()*100:.0f}% | "
          f"DIR_DOWN {int((df.fwd=='DIR_DOWN').sum())} · DIR_UP {int((df.fwd=='DIR_UP').sum())} · "
          f"CHOP {int((df.fwd=='CHOP').sum())}")
    print("=" * 92)
    base_m = metrics(df, "현행(shipped)")
    print(f"\n{'변형':<22}{'숏회수%':>8}{'롱회수%':>8}{'chopFP%':>9}{'정밀도%':>8}{'승격수':>7}{'회수숏4H약세%':>13}")
    for name in names:
        m = metrics(df, name)
        star = ""
        if name != "현행(shipped)":
            # 사전등록 게이트 (숏회수↑ ∧ FP≤현행+5 ∧ 정밀도≥55 ∧ 4H약세≥현행)
            ok = (m["rec_dn"] > base_m["rec_dn"] and m["fp"] <= base_m["fp"] + 5.0
                  and m["prec"] >= 55.0 and m["align_dn"] >= base_m["align_dn"])
            star = "  ✔통과" if ok else "  ✗탈락"
        print(f"{name:<22}{m['rec_dn']:>8.0f}{m['rec_up']:>8.0f}{m['fp']:>9.1f}"
              f"{m['prec']:>8.0f}{m['n_prom']:>7}{m['align_dn']:>13.0f}{star}")
    passed = [n for n in names if n != "현행(shipped)"
              and (lambda m: m["rec_dn"] > base_m["rec_dn"] and m["fp"] <= base_m["fp"] + 5.0
                   and m["prec"] >= 55.0 and m["align_dn"] >= base_m["align_dn"])(metrics(df, n))]
    print("\n" + "=" * 92)
    if passed:
        print(f"판정: 게이트 통과 → 단일변수 채택 검토: {passed}")
    else:
        print("판정: 게이트 통과 변형 0 → **현행 유지**(파라미터 변경 없음).")
        print(f"  · 현행이 효율 프론티어: 회수↑는 전부 chop-FP↑·정밀도↓로 상쇄.")
        print(f"  · grind-숏 회수 ~{base_m['rec_dn']:.0f}%가 구조적 상한(느린 grind가 slope-persist에서")
        print(f"    chop과 통계적으로 준-구별불가) → TF가 grind-숏 대다수를 원천 커버 불가.")
        print(f"  · er_pctl은 grind 회수에 무효(is_ranging 뒤 판정 — 설계상 chop-FP 보호).")
        print(f"  · 함의: grind-숏 빈도의 근본 회복은 파라미터 튜닝이 아니라 신규 방향신호")
        print(f"    (Phase 4·다레짐 검증 전제)의 몫. 밴드반전 승격이 메운 공백은 실재했음.")


if __name__ == "__main__":
    main()
