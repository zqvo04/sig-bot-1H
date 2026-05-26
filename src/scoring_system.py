"""
scoring_system.py — 점수 산출 (1h Bot v2.0)
────────────────────────────────────────────────────────────────────
[v2.0 추가: 5개 개선 기능]

① 4h 메타 레짐 레이어 (META_REGIME_THRESHOLD_ADJ)
   4h × 1h 레짐 조합으로 임계값 ±3~8pt 조정
   가장 큰 임팩트: 4h RANGING 중 1h 시그널 +5pt 차단

② 일봉 바이어스 (analyze_daily_bias 결과 참조)
   방향 일치: -3pt / 역추세: +7pt

③ 4h BOS/CHoCH 통합
   보너스: 4h BOS 방향 일치 +12pt (1h: +8pt)
   패널티: 4h CHoCH 역방향 ×0.80 (1h: ×0.88)
          4h BOS  역방향 ×0.78 (1h: ×0.82)
   → soft_penalty 체인 편입

④ 거래 세션 필터 (UTC 기준)
   _get_session_threshold_adj(): 아시아+4, 런던±0, NY-2, 오버랩-3, 주말+6

⑦ 펀딩비 8h 사이클
   _get_funding_cycle_adj(): OKX 정산 ±1h 구간 +3pt

[1h Bot v1.0 (v3.7 기반) 전체 기능 유지]
────────────────────────────────────────────────────────────────────
"""
import json, logging, os
from datetime import datetime, timezone, timedelta
import config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# [v2.0 ④⑦] 세션 / 펀딩 사이클 헬퍼
# ══════════════════════════════════════════════════════════════

def _get_session_threshold_adj() -> int:
    """
    [v2.0 ④] UTC 기준 거래 세션 임계값 조정
    런던+NY 오버랩(13-16h): -3pt  최고 유동성
    NY(16-22h):             -2pt  높은 유동성
    런던(07-13h):            0pt  기본
    아시아/데드존(22-07h):  +4pt  낮은 유동성, 오신호 위험
    주말(토/일):            +6pt  유동성 급감
    """
    now     = datetime.now(timezone.utc)
    hour    = now.hour
    weekday = now.weekday()  # 0=월 … 5=토, 6=일

    if weekday >= 5:          return config.SESSION_ADJ_WEEKEND
    if 13 <= hour < 16:       return config.SESSION_ADJ_OVERLAP
    if 16 <= hour < 22:       return config.SESSION_ADJ_NY
    if  7 <= hour < 13:       return config.SESSION_ADJ_LONDON
    return config.SESSION_ADJ_ASIA   # 22-23 or 0-6


def _get_funding_cycle_adj() -> int:
    """
    [v2.0 ⑦] OKX 펀딩비 정산 ±1h 구간 임계값 조정
    정산: 00:00 / 08:00 / 16:00 UTC
    해당 시간대: 포지션 청산 노이즈 → +3pt
    """
    hour = datetime.now(timezone.utc).hour
    if hour in config.FUNDING_CYCLE_HOURS:
        return config.FUNDING_CYCLE_ADJ
    return 0


def _get_tiered_bonus_cap(base_score: float) -> int:
    for threshold, cap in config.BONUS_CAP_TIERS:
        if base_score < threshold:
            return cap
    return 36


# ══════════════════════════════════════════════════════════════
# 점수 산출 메인
# ══════════════════════════════════════════════════════════════

