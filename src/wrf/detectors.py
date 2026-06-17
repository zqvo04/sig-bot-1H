"""L2 — 셋업 디텍터 ×4. 레짐이 허용집합을 결정한다.

각 디텍터는 롱/숏 대칭으로 후보를 만든다. 후보는 구조적 전제(precond)와
직교 3축(C/L/F ∈ [-1,1], 진입방향 정렬치)을 담는다. precond는 "강확증"
구조게이트(특히 BO 리테스트·RV ≥3확인은 필수★), 축은 prior P̂ 입력이다.

  TF(TRENDING+HTF정합): HH/HL + EMA20/VWAP 눌림 + 모멘텀 재정렬
  BO(SQUEEZE→확장/박스): 경계돌파 + 거래량스파이크 + [리테스트 유지★필수]
  MR(RANGING): BB극단 + RSI극단백분위 + 반전마이크로트리거
  RV(추세소진): 다이버전스 + 키레벨거부 + CHoCH + [≥3확인★] + (청산·펀딩·OI플러시)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))


def _ctx_axis(ctx: dict, direction: str) -> float:
    """C 맥락 축: 거시방향·일봉바이어스 정렬 (방향중립 [-1,1])."""
    macro = ctx.get("btc_macro", "CHOP")
    bias = ctx.get("bias_1d", "NEUTRAL")
    m = {"UPLEG": 1.0, "DOWNLEG": -1.0, "CHOP": 0.0}.get(macro, 0.0)
    b = {"BULL": 1.0, "BEAR": -1.0, "NEUTRAL": 0.0}.get(bias, 0.0)
    base = 0.6 * m + 0.4 * b
    return _clip(base if direction == "long" else -base)


def _flow_axis(raw: dict, pcts: dict, direction: str) -> float:
    """F 흐름 축: RSI/MACD 백분위 + 포지셔닝(펀딩·테이커·고래·OI·청산)."""
    long = direction == "long"
    # 모멘텀 동조: 롱이면 macd 백분위 높을수록 +, rsi는 과열 아닌 동조
    mom = (pcts.get("macd", 0.5) - 0.5) * 2.0
    # 테이커/롱숏/스마트머니 포지셔닝
    taker = ((raw.get("taker_buy") or 0.5) - 0.5) * 2.0
    smart = max(-1.0, min(1.0, (raw.get("smart_div") or 0.0) * 4.0))
    oi = {"trend_long": 0.5, "expanding_long": 0.5, "trend_short": -0.5,
          "expanding_short": -0.5}.get(raw.get("oi_quadrant", "neutral"), 0.0)
    base = 0.45 * mom + 0.25 * taker + 0.2 * smart + 0.1 * oi
    return _clip(base if long else -base)


def _detect_tf(feat: dict, measures: dict):
    raw, pcts, ctx = feat["raw"], feat["pct"], feat["ctx"]
    out = []
    if "TF" not in ctx["allowed_setups"]:
        return out
    for direction in ("long", "short"):
        long = direction == "long"
        ema_aligned = (raw.get("ema") == (1 if long else -1)
                       and raw.get("ema_4h") in ((1, 0) if long else (-1, 0)))
        # 눌림: 가격이 EMA20 근방으로 되돌림 (loc_ema20 백분위 중하단/중상단)
        loc = pcts.get("loc_ema20", 0.5)
        pullback = (0.15 <= loc <= 0.55) if long else (0.45 <= loc <= 0.85)
        mom_realign = raw.get("macd_bull") if long else (not raw.get("macd_bull"))
        struct = raw.get("bos") == (1 if long else -1) or raw.get("bos_4h") == (1 if long else -1)
        precond = bool(ema_aligned and pullback and (mom_realign or struct))
        if not precond:
            continue
        C = _ctx_axis(ctx, direction)
        # L: 눌림 품질 — 이상적 눌림(롱 loc≈0.35)에서 +1, 추세 정합 보강
        ideal = 0.35 if long else 0.65
        L = _clip(1.0 - abs(loc - ideal) / 0.35) * (0.7 + 0.3 * (1 if struct else 0))
        F = _flow_axis(raw, pcts, direction)
        out.append({"setup": "TF", "dir": direction, "precond": True,
                    "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
                    "confluence_n": raw.get(f"confluence_{direction}", 0),
                    "reason": "HTF정합+눌림+모멘텀재정렬"})
    return out


def _detect_bo(feat: dict, measures: dict):
    raw, pcts, ctx = feat["raw"], feat["pct"], feat["ctx"]
    out = []
    if "BO" not in ctx["allowed_setups"]:
        return out
    df = feat["df_1h"]
    if df is None or len(df) < 25:
        return out
    box_hi = float(df["high"].iloc[-21:-1].max())
    box_lo = float(df["low"].iloc[-21:-1].min())
    last = float(df["close"].iloc[-1])
    box_h = (box_hi - box_lo) / last if last else 0.0
    vol_spike = (raw.get("vol_ratio") or 0) >= 1.5
    for direction in ("long", "short"):
        long = direction == "long"
        broke = (last > box_hi) if long else (last < box_lo)
        # 리테스트 유지★필수: 직전 봉이 경계 재테스트 후 유지
        prev_low = float(df["low"].iloc[-1])
        prev_high = float(df["high"].iloc[-1])
        retest_hold = (prev_low <= box_hi * 1.001 and last > box_hi) if long \
            else (prev_high >= box_lo * 0.999 and last < box_lo)
        precond = bool(broke and vol_spike and retest_hold)
        if not precond:
            continue
        C = _ctx_axis(ctx, direction)
        L = _clip(0.5 + min(0.5, box_h * 10))  # 박스가 넓을수록 측정이동 여지 ↑
        F = _flow_axis(raw, pcts, direction)
        out.append({"setup": "BO", "dir": direction, "precond": True,
                    "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
                    "confluence_n": raw.get(f"confluence_{direction}", 0),
                    "box_hi": box_hi, "box_lo": box_lo,
                    "reason": "경계돌파+거래량+리테스트유지"})
    return out


def _detect_mr(feat: dict, measures: dict):
    raw, pcts, ctx = feat["raw"], feat["pct"], feat["ctx"]
    out = []
    if "MR" not in ctx["allowed_setups"]:
        return out
    c1 = measures.get("candle_pattern", {})
    for direction in ("long", "short"):
        long = direction == "long"
        bbpos = raw.get("bb_pctb")
        bb_extreme = (bbpos is not None and bbpos <= 0.1) if long \
            else (bbpos is not None and bbpos >= 0.9)
        rsi_p = pcts.get("rsi", 0.5)
        rsi_extreme = (rsi_p <= 0.15) if long else (rsi_p >= 0.85)
        micro = (c1.get("bullish_pin") or c1.get("bullish_engulf")) if long \
            else (c1.get("bearish_pin") or c1.get("bearish_engulf"))
        precond = bool(bb_extreme and rsi_extreme and micro)
        if not precond:
            continue
        C = _ctx_axis(ctx, direction)
        # MR은 평균회귀 — 극단일수록 L 강함(방향 정렬: 롱이면 저극단 = +)
        depth = (0.15 - rsi_p) / 0.15 if long else (rsi_p - 0.85) / 0.15
        L = _clip(0.5 + max(0.0, depth))
        F = _flow_axis(raw, pcts, direction)
        out.append({"setup": "MR", "dir": direction, "precond": True,
                    "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
                    "confluence_n": raw.get(f"confluence_{direction}", 0),
                    "reason": "BB극단+RSI극단+반전마이크로"})
    return out


def _detect_rv(feat: dict, measures: dict):
    raw, pcts, ctx = feat["raw"], feat["pct"], feat["ctx"]
    out = []
    if "RV" not in ctx["allowed_setups"]:
        return out
    rsi_m = measures.get("rsi", {})
    c1 = measures.get("candle_pattern", {})
    wk = measures.get("weekly_levels", {})
    for direction in ("long", "short"):
        long = direction == "long"
        # 추세소진 반전: 롱반전=하락추세 바닥소진
        div = rsi_m.get("bullish_divergence") if long else rsi_m.get("bearish_divergence")
        choch = (raw.get("choch") == 1 or raw.get("choch_4h") == 1) if long \
            else (raw.get("choch") == -1 or raw.get("choch_4h") == -1)
        key_reject = bool(wk.get("near_level"))
        rev_candle = (c1.get("bullish_pin") or c1.get("bullish_engulf")) if long \
            else (c1.get("bearish_pin") or c1.get("bearish_engulf"))
        liq_flush = bool(raw.get("liq_spike"))
        funding_extreme = (pcts.get("funding", 0.5) <= 0.1) if long \
            else (pcts.get("funding", 0.5) >= 0.9)
        oi_flush = raw.get("oi_quadrant") in ("reversal_long", "weak_bounce") if long else \
            raw.get("oi_quadrant") in ("reversal_short", "weak_bounce")
        confirms = sum([bool(div), bool(choch), bool(key_reject), bool(rev_candle),
                        bool(liq_flush), bool(funding_extreme), bool(oi_flush)])
        # ≥3확인★ 필수
        precond = confirms >= 3
        if not precond:
            continue
        C = _ctx_axis(ctx, direction)
        L = _clip(0.4 + 0.1 * confirms)
        F = _flow_axis(raw, pcts, direction)
        out.append({"setup": "RV", "dir": direction, "precond": True,
                    "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
                    "confluence_n": raw.get(f"confluence_{direction}", 0),
                    "confirms": confirms, "reason": f"추세소진({confirms}확인)"})
    return out


def detect_all(feat: dict) -> list:
    """4디텍터 실행 → 후보 리스트(발사 무관 전량). 디텍터별 try/except 격리."""
    measures = feat.get("measures", {})
    cands = []
    for fn in (_detect_tf, _detect_bo, _detect_mr, _detect_rv):
        try:
            cands.extend(fn(feat, measures))
        except Exception as e:  # pragma: no cover
            logger.warning(f"[detector {fn.__name__}] 실패(격리): {e}")
    return cands
