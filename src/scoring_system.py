"""
scoring_system.py — 점수 산출 (1h Bot v3.0)
────────────────────────────────────────────────────────────────────
[v3.0 신규 보너스/임계값 조정]

보너스 (scoring에 직접 적용):
  ① 스마트머니 LS 다이버전스   +8~15pt (방향 일치 시)
  ② OI 매트릭스                +3~10pt (4분면 판단)
  ③ 펀딩비 히스토리 추세       +3~8pt
  ④ 1D 캔들 패턴               +18~20pt (1h의 2배)
  ⑤ 4H 캔들 패턴               +12~14pt (1h의 1.4배)
  ⑥ 멀티TF 모멘텀 정합         +7~15pt
  ⑧ 주간 키레벨 근접            +8pt

임계값 조정 (threshold 가산):
  ⑨ 1D EMA 구조               ±5~13pt
  (v2.0 유지) 메타레짐/바이어스/세션/펀딩사이클
────────────────────────────────────────────────────────────────────
"""
import json, logging, os
from datetime import datetime, timezone, timedelta
import config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# 세션 / 펀딩사이클 헬퍼
# ══════════════════════════════════════════════════════════════════

def _get_session_threshold_adj() -> int:
    now = datetime.now(timezone.utc); h = now.hour; wd = now.weekday()
    if wd >= 5:          return config.SESSION_ADJ_WEEKEND
    if 13 <= h < 16:     return config.SESSION_ADJ_OVERLAP
    if 16 <= h < 22:     return config.SESSION_ADJ_NY
    if  7 <= h < 13:     return config.SESSION_ADJ_LONDON
    return config.SESSION_ADJ_ASIA

def _get_funding_cycle_adj() -> int:
    h = datetime.now(timezone.utc).hour
    return config.FUNDING_CYCLE_ADJ if h in config.FUNDING_CYCLE_HOURS else 0

def _get_tiered_bonus_cap(base_score: float) -> int:
    for threshold, cap in config.BONUS_CAP_TIERS:
        if base_score < threshold: return cap
    return 42


# ══════════════════════════════════════════════════════════════════
# 메인 점수 산출
# ══════════════════════════════════════════════════════════════════