def calculate_entry_score(analysis: dict, direction: str,
                           micro_result: dict = None) -> dict:
    d    = direction
    gate = analysis.get(f"gate_{d}", {})
    gate_penalty = gate.get("funding_penalty", 1.0)

    rsi     = analysis.get("rsi",         {})
    bb      = analysis.get("bollinger",    {})
    funding = analysis.get("funding_rate", {})
    ls      = analysis.get("ls_ratio",     {})
    taker   = analysis.get("taker_volume", {})
    liq     = analysis.get("liquidations", {})
    vol     = analysis.get("volume",       {})
    adx_15m = analysis.get("adx_1h",      {})   # [1h Bot] entry ADX = 1h
    regime  = analysis.get("regime",       {})

    # [v2.0] 신규 분석 데이터
    bos_choch_4h  = analysis.get("bos_choch_4h",  {})
    regime_4h     = analysis.get("regime_4h",      {})
    daily_bias    = analysis.get("daily_bias",     {})
    regime_4h_name = regime_4h.get("regime", "UNKNOWN")

    ema_info      = analysis.get(f"ema_{d}", {})
    reverse_count = ema_info.get("reverse_count", 0)

    rsi_val_15m  = rsi.get("value",    50.0)   # 1h RSI (entry)
    rsi_val_1h   = rsi.get("value_1h", 50.0)   # 4h RSI (mid)
    rsi_val_4h   = rsi.get("value_4h", 50.0)   # 1d RSI (macro)
    bb_state_str = bb.get("state", "")

    # ── 가중합 ───────────────────────────────────────────────
    scores = {
        "rsi":              rsi.get(f"{d}_score",     50.0),
        "bollinger":        bb.get(f"{d}_score",      50.0),
        "funding_rate":     funding.get(f"{d}_score", 50.0),
        "long_short_ratio": ls.get(f"{d}_score",      50.0),
        "taker_volume":     taker.get(f"{d}_score",   50.0),
        "volume":           vol.get("score",          50.0),
    }

    regime_name = regime.get("regime", "UNKNOWN")
    weights     = config.REGIME_SCORE_WEIGHTS.get(regime_name, config.SCORE_WEIGHTS)

    bb_reversal_exempt = (
        (d == "long"  and bb_state_str == "lower_breakout") or
        (d == "short" and bb_state_str == "upper_breakout")
    )
    ema_all_reverse = (reverse_count == 3)

    if ema_all_reverse and not bb_reversal_exempt:
        ls_raw_before = scores["long_short_ratio"]
        scores["long_short_ratio"] = 50.0
        logger.info(f"[EMA3역방향] LS 중립화: {ls_raw_before:.0f}→50pt [{d.upper()}]")

    # BB 스퀴즈 + 방향 반대 위치 → BB 점수 중립화
    _bb_squeeze = bb.get("squeeze", False)
    if _bb_squeeze:
        _orig_bb = scores["bollinger"]
        if d == "short" and bb_state_str in ("near_upper","upper_zone","upper_breakout"):
            scores["bollinger"] = min(scores["bollinger"], 52.0)
        elif d == "long" and bb_state_str in ("near_lower","lower_zone","lower_breakout"):
            scores["bollinger"] = max(scores["bollinger"], 48.0)
        if _orig_bb != scores["bollinger"]:
            logger.info(f"[BB스퀴즈/{d.upper()}] BB중립화: {_orig_bb:.0f}→{scores['bollinger']:.0f}pt")

    # [A] BOS역방향 → LS 점수 중립화 (1h + 4h BOS 모두 고려)
    _bos_pre = analysis.get("bos_choch", {})
    _bos_reverse_pre = (
        (d == "long"  and (_bos_pre.get("bos_bearish") or bos_choch_4h.get("bos_bearish"))) or
        (d == "short" and (_bos_pre.get("bos_bullish") or bos_choch_4h.get("bos_bullish")))
    )
    if _bos_reverse_pre:
        _ls_s = scores["long_short_ratio"]
        _ls_already_bad = ((d=="long" and _ls_s < 50) or (d=="short" and _ls_s > 50))
        if not _ls_already_bad:
            scores["long_short_ratio"] = 50.0
            logger.info(f"[BOS역방향/A] LS 중립화: {_ls_s:.0f}→50pt [{d.upper()}] (1h or 4h BOS)")

    raw_score = sum(scores[k] * weights[k] for k in weights)

    # ── EMA 배율 ─────────────────────────────────────────────
    ema_table = config.REGIME_EMA_MULTIPLIERS.get(regime_name, config.EMA_MULTIPLIER)
    ema_mult  = ema_table.get(reverse_count, 1.0)
    logger.info(f"[EMA배율/{d.upper()}] {ema_info.get('tf_signals',{})} → ×{ema_mult:.2f}  [{regime_name}]")

    # ── 극단 과매도/과매수 판정 ──────────────────────────────
    is_extreme_oversold = (
        d == "long" and
        rsi_val_15m <= config.EXTREME_OVERSOLD_15M and
        rsi_val_1h  <= config.EXTREME_OVERSOLD_1H  and
        rsi_val_4h  <= config.EXTREME_OVERSOLD_4H  and
        bb_state_str in ("lower_breakout", "near_lower", "lower_zone")
    )
    is_extreme_overbought = (
        d == "short" and
        rsi_val_15m >= config.EXTREME_OVERBOUGHT_15M and
        rsi_val_1h  >= config.EXTREME_OVERBOUGHT_1H  and
        rsi_val_4h  >= config.EXTREME_OVERBOUGHT_4H  and
        bb_state_str in ("upper_breakout", "near_upper", "upper_zone")
    )
    if is_extreme_oversold:
        logger.info(f"[극단과매도/{d.upper()}] 전TF RSI 극단 1h:{rsi_val_15m:.0f} 4h:{rsi_val_1h:.0f} 1d:{rsi_val_4h:.0f}")
    if is_extreme_overbought:
        logger.info(f"[극단과매수/{d.upper()}] 전TF RSI 극단 1h:{rsi_val_15m:.0f} 4h:{rsi_val_1h:.0f} 1d:{rsi_val_4h:.0f}")

    # ── base_score ───────────────────────────────────────────
    base_score = raw_score * ema_mult * gate_penalty

    # ── soft 패널티 계산 ──────────────────────────────────────
    rsi_1h = rsi_val_1h   # 4h RSI (mid TF)
    rsi_4h = rsi_val_4h   # 1d RSI (macro TF)
    mtf_penalty = 1.0; mtf_penalty_reason = None

    if d == "long":
        if rsi_1h >= config.MTF_RSI_OVERBOUGHT_1H_EXTREME:
            mtf_penalty = config.MTF_RSI_PENALTY_STRONG
            mtf_penalty_reason = f"4h RSI 극단과매수({rsi_1h:.1f}) → 롱 ×{mtf_penalty}"
        elif rsi_1h >= config.MTF_RSI_OVERBOUGHT_1H and rsi_4h >= config.MTF_RSI_OVERBOUGHT_4H:
            mtf_penalty = config.MTF_RSI_PENALTY_STRONG
            mtf_penalty_reason = f"4h+1d RSI 강과매수({rsi_1h:.1f}/{rsi_4h:.1f}) → 롱 ×{mtf_penalty}"
        elif rsi_1h >= config.MTF_RSI_OVERBOUGHT_1H_MILD:
            mtf_penalty = config.MTF_RSI_PENALTY_MILD
            mtf_penalty_reason = f"4h RSI 약과매수({rsi_1h:.1f}) → 롱 ×{mtf_penalty}"
    elif d == "short":
        if rsi_1h <= config.MTF_RSI_OVERSOLD_1H_EXTREME:
            mtf_penalty = config.MTF_RSI_PENALTY_STRONG
            mtf_penalty_reason = f"4h RSI 극단과매도({rsi_1h:.1f}) → 숏 ×{mtf_penalty}"
        elif rsi_1h <= config.MTF_RSI_OVERSOLD_1H and rsi_4h <= config.MTF_RSI_OVERSOLD_4H:
            mtf_penalty = config.MTF_RSI_PENALTY_STRONG
            mtf_penalty_reason = f"4h+1d RSI 강과매도({rsi_1h:.1f}/{rsi_4h:.1f}) → 숏 ×{mtf_penalty}"
        elif rsi_1h <= config.MTF_RSI_OVERSOLD_1H_MILD:
            mtf_penalty = config.MTF_RSI_PENALTY_MILD
            mtf_penalty_reason = f"4h RSI 약과매도({rsi_1h:.1f}) → 숏 ×{mtf_penalty}"

    if mtf_penalty < 1.0:
        logger.info(f"[MTF-RSI/{d.upper()}] {mtf_penalty_reason}")

    exhaustion_mult = 1.0; exhaustion_reason = None
    if regime_name == "EXPLOSIVE":
        if d == "long" and rsi_1h >= config.EXPLOSIVE_EXHAUSTION_RSI_LONG:
            exhaustion_mult = config.EXPLOSIVE_EXHAUSTION_PENALTY
            exhaustion_reason = f"EXPLOSIVE 소진(4h RSI:{rsi_1h:.1f}) → 롱 ×{exhaustion_mult}"
        elif d == "short" and rsi_1h <= config.EXPLOSIVE_EXHAUSTION_RSI_SHORT:
            exhaustion_mult = config.EXPLOSIVE_EXHAUSTION_PENALTY
            exhaustion_reason = f"EXPLOSIVE 소진(4h RSI:{rsi_1h:.1f}) → 숏 ×{exhaustion_mult}"
    if exhaustion_mult < 1.0:
        logger.info(f"[EXPLOSIVE소진/{d.upper()}] {exhaustion_reason}")

    # EXPLOSIVE 준과매도/과매수
    explosive_oversold_mult = 1.0
    if regime_name == "EXPLOSIVE":
        _pct_b_p1 = bb.get("pct_b", 0.5)
        if (d == "short" and rsi_1h < config.EXPLOSIVE_OVERSOLD_GUARD_RSI and
                _pct_b_p1 < config.EXPLOSIVE_OVERSOLD_GUARD_BB):
            explosive_oversold_mult = config.EXPLOSIVE_OVERSOLD_PENALTY
            logger.info(f"[EXPLOSIVE준과매도/{d.upper()}] 4h RSI:{rsi_1h:.0f} + %B:{_pct_b_p1:.2f} → ×{explosive_oversold_mult:.2f}")
        elif (d == "long" and rsi_1h > config.EXPLOSIVE_OVERBOUGHT_GUARD_RSI and
                _pct_b_p1 > config.EXPLOSIVE_OVERBOUGHT_GUARD_BB):
            explosive_oversold_mult = config.EXPLOSIVE_OVERSOLD_PENALTY
            logger.info(f"[EXPLOSIVE준과매수/{d.upper()}] 4h RSI:{rsi_1h:.0f} + %B:{_pct_b_p1:.2f} → ×{explosive_oversold_mult:.2f}")

    # 청산 역방향
    liq_reverse_mult = 1.0
    _liq_fav = liq.get("favorable_direction")
    if _liq_fav is not None and _liq_fav != d and liq.get("signal", "none") != "none":
        liq_reverse_mult = config.LIQ_REVERSE_PENALTY
        logger.info(f"[청산역방향/{d.upper()}] 청산유리:{_liq_fav} ≠ 진입:{d} → ×{liq_reverse_mult:.2f}")

    # BB 연속 이탈 억제
    BB_STREAK    = 3
    lower_streak = bb.get("lower_streak", 0)
    upper_streak = bb.get("upper_streak", 0)
    bb_suppressed = False; bb_reason = None

    if d == "long" and lower_streak >= BB_STREAK and regime_name == "TRENDING":
        if rsi_val_15m <= config.BB_STREAK_SUPPRESS_RSI_EXEMPT:
            logger.info(f"[BB억제면제/{d.upper()}] RSI극단({rsi_val_15m:.0f}) → 억제 해제")
        else:
            bb_suppressed = True
            bb_reason = f"TRENDING BB 하단 {lower_streak}캔들 연속 이탈 — 롱 억제"
    elif d == "short" and upper_streak >= BB_STREAK and regime_name == "TRENDING":
        if rsi_val_15m >= (100 - config.BB_STREAK_SUPPRESS_RSI_EXEMPT):
            logger.info(f"[BB억제면제/{d.upper()}] RSI극단({rsi_val_15m:.0f}) → 억제 해제")
        else:
            bb_suppressed = True
            bb_reason = f"TRENDING BB 상단 {upper_streak}캔들 연속 이탈 — 숏 억제"

    if bb_suppressed:
        logger.info(f"[Score/{d.upper()}] ⛔ {bb_reason}")
        return {
            "direction": d, "final_score": 0.0, "raw_score": round(raw_score, 2),
            "weighted_score": 0.0, "ema_multiplier": ema_mult, "adx_multiplier": 1.0,
            "passed_gate": True, "signal": False, "component_scores": scores,
            "bonuses": [], "bonus_total": 0, "gate_info": gate,
            "bb_suppressed": True, "bb_suppress_reason": bb_reason, "regime": regime,
            "breakdown": "⛔ BB 연속 이탈 억제", "volume_penalty": 0, "explosive_bos_penalty": 1.0,
        }

    # ══════════════════════════════════════════════════════════
    # CHoCH / BOS 패널티 사전 계산 (1h + 4h)
    # ══════════════════════════════════════════════════════════
    bos_choch_data = analysis.get("bos_choch", {})

    # 1h CHoCH
    choch_penalty = 1.0
    if d == "long"  and bos_choch_data.get("choch_bearish"):
        choch_penalty = config.CHOCH_AGAINST_PENALTY
        logger.info(f"[1h-CHoCH/{d.upper()}] ⚠️ 1h 하락전환 중 롱 → ×{choch_penalty}")
    elif d == "short" and bos_choch_data.get("choch_bullish"):
        choch_penalty = config.CHOCH_AGAINST_PENALTY
        logger.info(f"[1h-CHoCH/{d.upper()}] ⚠️ 1h 상승전환 중 숏 → ×{choch_penalty}")

    # 1h BOS
    bos_conflict_penalty = 1.0
    if d == "long"  and bos_choch_data.get("bos_bearish"):
        bos_conflict_penalty = config.BOS_CONFLICT_PENALTY
        logger.info(f"[1h-BOS/{d.upper()}] ⚠️ 1h 하락 BOS → 역추세 롱 ×{bos_conflict_penalty}")
    elif d == "short" and bos_choch_data.get("bos_bullish"):
        bos_conflict_penalty = config.BOS_CONFLICT_PENALTY
        logger.info(f"[1h-BOS/{d.upper()}] ⚠️ 1h 상승 BOS → 역추세 숏 ×{bos_conflict_penalty}")

    # [v2.0 ③] 4h CHoCH 패널티 (×0.80, 1h보다 강함)
    choch_4h_penalty = 1.0
    if d == "long"  and bos_choch_4h.get("choch_bearish"):
        choch_4h_penalty = config.CHOCH_4H_AGAINST_PENALTY
        logger.info(f"[4h-CHoCH/{d.upper()}] ⚠️ 4h 하락전환 중 롱 → ×{choch_4h_penalty} (강화)")
    elif d == "short" and bos_choch_4h.get("choch_bullish"):
        choch_4h_penalty = config.CHOCH_4H_AGAINST_PENALTY
        logger.info(f"[4h-CHoCH/{d.upper()}] ⚠️ 4h 상승전환 중 숏 → ×{choch_4h_penalty} (강화)")

    # [v2.0 ③] 4h BOS 패널티 (×0.78, 1h보다 강함)
    bos_4h_conflict_penalty = 1.0
    if d == "long"  and bos_choch_4h.get("bos_bearish"):
        bos_4h_conflict_penalty = config.BOS_4H_CONFLICT_PENALTY
        logger.info(f"[4h-BOS/{d.upper()}] ⚠️ 4h 하락 BOS 확증 → ×{bos_4h_conflict_penalty} (강화)")
    elif d == "short" and bos_choch_4h.get("bos_bullish"):
        bos_4h_conflict_penalty = config.BOS_4H_CONFLICT_PENALTY
        logger.info(f"[4h-BOS/{d.upper()}] ⚠️ 4h 상승 BOS 확증 → ×{bos_4h_conflict_penalty} (강화)")

    # ══════════════════════════════════════════════════════════
    # 보너스 계산
    # ══════════════════════════════════════════════════════════
    bonuses = []

    # ① 극단 과매도/과매수
    if is_extreme_oversold:
        bonuses.append(("멀티TF극단과매도", config.BONUS_EXTREME_OVERSOLD_MTF))
    elif is_extreme_overbought:
        bonuses.append(("멀티TF극단과매수", config.BONUS_EXTREME_OVERSOLD_MTF))

    # ② 볼린저 극단 + RSI 다이버전스
    bb_extreme = bb_state_str in ("lower_breakout","near_lower","upper_breakout","near_upper")
    has_div    = rsi.get("bullish_divergence") if d == "long" else rsi.get("bearish_divergence")
    _div_rsi_ok = ((d=="long" and rsi_val_15m<=38) or (d=="short" and rsi_val_15m>=65))
    if bb_extreme and has_div and _div_rsi_ok:
        bonuses.append(("볼린저극단+RSI다이버전스", config.BONUS_BB_RSI_ALIGN))
    elif bb_extreme and has_div:
        logger.info(f"[볼린저Div/{d.upper()}] RSI:{rsi_val_15m:.0f} 극단조건 미충족 → 보너스 미지급")

    # ③ 펀딩비 + 롱숏비율 동일 방향
    fr_bias = funding.get("bias","neutral"); ls_bias = ls.get("bias","neutral")
    fr_ok = (fr_bias == "long_favorable"  if d=="long"  else fr_bias == "short_favorable")
    ls_ok = (ls_bias in ("long_favorable","long_extreme")   if d=="long"  else
             ls_bias in ("short_favorable","short_extreme"))
    if fr_ok and ls_ok:
        bonuses.append(("펀딩비+롱숏비율", config.BONUS_FUNDING_LS_ALIGN))

    # ④ 대규모 청산
    liq_signal  = liq.get("signal","none"); liq_large = liq.get("is_large",False)
    liq_api_fired = (micro_result is not None and
        any(name=="LiqCascade" and p<0 for name,p,_ in micro_result.get("details",[])))
    if liq_api_fired:
        logger.info(f"[청산프록시/{d.upper()}] API 패널티 우선 → 청산보너스 억제")
    elif liq_large and (
        (d=="long"  and liq_signal=="long_liq_detected") or
        (d=="short" and liq_signal=="short_liq_detected")
    ):
        if _bos_reverse_pre:
            logger.info(f"[청산보너스/{d.upper()}] BOS역방향 → 청산꼬리보너스 억제")
        else:
            bonuses.append(("대규모청산꼬리", config.BONUS_LIQUIDATION))

    # ⑤ 추세 지속
    ema_same   = ema_info.get("same_count",0)
    taker_bias = taker.get("bias","neutral"); taker_str = taker.get("strength","neutral")
    trend_strong_ok = (ema_same==3 and taker_str in ("strong","mild") and (
        (d=="long"  and taker_bias=="buy_dominant") or
        (d=="short" and taker_bias=="sell_dominant")))
    if trend_strong_ok:
        bonuses.append((f"추세지속:EMA+Taker({'롱' if d=='long' else '숏'})", config.BONUS_TREND_STRONG))

    # ⑥ 눌림목
    pb_ok_strong = (
        (d=="long"  and rsi.get("pullback_long_strong",False)  and ema_same>=2) or
        (d=="short" and rsi.get("pullback_short_strong",False) and ema_same>=2))
    pb_ok_weak = (
        (d=="long"  and rsi.get("pullback_long_weak",False)   and not rsi.get("pullback_long_strong")  and ema_same>=2) or
        (d=="short" and rsi.get("pullback_short_weak",False)  and not rsi.get("pullback_short_strong") and ema_same>=2))
    pb_ok_micro = (
        (d=="long"  and rsi.get("pullback_long_micro",False)  and not pb_ok_strong and not pb_ok_weak and ema_same>=1) or
        (d=="short" and rsi.get("pullback_short_micro",False) and not pb_ok_strong and not pb_ok_weak and ema_same>=1))
    if pb_ok_strong:
        bonuses.append((f"눌림목강({d.upper()})", config.BONUS_PULLBACK_ENTRY))
    elif pb_ok_weak:
        bonuses.append((f"눌림목약({d.upper()})", config.BONUS_PULLBACK_ENTRY_WEAK))
    elif pb_ok_micro:
        bonuses.append((f"눌림목미세({d.upper()})", config.BONUS_PULLBACK_ENTRY_MICRO))

    # ⑦ 거래량-가격 다이버전스
    vpd = analysis.get("vol_price_div",{})
    _vpd_mult = 0.60 if regime_name=="RANGING" else 1.0
    if d=="short" and vpd.get("bearish_vol_div"):
        bonuses.append(("거래량약세다이버전스", round(config.BONUS_VOL_PRICE_DIV*_vpd_mult)))
    elif d=="long" and vpd.get("bullish_vol_div"):
        bonuses.append(("거래량강세다이버전스", round(config.BONUS_VOL_PRICE_DIV*_vpd_mult)))

    # ⑧ 돌파/붕괴 실패 + 구조
    ms = analysis.get("market_structure",{})
    _struct_eligible = regime_name not in ("RANGING","SQUEEZE")
    if d=="short":
        if ms.get("failed_breakout"): bonuses.append(("돌파실패", config.BONUS_FAILED_BREAKOUT))
        if ms.get("lower_high"):
            if _struct_eligible: bonuses.append(("LowerHigh구조", config.BONUS_MARKET_STRUCT_TREND))
    elif d=="long":
        if ms.get("failed_breakdown"): bonuses.append(("붕괴실패", config.BONUS_FAILED_BREAKOUT))
        if ms.get("higher_low"):
            if _struct_eligible: bonuses.append(("HigherLow구조", config.BONUS_MARKET_STRUCT_TREND))

    # ⑨ FVG
    fvg      = analysis.get("fvg",{})
    bull_fvg = fvg.get("in_bullish_fvg",False); bear_fvg = fvg.get("in_bearish_fvg",False)
    both_fvg = bull_fvg and bear_fvg
    fvg_val  = config.BONUS_FVG_ENTRY_CONFLICTED if both_fvg else config.BONUS_FVG_ENTRY
    if both_fvg:
        bonuses.append((f"FVG{'강세' if d=='long' else '약세'}진입(모호)", fvg_val))
    elif d=="long"  and bull_fvg: bonuses.append(("FVG강세진입", fvg_val))
    elif d=="short" and bear_fvg: bonuses.append(("FVG약세진입", fvg_val))

    # ⑩-a 1h BOS 확증
    if d=="long"  and bos_choch_data.get("bos_bullish"):
        bonuses.append(("1h-BOS상승확증", config.BONUS_BOS_CONFIRM))
        logger.info(f"[1h-BOS] ★ 1h 상승 BOS +{config.BONUS_BOS_CONFIRM}pt")
    elif d=="short" and bos_choch_data.get("bos_bearish"):
        bonuses.append(("1h-BOS하락확증", config.BONUS_BOS_CONFIRM))
        logger.info(f"[1h-BOS] ★ 1h 하락 BOS +{config.BONUS_BOS_CONFIRM}pt")

    # [v2.0 ③] ⑩-b 4h BOS 확증 (1h보다 강한 신호, +12pt)
    if d=="long"  and bos_choch_4h.get("bos_bullish"):
        bonuses.append(("4h-BOS상승확증", config.BONUS_BOS_CONFIRM_4H))
        logger.info(f"[4h-BOS] ★★ 4h 상승 BOS +{config.BONUS_BOS_CONFIRM_4H}pt (강화)")
    elif d=="short" and bos_choch_4h.get("bos_bearish"):
        bonuses.append(("4h-BOS하락확증", config.BONUS_BOS_CONFIRM_4H))
        logger.info(f"[4h-BOS] ★★ 4h 하락 BOS +{config.BONUS_BOS_CONFIRM_4H}pt (강화)")

    # ⑪ 피보나치
    fibonacci = analysis.get("fibonacci",{})
    if d=="long":
        if fibonacci.get("in_golden_pocket_long"):   bonuses.append(("피보황금포켓롱", config.BONUS_FIB_GOLDEN_POCKET))
        elif fibonacci.get("near_key_level_long"):   bonuses.append(("피보주요레벨롱", config.BONUS_FIB_KEY_LEVEL))
    elif d=="short":
        if fibonacci.get("in_golden_pocket_short"):  bonuses.append(("피보황금포켓숏", config.BONUS_FIB_GOLDEN_POCKET))
        elif fibonacci.get("near_key_level_short"):  bonuses.append(("피보주요레벨숏", config.BONUS_FIB_KEY_LEVEL))

    # ⑫ 히든 다이버전스
    hidden_bull = rsi.get("hidden_bull_div",False); hidden_bear = rsi.get("hidden_bear_div",False)
    _hidden_adx = adx_15m.get("adx",0.0)
    _hidden_div_eligible = not (regime_name in ("RANGING","SQUEEZE") and _hidden_adx < config.HIDDEN_DIV_MIN_ADX)
    if d=="long" and hidden_bull:
        if _hidden_div_eligible: bonuses.append(("히든강세다이버전스", config.BONUS_HIDDEN_DIVERGENCE))
    elif d=="short" and hidden_bear:
        if _hidden_div_eligible: bonuses.append(("히든약세다이버전스", config.BONUS_HIDDEN_DIVERGENCE))

    # ⑬ 캔들 패턴
    candle = analysis.get("candle_pattern",{})
    if d=="short":
        if candle.get("bearish_pin"):      bonuses.append(("베어리시핀바",   config.BONUS_CANDLE_PIN_BAR))
        elif candle.get("bearish_engulf"): bonuses.append(("베어리시인걸핑", config.BONUS_CANDLE_ENGULFING))
    elif d=="long":
        if candle.get("bullish_pin"):      bonuses.append(("불리시핀바",     config.BONUS_CANDLE_PIN_BAR))
        elif candle.get("bullish_engulf"): bonuses.append(("불리시인걸핑",   config.BONUS_CANDLE_ENGULFING))

    # ⑭ 거래량 폭발
    vol_ratio = vol.get("ratio",1.0); adx_val = adx_15m.get("adx",0.0)
    if vol_ratio >= config.VOLUME_EXPLOSION_MULTIPLIER and adx_val >= 22.0 and ema_same < 3:
        bonuses.append(("거래량폭발", config.BONUS_VOLUME_EXPLOSION))

    # ⑮ Post-Squeeze 모멘텀
    prev_regime   = analysis.get("prev_regime","")
    bb_just_broke = (
        (d=="long"  and bb_state_str in ("upper_breakout","near_upper") and bb.get("upper_streak",0)==1) or
        (d=="short" and bb_state_str in ("lower_breakout","near_lower") and bb.get("lower_streak",0)==1))
    if (prev_regime=="SQUEEZE" or regime_name=="EXPLOSIVE") and bb_just_broke:
        bonuses.append(("Post-Squeeze롱돌파" if d=="long" else "Post-Squeeze숏돌파", config.BONUS_POST_SQUEEZE))

    # ── 소진 상태에서 추세확인형 보너스 제거 ────────────────────
    if exhaustion_mult < 1.0:
        tc = {"LowerHigh구조","HigherLow구조","거래량약세다이버전스","거래량강세다이버전스",
              "볼린저극단+RSI다이버전스","1h-BOS상승확증","1h-BOS하락확증",
              "4h-BOS상승확증","4h-BOS하락확증"}
        removed = [(n,v) for n,v in bonuses if n in tc]
        bonuses = [(n,v) for n,v in bonuses if n not in tc]
        if removed: logger.info(f"[소진보너스제거] {[n for n,_ in removed]}")

    # ── EMA 3역방향 시 반전 보너스 감산 ─────────────────────────
    _REV = {"거래량강세다이버전스","거래량약세다이버전스","볼린저극단+RSI다이버전스"}
    if ema_all_reverse and not bb_reversal_exempt:
        bonuses = [(n, round(v*0.25) if n in _REV else v) for n,v in bonuses]

    # ── Taker 역방향 시 캔들 보너스 감산 ────────────────────────
    _CANDLE = {"불리시핀바","베어리시핀바","불리시인걸핑","베어리시인걸핑"}
    _taker_against = ((d=="long" and taker.get("bias")=="sell_dominant") or
                      (d=="short" and taker.get("bias")=="buy_dominant"))
    if _taker_against:
        bonuses = [(n, round(v*0.40) if n in _CANDLE else v) for n,v in bonuses]

    # ── SQUEEZE 국면 캔들 보너스 감액 ───────────────────────────
    if regime_name == "SQUEEZE":
        _sq = [(n,v) for n,v in bonuses if n in _CANDLE]
        if _sq:
            bonuses = [(n, round(v*config.SQUEEZE_CANDLE_BONUS_MULT) if n in _CANDLE else v) for n,v in bonuses]

    # ── 저유동성 구조 패턴 보너스 억제 ──────────────────────────
    _LOW_VOL_STRUCT = {"LowerHigh구조","HigherLow구조","돌파실패","붕괴실패",
                       "거래량강세다이버전스","거래량약세다이버전스","볼린저극단+RSI다이버전스"}
    vol_score_struct = vol.get("score",50.0)
    if vol_score_struct < config.VOLUME_PENALTY_MID_THRESHOLD:
        affected = [(n,v) for n,v in bonuses if n in _LOW_VOL_STRUCT]
        if affected:
            bonuses = [(n, round(v*0.5) if n in _LOW_VOL_STRUCT else v) for n,v in bonuses]
            logger.info(f"[저유동성/{d.upper()}] 구조패턴 보너스 50% 감산")

    # ── 역추세 보너스 캡 / 티어드 캡 ─────────────────────────────
    bonus_raw = sum(v for _,v in bonuses)
    # [v2.0] 4h BOS 역방향도 역추세 캡 조건에 포함
    _any_bos_conflict = (bos_conflict_penalty < 1.0 or bos_4h_conflict_penalty < 1.0)
    apply_counter_cap = (_any_bos_conflict and ema_all_reverse and not bb_reversal_exempt)
    if apply_counter_cap:
        bonus_cap   = config.COUNTER_TREND_BONUS_CAP
        bonus_total = min(bonus_cap, bonus_raw)
    elif _any_bos_conflict:
        bonus_cap   = config.BOS_ONLY_BONUS_CAP
        bonus_total = min(bonus_cap, bonus_raw)
    else:
        bonus_cap   = _get_tiered_bonus_cap(base_score)
        bonus_total = min(bonus_cap, bonus_raw)
    if bonus_raw > bonus_cap:
        logger.info(f"[보너스캡/{d.upper()}] {bonus_raw}→{bonus_total}pt (캡:{bonus_cap}pt)")

    # ── 캔들 모멘텀 역방향 패널티 ───────────────────────────────
    candle_momentum_mult = 1.0
    if d=="short" and candle.get("consecutive_bull"):
        if regime_name=="TRENDING":    candle_momentum_mult = config.CANDLE_MOMENTUM_PENALTY_TRENDING
        elif regime_name=="EXPLOSIVE": candle_momentum_mult = config.CANDLE_MOMENTUM_PENALTY_EXPLOSIVE
        else:                          candle_momentum_mult = config.CANDLE_MOMENTUM_PENALTY_RANGING
    elif d=="long" and candle.get("consecutive_bear"):
        bb_lower_exempt = (bb_state_str in ("lower_breakout","near_lower") or bb.get("pct_b",0.5)<=0.15)
        if not bb_lower_exempt:
            if regime_name=="TRENDING":    candle_momentum_mult = config.CANDLE_MOMENTUM_PENALTY_TRENDING
            elif regime_name=="EXPLOSIVE": candle_momentum_mult = config.CANDLE_MOMENTUM_PENALTY_EXPLOSIVE
            else:                          candle_momentum_mult = config.CANDLE_MOMENTUM_PENALTY_RANGING

    # EXPLOSIVE + 1h BOS 역방향 강화 패널티
    explosive_bos_penalty = 1.0
    if regime_name=="EXPLOSIVE" and bos_conflict_penalty < 1.0:
        explosive_bos_penalty = config.EXPLOSIVE_BOS_CONFLICT_PENALTY

    # 거래량 패널티
    vol_score = vol.get("score",50.0)
    if vol_score < config.VOLUME_PENALTY_LOW_THRESHOLD:
        volume_penalty = config.VOLUME_PENALTY_LOW
    elif vol_score < config.VOLUME_PENALTY_MID_THRESHOLD:
        volume_penalty = config.VOLUME_PENALTY_MID
    else:
        volume_penalty = 0

    # 저ADX + BOS 역방향 추가 패널티
    ranging_bos_weak_penalty = 1.0
    _adx_cur = adx_15m.get("adx",0.0)
    if (_any_bos_conflict and _adx_cur < config.ADX_BOS_COUNTER_THRESHOLD and regime_name=="RANGING"):
        ranging_bos_weak_penalty = 0.90
        logger.info(f"[저ADX+BOS역방향/{d.upper()}] ADX:{_adx_cur:.0f} RANGING → ×0.90")

    # ── 최종 soft_penalty (1h + 4h 패널티 통합) ─────────────────
    soft_penalty = (
        mtf_penalty          *
        exhaustion_mult      *
        explosive_oversold_mult *
        liq_reverse_mult     *
        candle_momentum_mult *
        choch_penalty        *   # 1h CHoCH
        choch_4h_penalty     *   # [v2.0 ③] 4h CHoCH
        bos_conflict_penalty *   # 1h BOS
        bos_4h_conflict_penalty * # [v2.0 ③] 4h BOS
        ranging_bos_weak_penalty *
        explosive_bos_penalty
    )
    micro_penalty = micro_result.get("total_penalty",0) if micro_result else 0

    final_score = round(min(100.0, max(0.0,
        (base_score + bonus_total) * soft_penalty + micro_penalty + volume_penalty
    )), 2)

    # ══════════════════════════════════════════════════════════
    # 임계값 계산 (순서대로 적용)
    # ══════════════════════════════════════════════════════════
    regime_threshold = regime.get("threshold", config.REGIME_THRESHOLDS.get("TRENDING", 64))

    # BB 스퀴즈 +2pt
    if bb.get("squeeze",False) and regime_threshold < 66:
        regime_threshold = min(66, regime_threshold + 2)
        logger.info(f"[BB스퀴즈임계/{d.upper()}] +2pt = {regime_threshold}pt")

    # ADX 연동 역추세 임계값 조정
    if ema_all_reverse and not bb_reversal_exempt:
        adx_val_ct = adx_15m.get("adx",0.0)
        if   adx_val_ct >= config.ADX_COUNTER_TREND_THRESHOLD_STRONG: ct_boost = config.ADX_COUNTER_TREND_BOOST_STRONG
        elif adx_val_ct >= config.ADX_COUNTER_TREND_THRESHOLD_MID:    ct_boost = config.ADX_COUNTER_TREND_BOOST_MID
        elif adx_val_ct >= config.ADX_COUNTER_TREND_THRESHOLD_WEAK:   ct_boost = config.ADX_COUNTER_TREND_BOOST_WEAK
        else:                                                          ct_boost = 0
        if ct_boost > 0:
            regime_threshold = min(85, regime_threshold + ct_boost)
            logger.info(f"[ADX역추세/{d.upper()}] ADX:{adx_val_ct:.0f} → +{ct_boost}pt = {regime_threshold}pt")

    # [v2.0 ①] 4h 메타 레짐 임계값 조정
    meta_adj = config.META_REGIME_THRESHOLD_ADJ.get((regime_4h_name, regime_name), 0)
    if meta_adj != 0:
        regime_threshold = min(88, max(52, regime_threshold + meta_adj))
        logger.info(
            f"[메타레짐/{d.upper()}] 4h:{regime_4h_name} × 1h:{regime_name} "
            f"→ {'+' if meta_adj>0 else ''}{meta_adj}pt = {regime_threshold}pt"
        )

    # [v2.0 ②] 일봉 바이어스 임계값 조정
    bias_adj = daily_bias.get(f"threshold_adj_{d}", 0)
    bias_name = daily_bias.get("bias", "NEUTRAL")
    if bias_adj != 0:
        regime_threshold = min(90, max(52, regime_threshold + bias_adj))
        logger.info(
            f"[일봉바이어스/{d.upper()}] {bias_name} → "
            f"{'+' if bias_adj>0 else ''}{bias_adj}pt = {regime_threshold}pt"
        )

    # [v2.0 ④] 거래 세션 임계값 조정
    session_adj = _get_session_threshold_adj()
    if session_adj != 0:
        regime_threshold = min(90, max(52, regime_threshold + session_adj))
        logger.info(
            f"[세션필터/{d.upper()}] → {'+' if session_adj>0 else ''}{session_adj}pt = {regime_threshold}pt"
        )

    # [v2.0 ⑦] 펀딩비 8h 사이클 임계값 조정
    funding_cycle_adj = _get_funding_cycle_adj()
    if funding_cycle_adj != 0:
        regime_threshold = min(90, regime_threshold + funding_cycle_adj)
        logger.info(f"[펀딩사이클/{d.upper()}] 정산±1h 구간 → +{funding_cycle_adj}pt = {regime_threshold}pt")

    signal = (final_score >= regime_threshold)

    # FVG 양방향 모호 + 저거래량 차단
    if signal and both_fvg and vol_score < config.FVG_AMBIGUOUS_VOL_THRESHOLD:
        signal = False
        logger.info(f"[FVG모호+저거래량/{d.upper()}] 신호 차단")

    # ── 로그 ─────────────────────────────────────────────────
    soft_applied = soft_penalty < 1.0
    _thr_adjs = []
    if meta_adj != 0:          _thr_adjs.append(f"메타레짐{'+' if meta_adj>0 else ''}{meta_adj}")
    if bias_adj != 0:          _thr_adjs.append(f"바이어스{'+' if bias_adj>0 else ''}{bias_adj}")
    if session_adj != 0:       _thr_adjs.append(f"세션{'+' if session_adj>0 else ''}{session_adj}")
    if funding_cycle_adj != 0: _thr_adjs.append(f"펀딩사이클+{funding_cycle_adj}")
    _thr_note = f" [{','.join(_thr_adjs)}]" if _thr_adjs else ""

    logger.info(
        f"[Score/{d.upper()}] [{regime_name}|4h:{regime_4h_name}|{bias_name}]"
        f" raw:{raw_score:.1f} ×EMA{ema_mult:.2f}"
        + (f" ×게이트{gate_penalty:.2f}" if gate_penalty < 1.0 else "")
        + f" +보너스{bonus_total}[cap:{bonus_cap}]"
        + (f" ×soft{soft_penalty:.3f}" if soft_applied else "")
        + (f" +micro{micro_penalty:+d}" if micro_penalty else "")
        + (f" +vol{volume_penalty:+d}"  if volume_penalty else "")
        + f" = {final_score:.1f}pt (임계:{regime_threshold}pt{_thr_note})"
        + (" 🚨 신호" if signal else "")
    )

    breakdown = _build_breakdown(
        d, scores, weights, raw_score, ema_mult, gate_penalty,
        mtf_penalty, exhaustion_mult, choch_penalty, bos_conflict_penalty,
        explosive_bos_penalty, candle_momentum_mult, ranging_bos_weak_penalty,
        bonuses, bonus_cap, final_score,
        gate, regime, micro_penalty, volume_penalty,
        choch_4h_penalty=choch_4h_penalty,
        bos_4h_conflict_penalty=bos_4h_conflict_penalty,
        meta_adj=meta_adj, bias_adj=bias_adj,
        session_adj=session_adj, funding_cycle_adj=funding_cycle_adj,
        regime_4h_name=regime_4h_name, bias_name=bias_name,
    )

    return {
        "direction": d, "final_score": final_score, "raw_score": round(raw_score,2),
        "weighted_score": round(base_score,2), "ema_multiplier": ema_mult, "adx_multiplier": 1.0,
        "passed_gate": True, "signal": signal, "component_scores": scores,
        "bonuses": bonuses, "bonus_total": bonus_total, "bonus_cap": bonus_cap, "gate_info": gate,
        "bb_suppressed": False, "bb_suppress_reason": None, "regime": regime,
        "regime_threshold": regime_threshold, "breakdown": breakdown,
        "mtf_penalty": mtf_penalty, "exhaustion_mult": exhaustion_mult,
        "explosive_oversold_mult": explosive_oversold_mult,
        "liq_reverse_mult": liq_reverse_mult,
        "candle_momentum_mult": candle_momentum_mult, "choch_penalty": choch_penalty,
        "choch_4h_penalty": choch_4h_penalty,          # [v2.0]
        "bos_conflict_penalty": bos_conflict_penalty,
        "bos_4h_conflict_penalty": bos_4h_conflict_penalty,  # [v2.0]
        "explosive_bos_penalty": explosive_bos_penalty,
        "ranging_bos_weak_penalty": ranging_bos_weak_penalty,
        "volume_penalty": volume_penalty,
        "meta_adj": meta_adj, "bias_adj": bias_adj,    # [v2.0]
        "session_adj": session_adj,                     # [v2.0]
        "funding_cycle_adj": funding_cycle_adj,         # [v2.0]
    }


