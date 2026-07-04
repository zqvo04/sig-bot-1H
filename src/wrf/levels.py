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
        tp_dist = box_h   # TP = 박스높이 측정이동(공통)
        # SL 배치: [grind-fix B] WRF_BO_SL_NEAR 로 토글.
        #   OFF(구동작): 박스 반대편 복귀(far) → 손절거리=박스높이 → RR≈1 고착.
        #   ON: 돌파된 경계(near) ∓ ATR쿠션 = 돌파-리테스트 무효화선 → RR 정상화.
        #   둘 다 롱/숏 대칭. min_sl/max_sl 클램프가 과타이트/과와이드 방지.
        if getattr(config, "WRF_BO_SL_NEAR", False):
            cushion = atr * getattr(config, "WRF_BO_SL_ATR_CUSHION", 1.0)
            if long:    # box_hi 상향돌파 → 무효화 = 깨진 경계 아래 쿠션
                sl_dist = max(price - (candidate["box_hi"] - cushion), min_sl)
            else:       # box_lo 하향돌파 → 무효화 = 깨진 경계 위 쿠션
                sl_dist = max((candidate["box_lo"] + cushion) - price, min_sl)
        elif long:
            sl_dist = max(price - candidate["box_lo"] * 0.999, min_sl)
        else:
            sl_dist = max(candidate["box_hi"] * 1.001 - price, min_sl)
        rr = tp_dist / sl_dist if sl_dist > 0 else 2.0
    elif setup == "MR" and "box_hi" in candidate and "box_lo" in candidate:
        # [G4] 박스 기하학: TP = 중심선(mid)/반대편 경계(opposite), SL = 경계 외곽 ∓ ATR
        box_hi = float(candidate["box_hi"])
        box_lo = float(candidate["box_lo"])
        box_mid = (box_hi + box_lo) / 2.0
        cushion = atr * getattr(config, "WRF_MR_ATR_CUSHION", 1.0)
        target = getattr(config, "WRF_MR_TP_TARGET", "mid")
        if long:   # 하단 반전
            sl_dist = max((price - box_lo) + cushion, min_sl)
            tp_dist = max((box_mid if target == "mid" else box_hi) - price, 0.0)
        else:      # 상단 반전
            sl_dist = max((box_hi - price) + cushion, min_sl)
            tp_dist = max(price - (box_mid if target == "mid" else box_lo), 0.0)
        rr = tp_dist / sl_dist if sl_dist > 0 else 1.5
    elif setup == "MR":
        # 박스 산정 실패 폴백 — TP = EMA20 회귀, SL = ATR
        ema20 = None
        try:
            ema20 = float(df["close"].ewm(span=20, adjust=False).mean().iloc[-1])
        except Exception:
            ema20 = price
        tp_dist = abs(ema20 - price)
        sl_dist = atr * 1.2
        rr = tp_dist / sl_dist if sl_dist > 0 else 1.5
    else:
        # TF / RV: 구조 SL(직전 스윙 ∓ ATR 쿠션) + R배수 TP  [G3]
        if getattr(config, "TPSL_USE_STRUCTURE", True) and df is not None and len(df) > 10:
            try:
                swing_lo = float(df["low"].iloc[-10:].min())
                swing_hi = float(df["high"].iloc[-10:].max())
                cushion = atr * getattr(config, "WRF_SL_ATR_CUSHION", 1.5)
                if long:
                    cand_sl = price - (swing_lo - cushion)   # 스윙 저점 - ATR×k
                else:
                    cand_sl = (swing_hi + cushion) - price    # 스윙 고점 + ATR×k
                if cand_sl > 0:
                    sl_dist = min(max(cand_sl, min_sl), max_sl)  # 폐기 대신 클램프
            except Exception:
                pass
        rr = 2.5 if setup == "TF" else 2.0
        tp_dist = sl_dist * rr

    sl_dist = min(sl_dist, max_sl)
    # [P2] TF 추세 태우기(무상태 트레일링): 고정 TP가 스윙 몸통을 자르는 FN을 완화. TF에 한해
    # HWM−k·ATR 샹들리에 트레일 거리를 주석(trail_dist)으로 발행하고 보유상한을 확장한다.
    # 라이브는 포지션 상태를 들지 않고 규칙만 전달 → 오프라인 라벨러가 동일 규칙으로 채점(5-E).
    trail_dist = None
    if setup == "TF" and getattr(config, "WRF_TF_TRAIL", False):
        trail_dist = atr * getattr(config, "WRF_TF_TRAIL_ATR", 3.0)
        t_max = getattr(config, "WRF_TF_TRAIL_TMAX", 72)
    if long:
        sl = price - sl_dist
        tp = price + tp_dist
    else:
        sl = price + sl_dist
        tp = price - tp_dist
    rr_final = (abs(tp - price) / sl_dist) if sl_dist > 0 else rr

    out = {
        "entry": round(price, 8),
        "tp": round(tp, 8),
        "sl": round(sl, 8),
        "r_dist": round(sl_dist, 8),
        "rr": round(rr_final, 3),
        "t_max": int(t_max),
    }
    if trail_dist is not None and trail_dist > 0:
        out["trail_dist"] = round(trail_dist, 8)
    return out