def calculate_entry_score(analysis: dict, direction: str,
                           micro_result: dict = None) -> dict:
    d = direction
    gate         = analysis.get(f"gate_{d}", {})
    gate_penalty = gate.get("funding_penalty", 1.0)

    rsi      = analysis.get("rsi",           {})
    bb       = analysis.get("bollinger",      {})
    funding  = analysis.get("funding_rate",   {})
    ls       = analysis.get("ls_ratio",       {})
    taker    = analysis.get("taker_volume",   {})
    liq      = analysis.get("liquidations",   {})
    vol      = analysis.get("volume",         {})
    adx_1h   = analysis.get("adx_1h",         {})
    regime   = analysis.get("regime",          {})

    # v2.0
    bos_choch_4h   = analysis.get("bos_choch_4h",  {})
    regime_4h      = analysis.get("regime_4h",       {})
    daily_bias     = analysis.get("daily_bias",      {})
    regime_4h_name = regime_4h.get("regime", "UNKNOWN")

    # [v3.0] 신규 분석 결과
    smart_money    = analysis.get("smart_money",    {})
    oi_matrix      = analysis.get("oi_matrix",      {})
    fund_trend     = analysis.get("funding_trend",  {})
    mtf_momentum   = analysis.get("mtf_momentum",   {})
    weekly_levels  = analysis.get("weekly_levels",  {})
    ema_structure  = analysis.get("ema_structure",  {})
    candle_4h      = analysis.get("candle_pattern_4h", {})
    candle_1d      = analysis.get("candle_pattern_1d", {})

    ema_info      = analysis.get(f"ema_{d}", {})
    reverse_count = ema_info.get("reverse_count", 0)

    rsi_val_15m  = rsi.get("value",    50.0)
    rsi_val_1h   = rsi.get("value_1h", 50.0)
    rsi_val_4h   = rsi.get("value_4h", 50.0)
    bb_state_str = bb.get("state", "")
    regime_name  = regime.get("regime", "UNKNOWN")

    # ── 가중합 ───────────────────────────────────────────────
    scores = {
        "rsi":              rsi.get(f"{d}_score",     50.0),
        "bollinger":        bb.get(f"{d}_score",      50.0),
        "funding_rate":     funding.get(f"{d}_score", 50.0),
        "long_short_ratio": ls.get(f"{d}_score",      50.0),
        "taker_volume":     taker.get(f"{d}_score",   50.0),
        "volume":           vol.get("score",          50.0),
    }
    weights = config.REGIME_SCORE_WEIGHTS.get(regime_name, config.SCORE_WEIGHTS)

    bb_reversal_exempt = (
        (d=="long"  and bb_state_str=="lower_breakout") or
        (d=="short" and bb_state_str=="upper_breakout")
    )
    ema_all_reverse = (reverse_count == 3)

    if ema_all_reverse and not bb_reversal_exempt:
        scores["long_short_ratio"] = 50.0

    _bb_squeeze = bb.get("squeeze", False)
    if _bb_squeeze:
        if d=="short" and bb_state_str in ("near_upper","upper_zone","upper_breakout"):
            scores["bollinger"] = min(scores["bollinger"], 52.0)
        elif d=="long" and bb_state_str in ("near_lower","lower_zone","lower_breakout"):
            scores["bollinger"] = max(scores["bollinger"], 48.0)

    _bos_pre = analysis.get("bos_choch", {})
    _bos_reverse_pre = (
        (d=="long"  and (_bos_pre.get("bos_bearish") or bos_choch_4h.get("bos_bearish"))) or
        (d=="short" and (_bos_pre.get("bos_bullish") or bos_choch_4h.get("bos_bullish")))
    )
    if _bos_reverse_pre:
        _ls = scores["long_short_ratio"]
        if not ((d=="long" and _ls<50) or (d=="short" and _ls>50)):
            scores["long_short_ratio"] = 50.0

    raw_score = sum(scores[k] * weights[k] for k in weights)

    ema_table = config.REGIME_EMA_MULTIPLIERS.get(regime_name, config.EMA_MULTIPLIER)
    ema_mult  = ema_table.get(reverse_count, 1.0)

    is_extreme_oversold = (
        d=="long" and rsi_val_15m<=config.EXTREME_OVERSOLD_15M and
        rsi_val_1h<=config.EXTREME_OVERSOLD_1H and rsi_val_4h<=config.EXTREME_OVERSOLD_4H and
        bb_state_str in ("lower_breakout","near_lower","lower_zone")
    )
    is_extreme_overbought = (
        d=="short" and rsi_val_15m>=config.EXTREME_OVERBOUGHT_15M and
        rsi_val_1h>=config.EXTREME_OVERBOUGHT_1H and rsi_val_4h>=config.EXTREME_OVERBOUGHT_4H and
        bb_state_str in ("upper_breakout","near_upper","upper_zone")
    )

    base_score = raw_score * ema_mult * gate_penalty

    # ── soft 패널티 ──────────────────────────────────────────
    mtf_penalty = 1.0; mtf_r = None
    if d=="long":
        if rsi_val_1h>=config.MTF_RSI_OVERBOUGHT_1H_EXTREME: mtf_penalty=config.MTF_RSI_PENALTY_STRONG; mtf_r=f"4h RSI 극단과매수({rsi_val_1h:.0f})"
        elif rsi_val_1h>=config.MTF_RSI_OVERBOUGHT_1H and rsi_val_4h>=config.MTF_RSI_OVERBOUGHT_4H: mtf_penalty=config.MTF_RSI_PENALTY_STRONG; mtf_r=f"4h+1d RSI 강과매수"
        elif rsi_val_1h>=config.MTF_RSI_OVERBOUGHT_1H_MILD: mtf_penalty=config.MTF_RSI_PENALTY_MILD; mtf_r=f"4h RSI 약과매수({rsi_val_1h:.0f})"
    elif d=="short":
        if rsi_val_1h<=config.MTF_RSI_OVERSOLD_1H_EXTREME: mtf_penalty=config.MTF_RSI_PENALTY_STRONG; mtf_r=f"4h RSI 극단과매도({rsi_val_1h:.0f})"
        elif rsi_val_1h<=config.MTF_RSI_OVERSOLD_1H and rsi_val_4h<=config.MTF_RSI_OVERSOLD_4H: mtf_penalty=config.MTF_RSI_PENALTY_STRONG; mtf_r=f"4h+1d RSI 강과매도"
        elif rsi_val_1h<=config.MTF_RSI_OVERSOLD_1H_MILD: mtf_penalty=config.MTF_RSI_PENALTY_MILD; mtf_r=f"4h RSI 약과매도({rsi_val_1h:.0f})"
    if mtf_penalty < 1.0: logger.info(f"[MTF-RSI/{d.upper()}] {mtf_r} → ×{mtf_penalty}")

    exhaustion_mult = 1.0
    if regime_name=="EXPLOSIVE":
        if d=="long" and rsi_val_1h>=config.EXPLOSIVE_EXHAUSTION_RSI_LONG:
            exhaustion_mult=config.EXPLOSIVE_EXHAUSTION_PENALTY
        elif d=="short" and rsi_val_1h<=config.EXPLOSIVE_EXHAUSTION_RSI_SHORT:
            exhaustion_mult=config.EXPLOSIVE_EXHAUSTION_PENALTY

    explosive_oversold_mult = 1.0
    if regime_name=="EXPLOSIVE":
        _pb = bb.get("pct_b",0.5)
        if d=="short" and rsi_val_1h<config.EXPLOSIVE_OVERSOLD_GUARD_RSI and _pb<config.EXPLOSIVE_OVERSOLD_GUARD_BB:
            explosive_oversold_mult=config.EXPLOSIVE_OVERSOLD_PENALTY
        elif d=="long" and rsi_val_1h>config.EXPLOSIVE_OVERBOUGHT_GUARD_RSI and _pb>config.EXPLOSIVE_OVERBOUGHT_GUARD_BB:
            explosive_oversold_mult=config.EXPLOSIVE_OVERSOLD_PENALTY

    liq_reverse_mult = 1.0
    if liq.get("favorable_direction") not in (None, d) and liq.get("signal","none")!="none":
        liq_reverse_mult=config.LIQ_REVERSE_PENALTY

    BB_STREAK=3; lower_streak=bb.get("lower_streak",0); upper_streak=bb.get("upper_streak",0)
    bb_suppressed=False; bb_reason=None
    if d=="long" and lower_streak>=BB_STREAK and regime_name=="TRENDING":
        if rsi_val_15m>config.BB_STREAK_SUPPRESS_RSI_EXEMPT: bb_suppressed=True; bb_reason=f"BB하단{lower_streak}캔들 연속 이탈"
    elif d=="short" and upper_streak>=BB_STREAK and regime_name=="TRENDING":
        if rsi_val_15m<(100-config.BB_STREAK_SUPPRESS_RSI_EXEMPT): bb_suppressed=True; bb_reason=f"BB상단{upper_streak}캔들 연속 이탈"
    if bb_suppressed:
        return {"direction":d,"final_score":0.0,"raw_score":round(raw_score,2),"weighted_score":0.0,
                "ema_multiplier":ema_mult,"adx_multiplier":1.0,"passed_gate":True,"signal":False,
                "component_scores":scores,"bonuses":[],"bonus_total":0,"gate_info":gate,
                "bb_suppressed":True,"bb_suppress_reason":bb_reason,"regime":regime,
                "breakdown":"⛔ BB 연속 이탈 억제","volume_penalty":0,"explosive_bos_penalty":1.0}

    # ── BOS/CHoCH 패널티 ─────────────────────────────────────
    bos_data = analysis.get("bos_choch",{})
    choch_penalty = 1.0
    if d=="long"  and bos_data.get("choch_bearish"): choch_penalty=config.CHOCH_AGAINST_PENALTY
    elif d=="short" and bos_data.get("choch_bullish"): choch_penalty=config.CHOCH_AGAINST_PENALTY
    bos_penalty = 1.0
    if d=="long"  and bos_data.get("bos_bearish"): bos_penalty=config.BOS_CONFLICT_PENALTY
    elif d=="short" and bos_data.get("bos_bullish"): bos_penalty=config.BOS_CONFLICT_PENALTY
    choch_4h_penalty = 1.0
    if d=="long"  and bos_choch_4h.get("choch_bearish"): choch_4h_penalty=config.CHOCH_4H_AGAINST_PENALTY
    elif d=="short" and bos_choch_4h.get("choch_bullish"): choch_4h_penalty=config.CHOCH_4H_AGAINST_PENALTY
    bos_4h_penalty = 1.0
    if d=="long"  and bos_choch_4h.get("bos_bearish"): bos_4h_penalty=config.BOS_4H_CONFLICT_PENALTY
    elif d=="short" and bos_choch_4h.get("bos_bullish"): bos_4h_penalty=config.BOS_4H_CONFLICT_PENALTY

    # ══════════════════════════════════════════════════════════
    # 보너스 계산
    # ══════════════════════════════════════════════════════════
    bonuses = []

    # 극단 과매도/과매수
    if is_extreme_oversold: bonuses.append(("멀티TF극단과매도", config.BONUS_EXTREME_OVERSOLD_MTF))
    elif is_extreme_overbought: bonuses.append(("멀티TF극단과매수", config.BONUS_EXTREME_OVERSOLD_MTF))

    # 볼린저 극단 + RSI 다이버전스
    bb_ext = bb_state_str in ("lower_breakout","near_lower","upper_breakout","near_upper")
    has_div = rsi.get("bullish_divergence") if d=="long" else rsi.get("bearish_divergence")
    _div_ok = (d=="long" and rsi_val_15m<=38) or (d=="short" and rsi_val_15m>=65)
    if bb_ext and has_div and _div_ok: bonuses.append(("볼린저극단+RSI다이버전스", config.BONUS_BB_RSI_ALIGN))

    # 펀딩비 + LS 동일 방향
    fr_bias=funding.get("bias","neutral"); ls_bias=ls.get("bias","neutral")
    if ((d=="long"  and fr_bias=="long_favorable"  and ls_bias in ("long_favorable","long_extreme")) or
        (d=="short" and fr_bias=="short_favorable" and ls_bias in ("short_favorable","short_extreme"))):
        bonuses.append(("펀딩비+롱숏비율", config.BONUS_FUNDING_LS_ALIGN))

    # 청산 프록시
    liq_signal=liq.get("signal","none"); liq_large=liq.get("is_large",False)
    liq_api = micro_result and any(n=="LiqCascade" and p<0 for n,p,_ in micro_result.get("details",[]))
    if not liq_api and liq_large and not _bos_reverse_pre:
        if (d=="long" and liq_signal=="long_liq_detected") or (d=="short" and liq_signal=="short_liq_detected"):
            bonuses.append(("대규모청산꼬리", config.BONUS_LIQUIDATION))

    # 추세 지속
    ema_same=ema_info.get("same_count",0); tb=taker.get("bias","neutral"); ts=taker.get("strength","neutral")
    if ema_same==3 and ts in ("strong","mild") and ((d=="long" and tb=="buy_dominant") or (d=="short" and tb=="sell_dominant")):
        bonuses.append((f"추세지속EMA+Taker", config.BONUS_TREND_STRONG))

    # 눌림목
    pbs=(d=="long" and rsi.get("pullback_long_strong") and ema_same>=2) or (d=="short" and rsi.get("pullback_short_strong") and ema_same>=2)
    pbw=(d=="long" and rsi.get("pullback_long_weak") and not rsi.get("pullback_long_strong") and ema_same>=2) or \
        (d=="short" and rsi.get("pullback_short_weak") and not rsi.get("pullback_short_strong") and ema_same>=2)
    pbm=(d=="long" and rsi.get("pullback_long_micro") and not pbs and not pbw and ema_same>=1) or \
        (d=="short" and rsi.get("pullback_short_micro") and not pbs and not pbw and ema_same>=1)
    if pbs: bonuses.append((f"눌림목강", config.BONUS_PULLBACK_ENTRY))
    elif pbw: bonuses.append((f"눌림목약", config.BONUS_PULLBACK_ENTRY_WEAK))
    elif pbm: bonuses.append((f"눌림목미세", config.BONUS_PULLBACK_ENTRY_MICRO))

    # 거래량-가격 다이버전스
    vpd=analysis.get("vol_price_div",{}); _vm=0.60 if regime_name=="RANGING" else 1.0
    if d=="short" and vpd.get("bearish_vol_div"): bonuses.append(("거래량약세다이버", round(config.BONUS_VOL_PRICE_DIV*_vm)))
    elif d=="long" and vpd.get("bullish_vol_div"): bonuses.append(("거래량강세다이버", round(config.BONUS_VOL_PRICE_DIV*_vm)))

    # 시장 구조
    ms=analysis.get("market_structure",{}); _se=regime_name not in ("RANGING","SQUEEZE")
    if d=="short":
        if ms.get("failed_breakout"): bonuses.append(("돌파실패", config.BONUS_FAILED_BREAKOUT))
        if ms.get("lower_high") and _se: bonuses.append(("LowerHigh", config.BONUS_MARKET_STRUCT_TREND))
    elif d=="long":
        if ms.get("failed_breakdown"): bonuses.append(("붕괴실패", config.BONUS_FAILED_BREAKOUT))
        if ms.get("higher_low") and _se: bonuses.append(("HigherLow", config.BONUS_MARKET_STRUCT_TREND))

    # FVG
    fvg=analysis.get("fvg",{}); bf=fvg.get("in_bullish_fvg",False); bfv=fvg.get("in_bearish_fvg",False)
    both=bf and bfv
    fv=config.BONUS_FVG_ENTRY_CONFLICTED if both else config.BONUS_FVG_ENTRY
    if both: bonuses.append((f"FVG모호진입", fv))
    elif d=="long" and bf: bonuses.append(("FVG강세진입", fv))
    elif d=="short" and bfv: bonuses.append(("FVG약세진입", fv))

    # 1h BOS
    if d=="long"  and bos_data.get("bos_bullish"): bonuses.append(("1h-BOS상승", config.BONUS_BOS_CONFIRM))
    elif d=="short" and bos_data.get("bos_bearish"): bonuses.append(("1h-BOS하락", config.BONUS_BOS_CONFIRM))

    # 4h BOS (강화 보너스)
    if d=="long"  and bos_choch_4h.get("bos_bullish"): bonuses.append(("4h-BOS상승", config.BONUS_BOS_CONFIRM_4H)); logger.info(f"[4h-BOS] ★★ +{config.BONUS_BOS_CONFIRM_4H}pt")
    elif d=="short" and bos_choch_4h.get("bos_bearish"): bonuses.append(("4h-BOS하락", config.BONUS_BOS_CONFIRM_4H)); logger.info(f"[4h-BOS] ★★ +{config.BONUS_BOS_CONFIRM_4H}pt")

    # 피보나치
    fib=analysis.get("fibonacci",{})
    if d=="long":
        if fib.get("in_golden_pocket_long"): bonuses.append(("피보황금포켓롱", config.BONUS_FIB_GOLDEN_POCKET))
        elif fib.get("near_key_level_long"): bonuses.append(("피보주요레벨롱", config.BONUS_FIB_KEY_LEVEL))
    elif d=="short":
        if fib.get("in_golden_pocket_short"): bonuses.append(("피보황금포켓숏", config.BONUS_FIB_GOLDEN_POCKET))
        elif fib.get("near_key_level_short"): bonuses.append(("피보주요레벨숏", config.BONUS_FIB_KEY_LEVEL))

    # 히든 다이버전스
    _ha=adx_1h.get("adx",0.0); _he=not (regime_name in ("RANGING","SQUEEZE") and _ha<config.HIDDEN_DIV_MIN_ADX)
    if d=="long" and rsi.get("hidden_bull_div") and _he: bonuses.append(("히든강세다이버", config.BONUS_HIDDEN_DIVERGENCE))
    elif d=="short" and rsi.get("hidden_bear_div") and _he: bonuses.append(("히든약세다이버", config.BONUS_HIDDEN_DIVERGENCE))

    # ── [v3.0] 신규 보너스 ────────────────────────────────────

    # ① 스마트머니 LS 다이버전스
    sm_dir = smart_money.get("smart_direction","neutral")
    if sm_dir != "neutral":
        adj = smart_money.get("long_score_adj" if d=="long" else "short_score_adj", 0)
        if adj > 0:
            bonuses.append((f"스마트머니{'롱' if d=='long' else '숏'}", adj))

    # ② OI 매트릭스
    oi_adj = oi_matrix.get("long_score_adj" if d=="long" else "short_score_adj", 0)
    if oi_adj > 0:
        bonuses.append((f"OI매트릭스({oi_matrix.get('quadrant','')})", oi_adj))

    # ③ 펀딩비 추세
    ft_adj = fund_trend.get("long_score_adj" if d=="long" else "short_score_adj", 0)
    if ft_adj > 0:
        bonuses.append((f"펀딩추세({fund_trend.get('signal','')})", ft_adj))

    # ⑤ 4H 캔들 패턴 (1h의 1.4배)
    if d=="short":
        if candle_4h.get("bearish_pin"):      bonuses.append(("4H베어핀바",   config.BONUS_CANDLE_4H_PIN_BAR))
        elif candle_4h.get("bearish_engulf"): bonuses.append(("4H베어인걸핑", config.BONUS_CANDLE_4H_ENGULFING))
    elif d=="long":
        if candle_4h.get("bullish_pin"):      bonuses.append(("4H불핀바",     config.BONUS_CANDLE_4H_PIN_BAR))
        elif candle_4h.get("bullish_engulf"): bonuses.append(("4H불인걸핑",   config.BONUS_CANDLE_4H_ENGULFING))

    # ④ 1D 캔들 패턴 (1h의 2배)
    if d=="short":
        if candle_1d.get("bearish_pin"):      bonuses.append(("1D베어핀바",   config.BONUS_CANDLE_1D_PIN_BAR))
        elif candle_1d.get("bearish_engulf"): bonuses.append(("1D베어인걸핑", config.BONUS_CANDLE_1D_ENGULFING))
    elif d=="long":
        if candle_1d.get("bullish_pin"):      bonuses.append(("1D불핀바",     config.BONUS_CANDLE_1D_PIN_BAR))
        elif candle_1d.get("bullish_engulf"): bonuses.append(("1D불인걸핑",   config.BONUS_CANDLE_1D_ENGULFING))

    # ⑥ 멀티TF 모멘텀 정합
    mtm_adj = mtf_momentum.get("long_score_adj" if d=="long" else "short_score_adj", 0)
    if mtm_adj > 0:
        bonuses.append((f"멀티TF모멘텀{mtf_momentum.get('alignment',0)}/3", mtm_adj))

    # ⑧ 주간 키레벨
    wl_adj = weekly_levels.get("long_score_adj" if d=="long" else "short_score_adj", 0)
    if wl_adj > 0:
        bonuses.append((f"주간레벨({weekly_levels.get('level_type','')})", wl_adj))

    # 1h 캔들 패턴 (기존)
    candle_1h = analysis.get("candle_pattern",{})
    if d=="short":
        if candle_1h.get("bearish_pin"):      bonuses.append(("1H베어핀바",   config.BONUS_CANDLE_PIN_BAR))
        elif candle_1h.get("bearish_engulf"): bonuses.append(("1H베어인걸핑", config.BONUS_CANDLE_ENGULFING))
    elif d=="long":
        if candle_1h.get("bullish_pin"):      bonuses.append(("1H불핀바",     config.BONUS_CANDLE_PIN_BAR))
        elif candle_1h.get("bullish_engulf"): bonuses.append(("1H불인걸핑",   config.BONUS_CANDLE_ENGULFING))

    # 거래량 폭발
    vr=vol.get("ratio",1.0); av=adx_1h.get("adx",0.0)
    if vr>=config.VOLUME_EXPLOSION_MULTIPLIER and av>=22.0 and ema_same<3:
        bonuses.append(("거래량폭발", config.BONUS_VOLUME_EXPLOSION))

    # Post-Squeeze
    prev_regime=analysis.get("prev_regime","")
    bb_jb=((d=="long" and bb_state_str in ("upper_breakout","near_upper") and bb.get("upper_streak",0)==1) or
           (d=="short" and bb_state_str in ("lower_breakout","near_lower") and bb.get("lower_streak",0)==1))
    if (prev_regime=="SQUEEZE" or regime_name=="EXPLOSIVE") and bb_jb:
        bonuses.append(("Post-Squeeze돌파", config.BONUS_POST_SQUEEZE))

    # ── 보너스 조정 ──────────────────────────────────────────
    if exhaustion_mult < 1.0:
        tc={"LowerHigh","HigherLow","거래량약세다이버","거래량강세다이버","볼린저극단+RSI다이버전스",
            "1h-BOS상승","1h-BOS하락","4h-BOS상승","4h-BOS하락"}
        bonuses=[(n,v) for n,v in bonuses if n not in tc]

    _REV={"거래량강세다이버","거래량약세다이버","볼린저극단+RSI다이버전스"}
    if ema_all_reverse and not bb_reversal_exempt:
        bonuses=[(n,round(v*0.25) if n in _REV else v) for n,v in bonuses]

    _CANDLE={"1H불핀바","1H베어핀바","1H불인걸핑","1H베어인걸핑",
             "4H불핀바","4H베어핀바","4H불인걸핑","4H베어인걸핑",
             "1D불핀바","1D베어핀바","1D불인걸핑","1D베어인걸핑"}
    _ta=((d=="long" and taker.get("bias")=="sell_dominant") or (d=="short" and taker.get("bias")=="buy_dominant"))
    if _ta:
        # 1h는 0.40, 4h는 0.60, 1d는 0.75 (상위TF 패턴은 덜 감산)
        _1h_c={"1H불핀바","1H베어핀바","1H불인걸핑","1H베어인걸핑"}
        _4h_c={"4H불핀바","4H베어핀바","4H불인걸핑","4H베어인걸핑"}
        _1d_c={"1D불핀바","1D베어핀바","1D불인걸핑","1D베어인걸핑"}
        bonuses=[(n, round(v*0.40) if n in _1h_c else round(v*0.60) if n in _4h_c else round(v*0.75) if n in _1d_c else v) for n,v in bonuses]

    if regime_name=="SQUEEZE":
        bonuses=[(n, round(v*config.SQUEEZE_CANDLE_BONUS_MULT) if n in _CANDLE else v) for n,v in bonuses]

    _LVS={"LowerHigh","HigherLow","돌파실패","붕괴실패","거래량강세다이버","거래량약세다이버","볼린저극단+RSI다이버전스"}
    vs=vol.get("score",50.0)
    if vs < config.VOLUME_PENALTY_MID_THRESHOLD:
        bonuses=[(n,round(v*0.5) if n in _LVS else v) for n,v in bonuses]

    # ── 보너스 캡 ────────────────────────────────────────────
    bonus_raw = sum(v for _,v in bonuses)
    _any_bos = (bos_penalty<1.0 or bos_4h_penalty<1.0)
    if _any_bos and ema_all_reverse and not bb_reversal_exempt: bonus_cap=config.COUNTER_TREND_BONUS_CAP
    elif _any_bos: bonus_cap=config.BOS_ONLY_BONUS_CAP
    else: bonus_cap=_get_tiered_bonus_cap(base_score)
    bonus_total=min(bonus_cap,bonus_raw)
    if bonus_raw>bonus_cap: logger.info(f"[보너스캡/{d.upper()}] {bonus_raw}→{bonus_total}pt (캡:{bonus_cap})")

    # ── 캔들 모멘텀 패널티 ───────────────────────────────────
    cm_mult=1.0
    if d=="short" and candle_1h.get("consecutive_bull"):
        cm_mult=config.CANDLE_MOMENTUM_PENALTY_TRENDING if regime_name=="TRENDING" else \
                config.CANDLE_MOMENTUM_PENALTY_EXPLOSIVE if regime_name=="EXPLOSIVE" else \
                config.CANDLE_MOMENTUM_PENALTY_RANGING
    elif d=="long" and candle_1h.get("consecutive_bear"):
        if not (bb_state_str in ("lower_breakout","near_lower") or bb.get("pct_b",0.5)<=0.15):
            cm_mult=config.CANDLE_MOMENTUM_PENALTY_TRENDING if regime_name=="TRENDING" else \
                    config.CANDLE_MOMENTUM_PENALTY_EXPLOSIVE if regime_name=="EXPLOSIVE" else \
                    config.CANDLE_MOMENTUM_PENALTY_RANGING

    exp_bos=1.0
    if regime_name=="EXPLOSIVE" and bos_penalty<1.0: exp_bos=config.EXPLOSIVE_BOS_CONFLICT_PENALTY

    vs2=vol.get("score",50.0)
    volume_penalty=config.VOLUME_PENALTY_LOW if vs2<config.VOLUME_PENALTY_LOW_THRESHOLD else \
                   config.VOLUME_PENALTY_MID if vs2<config.VOLUME_PENALTY_MID_THRESHOLD else 0

    rbw=1.0
    if _any_bos and adx_1h.get("adx",0)<config.ADX_BOS_COUNTER_THRESHOLD and regime_name=="RANGING":
        rbw=0.90

    soft_penalty=(mtf_penalty*exhaustion_mult*explosive_oversold_mult*liq_reverse_mult*
                  cm_mult*choch_penalty*choch_4h_penalty*bos_penalty*bos_4h_penalty*rbw*exp_bos)
    micro_penalty=micro_result.get("total_penalty",0) if micro_result else 0

    final_score=round(min(100.0,max(0.0,(base_score+bonus_total)*soft_penalty+micro_penalty+volume_penalty)),2)

    # ══════════════════════════════════════════════════════════
    # 임계값 조정
    # ══════════════════════════════════════════════════════════
    regime_threshold = regime.get("threshold", config.REGIME_THRESHOLDS.get("TRENDING",64))

    if bb.get("squeeze",False) and regime_threshold<66:
        regime_threshold=min(66,regime_threshold+2)

    if ema_all_reverse and not bb_reversal_exempt:
        av2=adx_1h.get("adx",0.0)
        if   av2>=config.ADX_COUNTER_TREND_THRESHOLD_STRONG: cb=config.ADX_COUNTER_TREND_BOOST_STRONG
        elif av2>=config.ADX_COUNTER_TREND_THRESHOLD_MID:    cb=config.ADX_COUNTER_TREND_BOOST_MID
        elif av2>=config.ADX_COUNTER_TREND_THRESHOLD_WEAK:   cb=config.ADX_COUNTER_TREND_BOOST_WEAK
        else: cb=0
        if cb>0: regime_threshold=min(85,regime_threshold+cb)

    # v2.0 임계값 조정
    meta_adj=config.META_REGIME_THRESHOLD_ADJ.get((regime_4h_name,regime_name),0)
    if meta_adj!=0:
        regime_threshold=min(88,max(52,regime_threshold+meta_adj))
        logger.info(f"[메타레짐/{d.upper()}] 4h:{regime_4h_name}×1h:{regime_name} → {meta_adj:+d}pt = {regime_threshold}pt")

    bias_adj=daily_bias.get(f"threshold_adj_{d}",0)
    if bias_adj!=0:
        regime_threshold=min(90,max(52,regime_threshold+bias_adj))
        logger.info(f"[일봉바이어스/{d.upper()}] {daily_bias.get('bias','?')} → {bias_adj:+d}pt = {regime_threshold}pt")

    session_adj=_get_session_threshold_adj()
    if session_adj!=0: regime_threshold=min(90,max(52,regime_threshold+session_adj))

    fc_adj=_get_funding_cycle_adj()
    if fc_adj!=0: regime_threshold=min(90,regime_threshold+fc_adj)

    # [v3.0 ⑨] 1D EMA 구조 임계값 조정
    ema_thr_adj = ema_structure.get(f"long_threshold_adj" if d=="long" else "short_threshold_adj", 0)
    if ema_thr_adj != 0:
        regime_threshold = min(92, max(50, regime_threshold + ema_thr_adj))
        logger.info(f"[1D-EMA구조/{d.upper()}] {ema_structure.get('structure','?')} → {ema_thr_adj:+d}pt = {regime_threshold}pt")

    signal = (final_score >= regime_threshold)
    if signal and both and vs<config.FVG_AMBIGUOUS_VOL_THRESHOLD:
        signal=False

    # 로그
    _adjs=[]
    if meta_adj!=0:    _adjs.append(f"메타레짐{meta_adj:+d}")
    if bias_adj!=0:    _adjs.append(f"바이어스{bias_adj:+d}")
    if session_adj!=0: _adjs.append(f"세션{session_adj:+d}")
    if fc_adj!=0:      _adjs.append(f"펀딩{fc_adj:+d}")
    if ema_thr_adj!=0: _adjs.append(f"EMA구조{ema_thr_adj:+d}")
    _tn=f" [{','.join(_adjs)}]" if _adjs else ""
    logger.info(
        f"[Score/{d.upper()}] [{regime_name}|4h:{regime_4h_name}|{daily_bias.get('bias','?')}]"
        f" raw:{raw_score:.1f}×EMA{ema_mult:.2f}"
        + (f"×게이트{gate_penalty:.2f}" if gate_penalty<1.0 else "")
        + f" +보너스{bonus_total}[캡:{bonus_cap}]"
        + (f" ×soft{soft_penalty:.3f}" if soft_penalty<1.0 else "")
        + (f" +micro{micro_penalty:+d}" if micro_penalty else "")
        + (f" +vol{volume_penalty:+d}" if volume_penalty else "")
        + f" = {final_score:.1f}pt (임계:{regime_threshold}pt{_tn})"
        + (" 🚨 신호" if signal else "")
    )

    return {
        "direction":d,"final_score":final_score,"raw_score":round(raw_score,2),
        "weighted_score":round(base_score,2),"ema_multiplier":ema_mult,"adx_multiplier":1.0,
        "passed_gate":True,"signal":signal,"component_scores":scores,
        "bonuses":bonuses,"bonus_total":bonus_total,"bonus_cap":bonus_cap,"gate_info":gate,
        "bb_suppressed":False,"bb_suppress_reason":None,"regime":regime,
        "regime_threshold":regime_threshold,"mtf_penalty":mtf_penalty,
        "exhaustion_mult":exhaustion_mult,"explosive_oversold_mult":explosive_oversold_mult,
        "liq_reverse_mult":liq_reverse_mult,"candle_momentum_mult":cm_mult,
        "choch_penalty":choch_penalty,"choch_4h_penalty":choch_4h_penalty,
        "bos_conflict_penalty":bos_penalty,"bos_4h_conflict_penalty":bos_4h_penalty,
        "explosive_bos_penalty":exp_bos,"ranging_bos_weak_penalty":rbw,
        "volume_penalty":volume_penalty,
        "meta_adj":meta_adj,"bias_adj":bias_adj,"session_adj":session_adj,
        "funding_cycle_adj":fc_adj,"ema_structure_adj":ema_thr_adj,
        # [v3.0 요약]
        "smart_money_dir":  smart_money.get("smart_direction","neutral"),
        "oi_quadrant":      oi_matrix.get("quadrant","neutral"),
        "fund_trend_signal":fund_trend.get("signal","neutral"),
        "mtf_momentum_align":mtf_momentum.get("alignment",0),
        "ema_structure":    ema_structure.get("structure","neutral"),
    }