def _build_breakdown(d, scores, weights, raw, ema_m, pen,
                     mtf_m, exh_m, choch_m, bos_m, exp_bos_m,
                     candle_m, ranging_bos_m,
                     bonuses, bonus_cap, final, gate, regime,
                     micro_penalty=0, volume_penalty=0,
                     choch_4h_penalty=1.0, bos_4h_conflict_penalty=1.0,
                     meta_adj=0, bias_adj=0, session_adj=0, funding_cycle_adj=0,
                     regime_4h_name="UNKNOWN", bias_name="NEUTRAL") -> str:
    label = "🟢 롱" if d == "long" else "🔴 숏"
    r4h   = f" | 4h:{regime_4h_name} | 바이어스:{bias_name}"
    lines = [f"{label} 진입 점수  [{regime.get('icon','')} {regime.get('regime','')}]{r4h}"]
    for key, weight in weights.items():
        s = scores.get(key,0.0); contrib = s * weight
        bar = "█"*int(s/10) + "░"*(10-int(s/10))
        lines.append(f"  {_score_label(key):<14} {bar} {s:>5.1f}pt × {weight:.0%} = {contrib:>4.1f}pt")
    lines.append(f"  {'─'*46}")
    lines.append(f"  가중합                           {raw:>5.1f}pt")
    if ema_m       < 1.0: lines.append(f"  EMA 역방향 배율         × {ema_m:.2f}")
    if pen         < 1.0: lines.append(f"  복합 페널티             × {pen:.2f}")
    if mtf_m       < 1.0: lines.append(f"  MTF RSI 패널티          × {mtf_m:.2f}")
    if exh_m       < 1.0: lines.append(f"  EXPLOSIVE 소진 패널티   × {exh_m:.2f}")
    if candle_m    < 1.0: lines.append(f"  캔들모멘텀 역방향       × {candle_m:.2f}")
    if choch_m     < 1.0: lines.append(f"  1h-CHoCH 역방향         × {choch_m:.2f}")
    if choch_4h_penalty < 1.0: lines.append(f"  4h-CHoCH 역방향(강화)  × {choch_4h_penalty:.2f}")
    if bos_m       < 1.0: lines.append(f"  1h-BOS 역방향           × {bos_m:.2f}")
    if bos_4h_conflict_penalty < 1.0: lines.append(f"  4h-BOS 역방향(강화)    × {bos_4h_conflict_penalty:.2f}")
    if exp_bos_m   < 1.0: lines.append(f"  EXPLOSIVE+BOS 강화      × {exp_bos_m:.2f}")
    if ranging_bos_m < 1.0: lines.append(f"  저ADX+BOS역방향        × {ranging_bos_m:.2f}")
    if bonuses:
        lines.append(f"  보너스 (상한:{bonus_cap}pt):")
        for name, val in bonuses:
            lines.append(f"    + {name}: +{val}pt")
    if micro_penalty   != 0: lines.append(f"  마이크로구조             {micro_penalty:+d}pt")
    if volume_penalty  != 0: lines.append(f"  거래량 페널티            {volume_penalty:+d}pt")
    lines.append(f"  {'─'*46}")
    # 임계값 조정 요약
    base_thr = regime.get("threshold", 64)
    adj_parts = []
    if meta_adj != 0:          adj_parts.append(f"메타레짐{'+' if meta_adj>0 else ''}{meta_adj}")
    if bias_adj != 0:          adj_parts.append(f"바이어스{'+' if bias_adj>0 else ''}{bias_adj}")
    if session_adj != 0:       adj_parts.append(f"세션{'+' if session_adj>0 else ''}{session_adj}")
    if funding_cycle_adj != 0: adj_parts.append(f"펀딩사이클+{funding_cycle_adj}")
    if adj_parts:
        lines.append(f"  임계값 기본:{base_thr}pt → 조정:[{', '.join(adj_parts)}]")
    lines.append(f"  최종 (임계:{regime.get('threshold',64)}pt 조정후)  {final:>5.1f}pt")
    return "\n".join(lines)


