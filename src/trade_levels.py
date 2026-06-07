"""
trade_levels.py — TP/SL 산출 (1h Bot v4.0)
────────────────────────────────────────────────────────────────────
스윙(1h, 최대 3일 보유) 신호의 손절(SL)·익절(TP)을 ATR + 시장구조로 산출한다.
성공/실패 자동 판정(notion_logger)의 기준선이 된다.

설계:
  · 손절 거리(risk) = max(ATR×배수, 가격×최소%)  (가격×최대%로 상한)
  · 구조 손절: 직전 스윙 저점(롱)/고점(숏)이 합리적 밴드면 우선 사용
  · 익절 = 진입가 ± risk × R배수 (신호 등급별 R)
"""
import logging
import config

logger = logging.getLogger(__name__)


def grade_of(score: float) -> str:
    if score >= config.GRADE_STRONG_SCORE: return "STRONG"
    if score >= config.GRADE_GOOD_SCORE:   return "GOOD"
    return "WATCH"


def _effective_grade_score(analysis: dict, score: float) -> float:
    """[v5.0-F] 등급 산정용 유효점수. 거시추세 정합 + 확정 추세추종이면 가산.
    (강한 추세숏이 단순 점수만으로 WATCH에 머무르던 문제 교정)"""
    meta = analysis.get("_entry_meta", {}) or {}
    eff = score
    if meta.get("with_trend") and meta.get("trend_aligned"):
        eff += config.GRADE_WITH_TREND_BONUS
    return eff


def compute_trade_levels(analysis: dict, direction: str, score: float) -> dict:
    """진입가/손절/익절/리스크% 산출. 실패 시 available=False."""
    price = float(analysis.get("current_price") or 0.0)
    atr_info = analysis.get("atr", {}) or {}
    atr_abs = float(atr_info.get("current") or 0.0)
    atr_pct = float(atr_info.get("pct") or 0.0)

    if price <= 0:
        return {"available": False}

    # ATR 결측 시 가격 기반 추정(0.6%)으로 폴백
    if atr_abs <= 0:
        atr_abs = price * 0.006

    # ── 손절 거리 (ATR 기반) ──────────────────────────────────────
    risk = atr_abs * config.TPSL_ATR_SL_MULT
    risk = max(risk, price * config.TPSL_MIN_SL_PCT)
    risk = min(risk, price * config.TPSL_MAX_SL_PCT)

    # ── 구조 손절 우선 반영 (직전 스윙 고/저점) ──────────────────
    if config.TPSL_USE_STRUCTURE:
        bos = analysis.get("bos_choch", {}) or {}
        buf = config.TPSL_STRUCTURE_BUFFER
        if direction == "long":
            sl_struct = bos.get("last_swing_low")
            if sl_struct and sl_struct < price:
                struct_risk = price - sl_struct * (1 - buf)
                if price * config.TPSL_MIN_SL_PCT <= struct_risk <= price * config.TPSL_MAX_SL_PCT:
                    risk = struct_risk
        else:
            sl_struct = bos.get("last_swing_high")
            if sl_struct and sl_struct > price:
                struct_risk = sl_struct * (1 + buf) - price
                if price * config.TPSL_MIN_SL_PCT <= struct_risk <= price * config.TPSL_MAX_SL_PCT:
                    risk = struct_risk

    grade  = grade_of(_effective_grade_score(analysis, score))
    r_mult = config.TPSL_TP_R_BY_GRADE.get(grade, config.TPSL_TP_R_MULTIPLE)

    if direction == "long":
        sl = price - risk
        tp = price + risk * r_mult
    else:
        sl = price + risk
        tp = price - risk * r_mult

    risk_pct = risk / price * 100.0
    logger.info(
        f"[TP/SL/{direction.upper()}] 진입:{price:.4f} SL:{sl:.4f} TP:{tp:.4f} "
        f"(risk:{risk_pct:.2f}% R:{r_mult}배 ATR:{atr_pct:.2f}%)"
    )
    return {
        "available": True,
        "entry": round(price, 6),
        "stop_loss": round(sl, 6),
        "take_profit": round(tp, 6),
        "risk_pct": round(risk_pct, 4),
        "r_multiple": r_mult,
        "atr_pct": round(atr_pct, 4),
        "grade": grade,
    }