def evaluate_signals(analysis: dict, micro_long: dict=None, micro_short: dict=None) -> dict:
    lr=calculate_entry_score(analysis,"long",  micro_long)
    sr=calculate_entry_score(analysis,"short", micro_short)
    ls=lr["final_score"]; ss=sr["final_score"]
    primary=None; suppressed=None
    if lr["signal"] and sr["signal"]:
        if abs(ls-ss)<5.0: suppressed=f"양방향 차이 {abs(ls-ss):.1f}pt"
        else: primary="long" if ls>ss else "short"
    elif lr["signal"]: primary="long"
    elif sr["signal"]: primary="short"
    ps=ls if primary=="long" else (ss if primary=="short" else 0.0)
    if primary: logger.info(f"[Signal] 🚨 {primary.upper()} {ps:.1f}pt")
    else:       logger.info(f"[Signal] 없음 — 롱:{ls:.1f} 숏:{ss:.1f}")
    return {"long":lr,"short":sr,"primary":primary,"primary_score":ps,"suppressed":suppressed}


# ══════════════════════════════════════════════════════════════════
# 상태 파일
# ══════════════════════════════════════════════════════════════════

def _load_state() -> dict:
    if os.path.exists(config.SIGNAL_STATE_FILE):
        try:
            with open(config.SIGNAL_STATE_FILE) as f: return json.load(f)
        except: pass
    return {}

