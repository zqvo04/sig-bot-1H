"""L4 보조 — 셋업별 구조기반 TP/SL/타임스톱.

  TF: TP=측정이동, SL=눌림저점, T=48h
  BO: TP=박스높이,  SL=박스복귀, T=36h
  MR: TP=VWAP/EMA20, SL=극단+ATR, T=24h(타임스톱=스크래치)
  RV: TP=직전레벨,  SL=극단너머, T=48h
거리는 ATR 기반 폴백으로 항상 산출(구조 부재 안전).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import config
except ImportError:  # pragma: no cover
    from src import config  # type: ignore


def _atr_abs(measures: dict, price: float) -> float:
    atr = (measures.get("atr") or {})
    a = atr.get("current")
    if a and a > 0:
        return float(a)
    pct = atr.get("pct")
    if pct:
        return float(pct) / 100.0 * price
    return price * 0.01


def compute_levels(candidate: dict, feat: dict) -> dict:
    """후보 → {entry, tp, sl, r_dist, rr, t_max}. 페이퍼 진입가 = 다음 봉 시가 근사(현재가)."""
    setup = candidate["setup"]
    direction = candidate["dir"]
    long = direction == "long"
    measures = feat.get("measures", {})
    price = float(feat["p0"])
    atr = _atr_abs(measures, price)
    df = feat.get("df_1h")
    t_max = getattr(config, "WRF_TMAX", {}).get(setup, 48)

    sl_mult = getattr(config, "TPSL_ATR_SL_MULT", 2.0) if hasattr(config, "TPSL_ATR_SL_MULT") else 2.0
    min_sl = price * getattr(config, "TPSL_MIN_SL_PCT", 0.012)
    max_sl = price * getattr(config, "TPSL_MAX_SL_PCT", 0.05)
    sl_dist = max(atr * sl_mult, min_sl)

    rr = 2.0
    if setup == "BO" and "box_hi" in candidate and "box_lo" in candidate:
        box_h = abs(candidate["box_hi"] - candidate["box_lo"])
        # SL = 박스복귀(경계 반대), TP = 박스높이 측정이동
        if long:
            sl_dist = max(price - candidate["box_lo"] * 0.999, min_sl)
            tp_dist = box_h
        else:
            sl_dist = max(candidate["box_hi"] * 1.001 - price, min_sl)
            tp_dist = box_h
        rr = tp_dist / sl_dist if sl_dist > 0 else 2.0
    elif setup == "MR":
        # TP = VWAP/EMA20 회귀, SL = 극단 + ATR
        ema20 = None
        try:
            ema20 = float(df["close"].ewm(span=20, adjust=False).mean().iloc[-1])
        except Exception:
            ema20 = price
        tp_dist = abs(ema20 - price)
        sl_dist = atr * 1.2
        rr = tp_dist / sl_dist if sl_dist > 0 else 1.5
    else:
        # TF / RV: 구조 SL + R배수 TP
        if getattr(config, "TPSL_USE_STRUCTURE", True) and df is not None and len(df) > 10:
            try:
                swing_lo = float(df["low"].iloc[-10:].min())
                swing_hi = float(df["high"].iloc[-10:].max())
                buf = getattr(config, "TPSL_STRUCTURE_BUFFER", 0.001)
                if long:
                    cand_sl = price - swing_lo * (1 - buf)
                    if 0 < cand_sl < max_sl:
                        sl_dist = max(cand_sl, min_sl)
                else:
                    cand_sl = swing_hi * (1 + buf) - price
                    if 0 < cand_sl < max_sl:
                        sl_dist = max(cand_sl, min_sl)
            except Exception:
                pass
        rr = 2.5 if setup == "TF" else 2.0
        tp_dist = sl_dist * rr

    sl_dist = min(sl_dist, max_sl)
    if long:
        sl = price - sl_dist
        tp = price + tp_dist
    else:
        sl = price + sl_dist
        tp = price - tp_dist
    rr_final = (abs(tp - price) / sl_dist) if sl_dist > 0 else rr

    return {
        "entry": round(price, 8),
        "tp": round(tp, 8),
        "sl": round(sl, 8),
        "r_dist": round(sl_dist, 8),
        "rr": round(rr_final, 3),
        "t_max": int(t_max),
    }