def _score_label(key: str) -> str:
    return {
        "rsi": "RSI", "bollinger": "볼린저밴드", "funding_rate": "펀딩비",
        "long_short_ratio": "롱숏비율", "taker_volume": "Taker비율", "volume": "거래량",
    }.get(key, key)


def evaluate_signals(analysis: dict,
                     micro_long: dict = None,
                     micro_short: dict = None) -> dict:
    lr = calculate_entry_score(analysis, "long",  micro_long)
    sr = calculate_entry_score(analysis, "short", micro_short)
    ls = lr["final_score"]; ss = sr["final_score"]
    primary = None; suppressed = None

    if lr["signal"] and sr["signal"]:
        if abs(ls-ss) < 5.0: suppressed = f"양방향 차이 {abs(ls-ss):.1f}pt < 5pt"
        else:                 primary = "long" if ls > ss else "short"
    elif lr["signal"]: primary = "long"
    elif sr["signal"]: primary = "short"

    ps = ls if primary=="long" else (ss if primary=="short" else 0.0)
    if primary: logger.info(f"[Signal] 🚨 {primary.upper()} {ps:.1f}pt")
    else:       logger.info(f"[Signal] 없음 — 롱:{ls:.1f} 숏:{ss:.1f}")
    return {"long": lr, "short": sr, "primary": primary, "primary_score": ps, "suppressed": suppressed}