def _save_state(state: dict) -> None:
    try:
        d=os.path.dirname(config.SIGNAL_STATE_FILE)
        if d: os.makedirs(d,exist_ok=True)
        with open(config.SIGNAL_STATE_FILE,"w") as f: json.dump(state,f)
    except Exception as e: logger.warning(f"[State] 저장 실패: {e}")

def _get_effective_cooldown(symbol,direction,current_price):
    state=_load_state(); lp=state.get(f"{symbol}_{direction}_last_price",0)
    if not lp: return config.SIGNAL_COOLDOWN_MINUTES
    cp=(current_price-lp)/lp; dm=cp if direction=="long" else -cp
    if dm>=config.PRICE_MOVE_SUPPRESS_STRONG: return config.COOLDOWN_SUPPRESSED_STRONG
    if dm>=config.PRICE_MOVE_SUPPRESS_MILD:   return config.COOLDOWN_SUPPRESSED_MILD
    if dm<=config.PRICE_MOVE_RESET_THRESHOLD: return 0
    return config.SIGNAL_COOLDOWN_MINUTES

def is_in_cooldown(symbol,direction,current_price=0.0):
    state=_load_state(); last=state.get(f"{symbol}_{direction}")
    if last is None: return False
    em=_get_effective_cooldown(symbol,direction,current_price)
    if em==0: return False
    el=datetime.now(timezone.utc)-datetime.fromisoformat(last); cd=timedelta(minutes=em)
    if el<cd:
        remain=int((cd-el).total_seconds()/60); logger.info(f"[Cooldown] {symbol} {direction.upper()} 잔여:{remain}분"); return True
    return False

