"""
directional_bias.py — 거시 방향성 앵커 (1h Bot v5.0)
────────────────────────────────────────────────────────────────────
[v5.0 — Trend-First, Reversal-Gated 아키텍처의 최상위 레이어]

기존 시스템은 1H 레짐(매시간 EXPLOSIVE↔TRENDING↔RANGING로 깜빡임)에 과의존해
가중치·임계가 출렁였고, "멀티TF 과매도"가 만능 트리거가 되어 강한 하락추세
한복판에서 떨어지는 칼(롱)을 반복 매수했다.

v5.0은 Daily + 4H 의 느린 타임프레임을 묶어 단일 거시 추세 앵커(macro_trend)를
산출한다. 이 앵커가 진입을 두 트랙으로 분기한다:
  · 추세추종(with-trend)  : 진입방향 == macro_trend → 적극 포착(임계 완화)
  · 역추세반전(counter)   : 진입방향 == 반대        → 반전 확인 게이트 필수

산출 근거(가중 합산, 부호 = 방향):
  · 1D EMA(9/21) 방향        ±W_EMA1D
  · 4H EMA(9/21) 방향        ±W_EMA4
  · 일봉 바이어스(BULL/BEAR) ±W_DAILY
  · 1D EMA 구조(정배열/역배열) ±W_ESTRUCT
  · 4H 추세 성숙도(HH/HL vs LH/LL) ±W_MATURITY
  · 4H BOS(시장구조 돌파)    ±W_BOS4
"""
import logging
import config

logger = logging.getLogger(__name__)


def compute_macro_trend(analysis: dict) -> dict:
    """Daily+4H 결합 거시 추세 앵커. analysis 전체를 받아 방향/강도 산출."""
    ema       = analysis.get("ema_long", {}) or {}      # tf_signals 는 방향 무관 공통
    tf        = ema.get("tf_signals", {}) or {}
    s4        = tf.get("4h", "neutral")
    s1d       = tf.get("1d", "neutral")
    db        = (analysis.get("daily_bias", {}) or {}).get("bias", "NEUTRAL")
    estruct   = (analysis.get("ema_structure", {}) or {}).get("structure", "neutral")
    mat       = analysis.get("maturity", {}) or {}
    bos4      = analysis.get("bos_choch_4h", {}) or {}

    score = 0.0
    parts = []

    if s4 == "bullish":   score += config.MACRO_W_EMA4;  parts.append("4hEMA↑")
    elif s4 == "bearish": score -= config.MACRO_W_EMA4;  parts.append("4hEMA↓")

    if s1d == "bullish":   score += config.MACRO_W_EMA1D; parts.append("1dEMA↑")
    elif s1d == "bearish": score -= config.MACRO_W_EMA1D; parts.append("1dEMA↓")

    if db == "BULL":   score += config.MACRO_W_DAILY; parts.append("일봉强")
    elif db == "BEAR": score -= config.MACRO_W_DAILY; parts.append("일봉弱")

    if estruct == "bull":   score += config.MACRO_W_ESTRUCT; parts.append("정배열")
    elif estruct == "bear": score -= config.MACRO_W_ESTRUCT; parts.append("역배열")

    bc = int(mat.get("bull_count", 0)); brc = int(mat.get("bear_count", 0))
    if bc > brc:   score += config.MACRO_W_MATURITY; parts.append(f"4h성숙↑{bc}")
    elif brc > bc: score -= config.MACRO_W_MATURITY; parts.append(f"4h성숙↓{brc}")

    if bos4.get("bos_bullish"):   score += config.MACRO_W_BOS4; parts.append("4hBOS↑")
    if bos4.get("bos_bearish"):   score -= config.MACRO_W_BOS4; parts.append("4hBOS↓")

    thr = config.MACRO_TREND_THRESHOLD
    if   score >=  thr: trend = "UP"
    elif score <= -thr: trend = "DOWN"
    else:               trend = "NEUTRAL"

    strength = min(3, int(abs(score) / config.MACRO_STRENGTH_DIVISOR))

    logger.info(
        f"[거시추세] {trend} (강도{strength}, score:{score:+.1f}) "
        f"[{', '.join(parts) if parts else '중립'}]"
    )
    return {
        "trend": trend,
        "strength": strength,
        "score": round(score, 2),
        "components": parts,
    }