# ══════════════════════════════════════════════
# 상태 파일 (쿨다운 / 이전 국면)
# ══════════════════════════════════════════════

def _load_state() -> dict:
    if os.path.exists(config.SIGNAL_STATE_FILE):
        try:
            with open(config.SIGNAL_STATE_FILE) as f: return json.load(f)
        except: pass
    return {}

def _save_state(state: dict) -> None:
    try:
        d = os.path.dirname(config.SIGNAL_STATE_FILE)
        if d: os.makedirs(d, exist_ok=True)
        with open(config.SIGNAL_STATE_FILE,"w") as f: json.dump(state,f)
    except Exception as e: logger.warning(f"[Cooldown] 저장 실패: {e}")

def _get_effective_cooldown(symbol: str, direction: str, current_price: float) -> int:
    state = _load_state()
    last_price = state.get(f"{symbol}_{direction}_last_price", 0)
    if not last_price: return config.SIGNAL_COOLDOWN_MINUTES
    change_pct = (current_price - last_price) / last_price
    directional_move = change_pct if direction=="long" else -change_pct
    if directional_move >= config.PRICE_MOVE_SUPPRESS_STRONG: return config.COOLDOWN_SUPPRESSED_STRONG
    if directional_move >= config.PRICE_MOVE_SUPPRESS_MILD:   return config.COOLDOWN_SUPPRESSED_MILD
    if directional_move <= config.PRICE_MOVE_RESET_THRESHOLD: return 0
    return config.SIGNAL_COOLDOWN_MINUTES