def record_signal_sent(symbol,direction,current_price=0.0):
    state=_load_state(); state[f"{symbol}_{direction}"]=datetime.now(timezone.utc).isoformat()
    if current_price>0: state[f"{symbol}_{direction}_last_price"]=current_price
    _save_state(state)

def _load_prev_regime(symbol): return _load_state().get(f"{symbol}_prev_regime","")
def _save_prev_regime(symbol,regime_name):
    state=_load_state(); state[f"{symbol}_prev_regime"]=regime_name; _save_state(state)


# ══════════════════════════════════════════════════════════════════
# 파이프라인
# ══════════════════════════════════════════════════════════════════

def run_scoring_pipeline(symbol,analysis,market_data=None):
    import datetime as dt
    logger.info(f"{'─'*50}")
    logger.info(f"🎯 점수 산출 [v3.0]: {symbol}")
    regime=analysis.get("regime",{}); rn=regime.get("regime","UNKNOWN")
    r4h=analysis.get("regime_4h",{}); db=analysis.get("daily_bias",{})
    sm=analysis.get("smart_money",{}); oi=analysis.get("oi_matrix",{})
    es=analysis.get("ema_structure",{})
    logger.info(
        f"  {regime.get('icon','')} 1h:{rn} | 4h:{r4h.get('regime','?')} | "
        f"바이어스:{db.get('bias','?')} | EMA구조:{es.get('structure','?')} | "
        f"스마트머니:{sm.get('smart_direction','?')} | OI:{oi.get('quadrant','?')}"
    )

    prev=_load_prev_regime(symbol)
    if prev: analysis["prev_regime"]=prev

    ml={"total_penalty":0,"raw_total":0,"details":[],"suggested_entry":None}
    ms_={"total_penalty":0,"raw_total":0,"details":[],"suggested_entry":None}

    if market_data:
        try:
            from microstructure_analyzer import compute_microstructure_penalties
            md=market_data.get("microstructure",{}); price=market_data.get("price") or analysis.get("current_price") or 0.0
            tbp=market_data.get("taker_volume",{}).get("buy_pct",50.0)
            plp=market_data.get("ls_ratio",{}).get("long_pct",0.5)
            pb=analysis.get("bollinger",{}).get("pct_b",0.5)
            ml=compute_microstructure_penalties(micro_data=md,current_price=price,direction="long",regime=rn,percent_b=pb,taker_buy_pct=tbp,position_long_pct=plp)
            ms_=compute_microstructure_penalties(micro_data=md,current_price=price,direction="short",regime=rn,percent_b=pb,taker_buy_pct=tbp,position_long_pct=plp)
        except Exception as e:
            logger.warning(f"[Pipeline] 마이크로구조 계산 실패: {e}")

    signals=evaluate_signals(analysis,micro_long=ml,micro_short=ms_)
    primary=signals["primary"]; ps=signals["primary_score"]
    cp=analysis.get("current_price") or 0.0
    cooldown=False; should_notify=False

    if primary:
        if is_in_cooldown(symbol,primary,cp): cooldown=True
        else: should_notify=True; logger.info(f"[Pipeline] ✅ {symbol} {primary.upper()} {ps:.1f}pt")
    else: logger.info(f"[Pipeline] {symbol} 신호 없음")

    _save_prev_regime(symbol,rn)
    mr=ml if primary=="long" else ms_
    return {
        "symbol":symbol,"should_notify":should_notify,"direction":primary,"score":ps,
        "signal_result":signals,"cooldown_skip":cooldown,"regime":regime,
        "regime_4h":r4h,"daily_bias":db,"scored_at":dt.datetime.now(timezone.utc).isoformat(),
        "micro_result":mr,
    }