def is_in_cooldown(symbol: str, direction: str, current_price: float = 0.0) -> bool:
    state = _load_state()
    last  = state.get(f"{symbol}_{direction}")
    if last is None: return False
    effective_minutes = _get_effective_cooldown(symbol, direction, current_price)
    if effective_minutes == 0: return False
    elapsed  = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    cooldown = timedelta(minutes=effective_minutes)
    if elapsed < cooldown:
        remain = int((cooldown-elapsed).total_seconds()/60)
        logger.info(f"[Cooldown] {symbol} {direction.upper()} — 잔여:{remain}분")
        return True
    return False

def record_signal_sent(symbol: str, direction: str, current_price: float = 0.0) -> None:
    state = _load_state()
    state[f"{symbol}_{direction}"] = datetime.now(timezone.utc).isoformat()
    if current_price > 0:
        state[f"{symbol}_{direction}_last_price"] = current_price
    _save_state(state)

def _load_prev_regime(symbol: str) -> str:
    return _load_state().get(f"{symbol}_prev_regime","")

def _save_prev_regime(symbol: str, regime_name: str) -> None:
    state = _load_state()
    state[f"{symbol}_prev_regime"] = regime_name
    _save_state(state)


# ══════════════════════════════════════════════
# 파이프라인
# ══════════════════════════════════════════════

def run_scoring_pipeline(symbol: str, analysis: dict,
                          market_data: dict = None) -> dict:
    import datetime as dt
    logger.info(f"{'─'*50}")
    logger.info(f"🎯 점수 산출: {symbol}")

    regime      = analysis.get("regime",{})
    regime_name = regime.get("regime","UNKNOWN")
    regime_4h   = analysis.get("regime_4h",{})
    daily_bias  = analysis.get("daily_bias",{})
    logger.info(
        f"  {regime.get('icon','')} 1h국면:{regime_name} | "
        f"4h국면:{regime_4h.get('regime','?')} | "
        f"일봉바이어스:{daily_bias.get('bias','?')} | "
        f"{regime.get('description','')}"
    )

    prev_regime = _load_prev_regime(symbol)
    if prev_regime:
        analysis["prev_regime"] = prev_regime

    micro_long  = {"total_penalty":0,"raw_total":0,"details":[],"suggested_entry":None}
    micro_short = {"total_penalty":0,"raw_total":0,"details":[],"suggested_entry":None}

    if market_data:
        try:
            from microstructure_analyzer import compute_microstructure_penalties
            micro_data    = market_data.get("microstructure",{})
            price         = market_data.get("price") or analysis.get("current_price") or 0.0
            taker_buy_pct = market_data.get("taker_volume",{}).get("buy_pct",50.0)
            pos_long_pct  = market_data.get("ls_ratio",{}).get("long_pct",0.5)
            percent_b     = analysis.get("bollinger",{}).get("pct_b",0.5)
            micro_long  = compute_microstructure_penalties(
                micro_data=micro_data, current_price=price, direction="long",
                regime=regime_name, percent_b=percent_b,
                taker_buy_pct=taker_buy_pct, position_long_pct=pos_long_pct)
            micro_short = compute_microstructure_penalties(
                micro_data=micro_data, current_price=price, direction="short",
                regime=regime_name, percent_b=percent_b,
                taker_buy_pct=taker_buy_pct, position_long_pct=pos_long_pct)
        except Exception as e:
            logger.warning(f"[Pipeline] 마이크로구조 계산 실패: {e}")

    signals = evaluate_signals(analysis, micro_long=micro_long, micro_short=micro_short)
    primary = signals["primary"]; ps = signals["primary_score"]
    current_price = analysis.get("current_price") or 0.0
    cooldown = False; should_notify = False

    if primary:
        if is_in_cooldown(symbol, primary, current_price):
            cooldown = True
        else:
            should_notify = True
            logger.info(f"[Pipeline] ✅ {symbol} {primary.upper()} {ps:.1f}pt — 알림 예정")
    else:
        logger.info(f"[Pipeline] {symbol} — 신호 없음")

    _save_prev_regime(symbol, regime_name)
    micro_result = micro_long if primary=="long" else micro_short
    return {
        "symbol":        symbol,
        "should_notify": should_notify,
        "direction":     primary,
        "score":         ps,
        "signal_result": signals,
        "cooldown_skip": cooldown,
        "regime":        regime,
        "regime_4h":     regime_4h,       # [v2.0]
        "daily_bias":    daily_bias,      # [v2.0]
        "scored_at":     dt.datetime.now(timezone.utc).isoformat(),
        "micro_result":  micro_result,
    }
