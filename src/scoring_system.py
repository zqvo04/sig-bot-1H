"""
scoring_system.py — 점수 산출 (1h Bot v3.2)
────────────────────────────────────────────────────────────────────
[v3.1] ①쿨다운즉시저장 ②가격밴드쿨다운 ③FVG역방향패널티
       ④RANGING_EMA_ADJ(제거→A-2통합) ⑤MACD음수권패널티 ⑥연속신호임계값
[v3.2] 충돌/중복 점검 완료 후 통합:
  ④ 제거 → A-2 역풍카운터에 흡수
  [A-1] 3중 역풍 하드블록 (MACD+EMA+Taker 동시, 극단과매도/매수 예외)
  [A-2] 역풍 카운터 임계값 (5요소 × 3pt, 최대 12pt) — ④ 대체
  [A-3] 하락 모멘텀 컨텍스트 (음봉2/3 + MA20하단 + MACD음수 + slope음 → +5pt)
  [B-1] RANGING 심리보너스 ×0.5 (entry EMA 역방향 시 펀딩/OI/스마트머니/펀딩추세)
  [B-2] RANGING + EMA역방향 보너스캡 20pt (기존 22~42pt에서 하향)
  [C-1] MA20 위치+기울기 임계값 +4pt (price<MA20 AND slope음)
  [D-1] 기본점수 <55 + 보너스raw >25 → 보너스캡 18pt
  [D-2] 보너스 ≤ 기본점수×0.55 (최소 10pt 보장)
  [E-1] RANGING 지속시간 +2~4pt (3h+/6h+, state_file 타이머)
────────────────────────────────────────────────────────────────────
충돌 처리:
  · ④ RANGING_ENTRY_EMA_ADJ 상수 config에서 제거, A-2로 통합
  · B-2/D-1/D-2는 모두 min()으로 기존 tiered cap 뒤에 순차 적용
  · A-1은 threshold 비교 이후 override (score 로그는 보존)
  · C-2(선형회귀)·C-3(피크되돌림)·E-2 → A-3에 흡수하거나 제거
────────────────────────────────────────────────────────────────────
"""
import json, logging, os
from datetime import datetime, timezone, timedelta
import config

logger = logging.getLogger(__name__)

# B-1에서 사용하는 심리보너스 이름 프리픽스
_SENTIMENT_PREFIXES = (
    "펀딩비+롱숏비율",
    "OI매트릭스(",
    "펀딩추세(",
    "스마트머니롱",
    "스마트머니숏",
)


# ════════════════════════════════════════════════
# 세션 / 펀딩사이클 헬퍼
# ════════════════════════════════════════════════
def _session_adj():
    h = datetime.now(timezone.utc).hour
    wd = datetime.now(timezone.utc).weekday()
    if wd >= 5:      return config.SESSION_ADJ_WEEKEND
    if 13 <= h < 16: return config.SESSION_ADJ_OVERLAP
    if 16 <= h < 22: return config.SESSION_ADJ_NY
    if  7 <= h < 13: return config.SESSION_ADJ_LONDON
    return config.SESSION_ADJ_ASIA

def _funding_cycle_adj():
    return config.FUNDING_CYCLE_ADJ if datetime.now(timezone.utc).hour in config.FUNDING_CYCLE_HOURS else 0

def _tiered_bonus_cap(base_score):
    for thr, cap in config.BONUS_CAP_TIERS:
        if base_score < thr: return cap
    return 42


# ════════════════════════════════════════════════
# 점수 산출 핵심
# ════════════════════════════════════════════════
def calculate_entry_score(analysis: dict, direction: str, micro_result: dict = None) -> dict:
    d = direction

    # ── 기본 데이터 추출 ──────────────────────────────────────
    gate          = analysis.get(f"gate_{d}", {})
    gate_penalty  = gate.get("funding_penalty", 1.0)
    rsi           = analysis.get("rsi", {})
    bb            = analysis.get("bollinger", {})
    funding       = analysis.get("funding_rate", {})
    ls            = analysis.get("ls_ratio", {})
    taker         = analysis.get("taker_volume", {})
    liq           = analysis.get("liquidations", {})
    vol           = analysis.get("volume", {})
    adx_1h        = analysis.get("adx_1h", {})
    regime        = analysis.get("regime", {})
    macd_1h       = analysis.get("macd_1h", {})        # [v3.1/v3.2]
    bos4          = analysis.get("bos_choch_4h", {})
    r4h           = analysis.get("regime_4h", {})
    db            = analysis.get("daily_bias", {})
    smart_money   = analysis.get("smart_money", {})
    oi_matrix     = analysis.get("oi_matrix", {})
    fund_trend    = analysis.get("funding_trend", {})
    mtf_mom       = analysis.get("mtf_momentum", {})
    weekly_lvl    = analysis.get("weekly_levels", {})
    ema_struct    = analysis.get("ema_structure", {})
    candle_4h     = analysis.get("candle_pattern_4h", {})
    candle_1d     = analysis.get("candle_pattern_1d", {})
    candle_1h     = analysis.get("candle_pattern", {})
    bos_data      = analysis.get("bos_choch", {})
    fvg           = analysis.get("fvg", {})

    ema_info      = analysis.get(f"ema_{d}", {})
    rev_cnt       = ema_info.get("reverse_count", 0)
    ema_same      = ema_info.get("same_count", 0)
    # 1h TF 방향 — A-1/A-2 역풍 판단에 사용
    entry_ema_tf  = ema_info.get("tf_signals", {}).get("1h", "neutral")

    rn            = regime.get("regime", "UNKNOWN")
    r4h_name      = r4h.get("regime", "UNKNOWN")
    rsi15         = rsi.get("value", 50.0)
    rsi1h         = rsi.get("value_1h", 50.0)
    rsi4h         = rsi.get("value_4h", 50.0)
    bb_state      = bb.get("state", "")
    tb            = taker.get("bias", "neutral")
    ts            = taker.get("strength", "neutral")
    vs            = vol.get("score", 50.0)
    vr            = vol.get("ratio", 1.0)
    ha            = adx_1h.get("adx", 0.0)
    cp            = analysis.get("current_price", 0.0)
    sym           = analysis.get("_symbol", "")

    # MA20 컨텍스트 (bollinger mid = SMA20) — C-1/A-2/A-3
    ma20          = bb.get("mid", 0.0)
    ma20_slope    = bb.get("ma20_slope_sign", 0)    # [v3.2] analysis_engine 추가 필드

    bf  = fvg.get("in_bullish_fvg", False)
    bfv = fvg.get("in_bearish_fvg", False)
    both = bf and bfv

    # ── 극단 과매도/과매수 플래그 (A-1 예외 조건) ─────────────
    is_ext_oversold = (
        d == "long" and
        rsi15 <= config.EXTREME_OVERSOLD_15M and
        rsi1h  <= config.EXTREME_OVERSOLD_1H and
        rsi4h  <= config.EXTREME_OVERSOLD_4H and
        bb_state in ("lower_breakout", "near_lower", "lower_zone")
    )
    is_ext_overbought = (
        d == "short" and
        rsi15 >= config.EXTREME_OVERBOUGHT_15M and
        rsi1h  >= config.EXTREME_OVERBOUGHT_1H and
        rsi4h  >= config.EXTREME_OVERBOUGHT_4H and
        bb_state in ("upper_breakout", "near_upper", "upper_zone")
    )

    # ── 가중합 원점수 ─────────────────────────────────────────
    scores = {
        "rsi":              rsi.get(f"{d}_score", 50.0),
        "bollinger":        bb.get(f"{d}_score", 50.0),
        "funding_rate":     funding.get(f"{d}_score", 50.0),
        "long_short_ratio": ls.get(f"{d}_score", 50.0),
        "taker_volume":     taker.get(f"{d}_score", 50.0),
        "volume":           vs,
    }
    weights = config.REGIME_SCORE_WEIGHTS.get(rn, config.SCORE_WEIGHTS)

    bb_rev_exempt = (
        (d == "long"  and bb_state == "lower_breakout") or
        (d == "short" and bb_state == "upper_breakout")
    )
    ema_all_rev = (rev_cnt == 3)

    if ema_all_rev and not bb_rev_exempt:
        scores["long_short_ratio"] = 50.0

    if bb.get("squeeze"):
        if d == "short" and bb_state in ("near_upper","upper_zone","upper_breakout"):
            scores["bollinger"] = min(scores["bollinger"], 52.0)
        elif d == "long" and bb_state in ("near_lower","lower_zone","lower_breakout"):
            scores["bollinger"] = max(scores["bollinger"], 48.0)

    bos_rev = (
        (d == "long"  and (bos_data.get("bos_bearish") or bos4.get("bos_bearish"))) or
        (d == "short" and (bos_data.get("bos_bullish") or bos4.get("bos_bullish")))
    )
    if bos_rev:
        lsv = scores["long_short_ratio"]
        if not ((d == "long" and lsv < 50) or (d == "short" and lsv > 50)):
            scores["long_short_ratio"] = 50.0

    raw_score  = sum(scores[k] * weights[k] for k in weights)
    ema_table  = config.REGIME_EMA_MULTIPLIERS.get(rn, config.EMA_MULTIPLIER)
    ema_mult   = ema_table.get(rev_cnt, 1.0)
    base_score = raw_score * ema_mult * gate_penalty

    # ────────────────────────────────────────────
    # Soft 패널티 곱셈
    # ────────────────────────────────────────────
    mtf_p = 1.0; mtf_r = None
    if d == "long":
        if rsi1h >= config.MTF_RSI_OVERBOUGHT_1H_EXTREME:
            mtf_p = config.MTF_RSI_PENALTY_STRONG; mtf_r = f"RSI극단과매수({rsi1h:.0f})"
        elif rsi1h >= config.MTF_RSI_OVERBOUGHT_1H and rsi4h >= config.MTF_RSI_OVERBOUGHT_4H:
            mtf_p = config.MTF_RSI_PENALTY_STRONG; mtf_r = "RSI강과매수"
        elif rsi1h >= config.MTF_RSI_OVERBOUGHT_1H_MILD:
            mtf_p = config.MTF_RSI_PENALTY_MILD;  mtf_r = f"RSI약과매수({rsi1h:.0f})"
    elif d == "short":
        if rsi1h <= config.MTF_RSI_OVERSOLD_1H_EXTREME:
            mtf_p = config.MTF_RSI_PENALTY_STRONG; mtf_r = f"RSI극단과매도({rsi1h:.0f})"
        elif rsi1h <= config.MTF_RSI_OVERSOLD_1H and rsi4h <= config.MTF_RSI_OVERSOLD_4H:
            mtf_p = config.MTF_RSI_PENALTY_STRONG; mtf_r = "RSI강과매도"
        elif rsi1h <= config.MTF_RSI_OVERSOLD_1H_MILD:
            mtf_p = config.MTF_RSI_PENALTY_MILD;  mtf_r = f"RSI약과매도({rsi1h:.0f})"
    if mtf_p < 1.0:
        logger.info(f"[MTF-RSI/{d.upper()}] {mtf_r} → ×{mtf_p}")

    exh_mult = 1.0
    if rn == "EXPLOSIVE":
        if d == "long"  and rsi1h >= config.EXPLOSIVE_EXHAUSTION_RSI_LONG:  exh_mult = config.EXPLOSIVE_EXHAUSTION_PENALTY
        elif d == "short" and rsi1h <= config.EXPLOSIVE_EXHAUSTION_RSI_SHORT: exh_mult = config.EXPLOSIVE_EXHAUSTION_PENALTY

    exp_ov_mult = 1.0
    pb = bb.get("pct_b", 0.5)
    if rn == "EXPLOSIVE":
        if d == "short" and rsi1h < config.EXPLOSIVE_OVERSOLD_GUARD_RSI and pb < config.EXPLOSIVE_OVERSOLD_GUARD_BB:
            exp_ov_mult = config.EXPLOSIVE_OVERSOLD_PENALTY
        elif d == "long" and rsi1h > config.EXPLOSIVE_OVERBOUGHT_GUARD_RSI and pb > config.EXPLOSIVE_OVERBOUGHT_GUARD_BB:
            exp_ov_mult = config.EXPLOSIVE_OVERSOLD_PENALTY

    liq_rev = 1.0
    if liq.get("favorable_direction") not in (None, d) and liq.get("signal", "none") != "none":
        liq_rev = config.LIQ_REVERSE_PENALTY

    # BB 연속 이탈 억제 (TRENDING 한정)
    ls_bb = bb.get("lower_streak", 0); us_bb = bb.get("upper_streak", 0)
    if d == "long" and ls_bb >= 3 and rn == "TRENDING" and rsi15 > config.BB_STREAK_SUPPRESS_RSI_EXEMPT:
        return _suppressed_result(d, raw_score, base_score, ema_mult, gate, regime, f"BB하단{ls_bb}캔들연속")
    if d == "short" and us_bb >= 3 and rn == "TRENDING" and rsi15 < 100 - config.BB_STREAK_SUPPRESS_RSI_EXEMPT:
        return _suppressed_result(d, raw_score, base_score, ema_mult, gate, regime, f"BB상단{us_bb}캔들연속")

    # BOS/CHoCH 패널티
    choch_p  = config.CHOCH_AGAINST_PENALTY    if ((d=="long" and bos_data.get("choch_bearish")) or (d=="short" and bos_data.get("choch_bullish"))) else 1.0
    bos_p    = config.BOS_CONFLICT_PENALTY     if ((d=="long" and bos_data.get("bos_bearish"))   or (d=="short" and bos_data.get("bos_bullish")))   else 1.0
    choch4_p = config.CHOCH_4H_AGAINST_PENALTY if ((d=="long" and bos4.get("choch_bearish"))     or (d=="short" and bos4.get("choch_bullish")))     else 1.0
    bos4_p   = config.BOS_4H_CONFLICT_PENALTY  if ((d=="long" and bos4.get("bos_bearish"))       or (d=="short" and bos4.get("bos_bullish")))       else 1.0
    any_bos  = (bos_p < 1.0 or bos4_p < 1.0)

    # ────────────────────────────────────────────
    # 보너스 계산
    # ────────────────────────────────────────────
    bonuses = []

    if is_ext_oversold:    bonuses.append(("멀티TF극단과매도", config.BONUS_EXTREME_OVERSOLD_MTF))
    elif is_ext_overbought: bonuses.append(("멀티TF극단과매수", config.BONUS_EXTREME_OVERSOLD_MTF))

    bb_ext = bb_state in ("lower_breakout","near_lower","upper_breakout","near_upper")
    has_div = rsi.get("bullish_divergence") if d=="long" else rsi.get("bearish_divergence")
    div_ok  = (d=="long" and rsi15 <= 38) or (d=="short" and rsi15 >= 65)
    if bb_ext and has_div and div_ok:
        bonuses.append(("볼린저극단+RSI다이버전스", config.BONUS_BB_RSI_ALIGN))

    fr_b = funding.get("bias","neutral"); ls_b = ls.get("bias","neutral")
    if ((d=="long"  and fr_b=="long_favorable"  and ls_b in ("long_favorable","long_extreme")) or
        (d=="short" and fr_b=="short_favorable" and ls_b in ("short_favorable","short_extreme"))):
        bonuses.append(("펀딩비+롱숏비율", config.BONUS_FUNDING_LS_ALIGN))

    liq_sig = liq.get("signal","none"); liq_large = liq.get("is_large", False)
    liq_api = micro_result and any(n=="LiqCascade" and p<0 for n,p,_ in micro_result.get("details",[]))
    if not liq_api and liq_large and not bos_rev:
        if (d=="long" and liq_sig=="long_liq_detected") or (d=="short" and liq_sig=="short_liq_detected"):
            bonuses.append(("대규모청산꼬리", config.BONUS_LIQUIDATION))

    if ema_same==3 and ts in ("strong","mild") and ((d=="long" and tb=="buy_dominant") or (d=="short" and tb=="sell_dominant")):
        bonuses.append(("추세지속EMA+Taker", config.BONUS_TREND_STRONG))

    pbs = (d=="long"  and rsi.get("pullback_long_strong")  and ema_same>=2) or (d=="short" and rsi.get("pullback_short_strong")  and ema_same>=2)
    pbw = (d=="long"  and rsi.get("pullback_long_weak")    and not rsi.get("pullback_long_strong")  and ema_same>=2) or (d=="short" and rsi.get("pullback_short_weak")  and not rsi.get("pullback_short_strong") and ema_same>=2)
    pbm = (d=="long"  and rsi.get("pullback_long_micro")   and not pbs and not pbw and ema_same>=1) or (d=="short" and rsi.get("pullback_short_micro") and not pbs and not pbw and ema_same>=1)
    if pbs:      bonuses.append(("눌림목강",   config.BONUS_PULLBACK_ENTRY))
    elif pbw:    bonuses.append(("눌림목약",   config.BONUS_PULLBACK_ENTRY_WEAK))
    elif pbm:    bonuses.append(("눌림목미세", config.BONUS_PULLBACK_ENTRY_MICRO))

    vpd = analysis.get("vol_price_div", {}); vm = 0.60 if rn=="RANGING" else 1.0
    if d=="short" and vpd.get("bearish_vol_div"): bonuses.append(("거래량약세다이버", round(config.BONUS_VOL_PRICE_DIV*vm)))
    elif d=="long"  and vpd.get("bullish_vol_div"): bonuses.append(("거래량강세다이버", round(config.BONUS_VOL_PRICE_DIV*vm)))

    mst = analysis.get("market_structure", {}); se = rn not in ("RANGING","SQUEEZE")
    if d=="short":
        if mst.get("failed_breakout"): bonuses.append(("돌파실패",  config.BONUS_FAILED_BREAKOUT))
        if mst.get("lower_high") and se: bonuses.append(("LowerHigh", config.BONUS_MARKET_STRUCT_TREND))
    elif d=="long":
        if mst.get("failed_breakdown"): bonuses.append(("붕괴실패",  config.BONUS_FAILED_BREAKOUT))
        if mst.get("higher_low") and se: bonuses.append(("HigherLow", config.BONUS_MARKET_STRUCT_TREND))

    fv = config.BONUS_FVG_ENTRY_CONFLICTED if both else config.BONUS_FVG_ENTRY
    if both:               bonuses.append(("FVG모호진입",  fv))
    elif d=="long"  and bf:  bonuses.append(("FVG강세진입", fv))
    elif d=="short" and bfv: bonuses.append(("FVG약세진입", fv))

    if d=="long"  and bos_data.get("bos_bullish"):  bonuses.append(("1h-BOS상승", config.BONUS_BOS_CONFIRM))
    elif d=="short" and bos_data.get("bos_bearish"): bonuses.append(("1h-BOS하락", config.BONUS_BOS_CONFIRM))
    if d=="long"  and bos4.get("bos_bullish"):  bonuses.append(("4h-BOS상승", config.BONUS_BOS_CONFIRM_4H))
    elif d=="short" and bos4.get("bos_bearish"): bonuses.append(("4h-BOS하락", config.BONUS_BOS_CONFIRM_4H))

    fib = analysis.get("fibonacci", {})
    if d == "long":
        if fib.get("in_golden_pocket_long"):  bonuses.append(("피보황금포켓롱", config.BONUS_FIB_GOLDEN_POCKET))
        elif fib.get("near_key_level_long"):  bonuses.append(("피보주요레벨롱", config.BONUS_FIB_KEY_LEVEL))
    elif d == "short":
        if fib.get("in_golden_pocket_short"): bonuses.append(("피보황금포켓숏", config.BONUS_FIB_GOLDEN_POCKET))
        elif fib.get("near_key_level_short"): bonuses.append(("피보주요레벨숏", config.BONUS_FIB_KEY_LEVEL))

    he = not (rn in ("RANGING","SQUEEZE") and ha < config.HIDDEN_DIV_MIN_ADX)
    if d=="long"  and rsi.get("hidden_bull_div") and he: bonuses.append(("히든강세다이버", config.BONUS_HIDDEN_DIVERGENCE))
    elif d=="short" and rsi.get("hidden_bear_div") and he: bonuses.append(("히든약세다이버", config.BONUS_HIDDEN_DIVERGENCE))

    # v3.0 신규 보너스
    sm_adj = smart_money.get("long_score_adj" if d=="long" else "short_score_adj", 0)
    if sm_adj > 0: bonuses.append((f"스마트머니{'롱' if d=='long' else '숏'}", sm_adj))

    oi_adj = oi_matrix.get("long_score_adj" if d=="long" else "short_score_adj", 0)
    if oi_adj > 0: bonuses.append((f"OI매트릭스({oi_matrix.get('quadrant','')})", oi_adj))

    ft_adj = fund_trend.get("long_score_adj" if d=="long" else "short_score_adj", 0)
    if ft_adj > 0: bonuses.append((f"펀딩추세({fund_trend.get('signal','')})", ft_adj))

    for c4t, c4n, pin, eng in [("short","4H베어","bearish_pin","bearish_engulf"),("long","4H불","bullish_pin","bullish_engulf")]:
        if d == c4t:
            if candle_4h.get(pin):      bonuses.append((f"{c4n}핀바",   config.BONUS_CANDLE_4H_PIN_BAR))
            elif candle_4h.get(eng):    bonuses.append((f"{c4n}인걸핑", config.BONUS_CANDLE_4H_ENGULFING))
    for c1t, c1n, pin, eng in [("short","1D베어","bearish_pin","bearish_engulf"),("long","1D불","bullish_pin","bullish_engulf")]:
        if d == c1t:
            if candle_1d.get(pin):      bonuses.append((f"{c1n}핀바",   config.BONUS_CANDLE_1D_PIN_BAR))
            elif candle_1d.get(eng):    bonuses.append((f"{c1n}인걸핑", config.BONUS_CANDLE_1D_ENGULFING))
    for cht, chn, pin, eng in [("short","1H베어","bearish_pin","bearish_engulf"),("long","1H불","bullish_pin","bullish_engulf")]:
        if d == cht:
            if candle_1h.get(pin):      bonuses.append((f"{chn}핀바",   config.BONUS_CANDLE_PIN_BAR))
            elif candle_1h.get(eng):    bonuses.append((f"{chn}인걸핑", config.BONUS_CANDLE_ENGULFING))

    mtm_adj = mtf_mom.get("long_score_adj" if d=="long" else "short_score_adj", 0)
    if mtm_adj > 0: bonuses.append((f"멀티TF모멘텀{mtf_mom.get('alignment',0)}/3", mtm_adj))

    wl_adj = weekly_lvl.get("long_score_adj" if d=="long" else "short_score_adj", 0)
    if wl_adj > 0: bonuses.append((f"주간레벨({weekly_lvl.get('level_type','')})", wl_adj))

    if vr >= config.VOLUME_EXPLOSION_MULTIPLIER and ha >= 22.0 and ema_same < 3:
        bonuses.append(("거래량폭발", config.BONUS_VOLUME_EXPLOSION))

    prev_regime = analysis.get("prev_regime", "")
    bb_jb = (
        (d=="long"  and bb_state in ("upper_breakout","near_upper") and bb.get("upper_streak",0)==1) or
        (d=="short" and bb_state in ("lower_breakout","near_lower") and bb.get("lower_streak",0)==1)
    )
    if (prev_regime=="SQUEEZE" or rn=="EXPLOSIVE") and bb_jb:
        bonuses.append(("Post-Squeeze돌파", config.BONUS_POST_SQUEEZE))

    # ── 기존 보너스 조정 (v3.0 유지) ──────────────────────────
    if exh_mult < 1.0:
        _exc = {"LowerHigh","HigherLow","거래량약세다이버","거래량강세다이버",
                "볼린저극단+RSI다이버전스","1h-BOS상승","1h-BOS하락","4h-BOS상승","4h-BOS하락"}
        bonuses = [(n,v) for n,v in bonuses if n not in _exc]

    _rev_set = {"거래량강세다이버","거래량약세다이버","볼린저극단+RSI다이버전스"}
    if ema_all_rev and not bb_rev_exempt:
        bonuses = [(n, round(v*0.25) if n in _rev_set else v) for n,v in bonuses]

    _candles = {"1H불핀바","1H베어핀바","1H불인걸핑","1H베어인걸핑",
                "4H불핀바","4H베어핀바","4H불인걸핑","4H베어인걸핑",
                "1D불핀바","1D베어핀바","1D불인걸핑","1D베어인걸핑"}
    taker_against = (d=="long" and tb=="sell_dominant") or (d=="short" and tb=="buy_dominant")
    if taker_against:
        bonuses = [(n, round(v*0.40) if n.startswith("1H") and n in _candles
                         else round(v*0.60) if n.startswith("4H") and n in _candles
                         else round(v*0.75) if n.startswith("1D") and n in _candles
                         else v) for n,v in bonuses]

    if rn == "SQUEEZE":
        bonuses = [(n, round(v*config.SQUEEZE_CANDLE_BONUS_MULT) if n in _candles else v) for n,v in bonuses]

    _lvs = {"LowerHigh","HigherLow","돌파실패","붕괴실패","거래량강세다이버","거래량약세다이버","볼린저극단+RSI다이버전스"}
    if vs < config.VOLUME_PENALTY_MID_THRESHOLD:
        bonuses = [(n, round(v*0.5) if n in _lvs else v) for n,v in bonuses]

    # ── [B-1] RANGING 심리보너스 ×0.5 ────────────────────────
    # 조건: RANGING 국면 AND entry EMA 역방향
    # 대상: 펀딩비/OI/스마트머니/펀딩추세 (추세 없는 구간에서 심리보너스 신뢰도 낮음)
    # 충돌 없음: 기존 조정과 독립적 곱셈
    entry_against = (d=="long" and entry_ema_tf=="bearish") or (d=="short" and entry_ema_tf=="bullish")
    if rn == "RANGING" and entry_against:
        bonuses = [
            (n, round(v * config.RANGING_SENTIMENT_MULT)
             if any(n.startswith(p) for p in _SENTIMENT_PREFIXES) else v)
            for n, v in bonuses
        ]
        logger.info(f"[B-1/{d.upper()}] RANGING+역EMA → 심리보너스 ×{config.RANGING_SENTIMENT_MULT}")

    # ── 보너스 캡 계산 (순서 중요: tiered → B-2 → D-1 → D-2) ─
    bonus_raw = sum(v for _, v in bonuses)

    # 기존 tiered cap (BOS 충돌 여부 기반)
    if any_bos and ema_all_rev and not bb_rev_exempt:
        bonus_cap = config.COUNTER_TREND_BONUS_CAP    # 14
    elif any_bos:
        bonus_cap = config.BOS_ONLY_BONUS_CAP          # 22
    else:
        bonus_cap = _tiered_bonus_cap(base_score)      # 22/32/42

    # [B-2] RANGING + entry EMA 역방향 → 캡 20pt
    # 충돌처리: tiered cap 결과에 min() 추가 적용
    if rn == "RANGING" and entry_against:
        bonus_cap = min(bonus_cap, config.RANGING_REVERSE_BONUS_CAP)
        logger.info(f"[B-2/{d.upper()}] RANGING+역EMA → 보너스캡={bonus_cap}pt")

    # [D-1] 기본점수 약함 + 보너스 과다 → 캡 강제 하향
    # 충돌처리: 앞선 캡 결과에 min() 추가 적용
    if base_score < config.WEAK_BASE_SCORE_THRESHOLD and bonus_raw > config.WEAK_BASE_BONUS_THRESHOLD:
        bonus_cap = min(bonus_cap, config.WEAK_BASE_BONUS_CAP)
        logger.info(f"[D-1/{d.upper()}] base:{base_score:.1f}<{config.WEAK_BASE_SCORE_THRESHOLD} "
                    f"bonus_raw:{bonus_raw}>{config.WEAK_BASE_BONUS_THRESHOLD} → 캡={bonus_cap}pt")

    # [D-2] 보너스/기본점수 비율 상한 (하한 MIN_BONUS_FLOOR 보장)
    # 충돌처리: 앞선 캡 결과에 min() 추가 적용
    ratio_cap  = max(round(base_score * config.MAX_BONUS_TO_BASE_RATIO), config.MIN_BONUS_FLOOR)
    bonus_cap  = min(bonus_cap, ratio_cap)

    bonus_total = min(bonus_cap, bonus_raw)
    if bonus_raw > bonus_cap:
        logger.info(f"[보너스캡/{d.upper()}] raw:{bonus_raw} → {bonus_total}pt (cap:{bonus_cap})")

    # ── 캔들 모멘텀 패널티 ───────────────────────────────────
    cm_mult = 1.0
    if d=="short" and candle_1h.get("consecutive_bull"):
        cm_mult = (config.CANDLE_MOMENTUM_PENALTY_TRENDING  if rn=="TRENDING"  else
                   config.CANDLE_MOMENTUM_PENALTY_EXPLOSIVE if rn=="EXPLOSIVE" else
                   config.CANDLE_MOMENTUM_PENALTY_RANGING)
    elif d=="long" and candle_1h.get("consecutive_bear"):
        if not (bb_state in ("lower_breakout","near_lower") or pb <= 0.15):
            cm_mult = (config.CANDLE_MOMENTUM_PENALTY_TRENDING  if rn=="TRENDING"  else
                       config.CANDLE_MOMENTUM_PENALTY_EXPLOSIVE if rn=="EXPLOSIVE" else
                       config.CANDLE_MOMENTUM_PENALTY_RANGING)

    exp_bos_p = config.EXPLOSIVE_BOS_CONFLICT_PENALTY if (rn=="EXPLOSIVE" and bos_p<1.0) else 1.0

    vol_pen = (config.VOLUME_PENALTY_LOW if vs < config.VOLUME_PENALTY_LOW_THRESHOLD else
               config.VOLUME_PENALTY_MID if vs < config.VOLUME_PENALTY_MID_THRESHOLD else 0)

    rbw = 0.90 if (any_bos and ha < config.ADX_BOS_COUNTER_THRESHOLD and rn=="RANGING") else 1.0

    soft = mtf_p * exh_mult * exp_ov_mult * liq_rev * cm_mult * choch_p * choch4_p * bos_p * bos4_p * rbw * exp_bos_p
    micro_pen = micro_result.get("total_penalty", 0) if micro_result else 0

    # [v3.1 ⑤] MACD 음수권 패널티 (-8pt)
    macd_pen = 0
    if macd_1h.get("available"):
        if d=="long"  and macd_1h.get("bearish"):
            macd_pen = config.MACD_BEARISH_LONG_PENALTY
            logger.info(f"[MACD패널티/{d.upper()}] DIF<0,DEA<0 → {macd_pen}pt")
        elif d=="short" and macd_1h.get("bullish"):
            macd_pen = config.MACD_BEARISH_LONG_PENALTY
            logger.info(f"[MACD패널티/{d.upper()}] DIF>0,DEA>0 → {macd_pen}pt")

    # [v3.1 ③] FVG 역방향 패널티
    fvg_pen = 0
    if d == "long":
        if bfv and not bf:
            fvg_pen = config.BEARISH_FVG_LONG_PENALTY
            logger.info(f"[FVG역방향/{d.upper()}] 약세FVG 내부 롱 → {fvg_pen}pt")
        elif not bfv and fvg.get("bearish_fvg_count",0) >= 2 and not bf:
            fvg_pen = config.BEARISH_FVG_OVERHEAD_PENALTY
            logger.info(f"[FVG오버헤드/{d.upper()}] 약세FVG {fvg.get('bearish_fvg_count',0)}개 → {fvg_pen}pt")
    elif d == "short":
        if bf and not bfv:
            fvg_pen = config.BEARISH_FVG_LONG_PENALTY
            logger.info(f"[FVG역방향/{d.upper()}] 강세FVG 내부 숏 → {fvg_pen}pt")
        elif not bf and fvg.get("bullish_fvg_count",0) >= 2 and not bfv:
            fvg_pen = config.BEARISH_FVG_OVERHEAD_PENALTY

    # ── 최종 점수 ────────────────────────────────────────────
    final_score = round(min(100.0, max(0.0,
        (base_score + bonus_total) * soft + micro_pen + vol_pen + macd_pen + fvg_pen
    )), 2)

    # ════════════════════════════════════════════
    # 임계값 조정 (순서: 기본 → v2.0 → v3.2 A/C/E → v3.1 ⑥)
    # ════════════════════════════════════════════
    thr = regime.get("threshold", config.REGIME_THRESHOLDS.get("TRENDING", 64))

    # BB 스퀴즈 최소 임계값
    if bb.get("squeeze") and thr < 66:
        thr = min(66, thr + 2)

    # EMA 전역 역방향 + ADX 부스트
    if ema_all_rev and not bb_rev_exempt:
        adx_cb = (config.ADX_COUNTER_TREND_BOOST_STRONG if ha >= config.ADX_COUNTER_TREND_THRESHOLD_STRONG else
                  config.ADX_COUNTER_TREND_BOOST_MID    if ha >= config.ADX_COUNTER_TREND_THRESHOLD_MID    else
                  config.ADX_COUNTER_TREND_BOOST_WEAK   if ha >= config.ADX_COUNTER_TREND_THRESHOLD_WEAK   else 0)
        if adx_cb: thr = min(85, thr + adx_cb)

    # v2.0: 메타레짐 / 바이어스 / 세션 / 펀딩사이클
    meta_adj = config.META_REGIME_THRESHOLD_ADJ.get((r4h_name, rn), 0)
    if meta_adj: thr = min(88, max(52, thr + meta_adj))

    bias_adj = db.get(f"threshold_adj_{d}", 0)
    if bias_adj: thr = min(90, max(52, thr + bias_adj))

    sess_adj = _session_adj()
    if sess_adj: thr = min(90, max(52, thr + sess_adj))

    fc_adj = _funding_cycle_adj()
    if fc_adj: thr = min(90, thr + fc_adj)

    # v3.0: 1D EMA 구조
    ema_s_adj = ema_struct.get("long_threshold_adj" if d=="long" else "short_threshold_adj", 0)
    if ema_s_adj: thr = min(92, max(50, thr + ema_s_adj))

    # ── [A-2] 역풍 카운터 ─────────────────────────────────────
    # 5개 요소 각 +3pt, 최대 12pt.  ④ RANGING_ENTRY_EMA_ADJ 대체
    # 충돌 없음: ④는 config에서 완전 제거, A-2로 일원화
    pressure = 0
    if d == "long":
        if macd_1h.get("bearish"):                               pressure += 1
        if entry_ema_tf == "bearish":                            pressure += 1
        if tb == "sell_dominant":                                pressure += 1
        if fvg.get("bearish_fvg_count", 0) >= 2 and not bf:     pressure += 1
        if ma20 > 0 and cp < ma20 and ma20_slope < 0:            pressure += 1
    elif d == "short":
        if macd_1h.get("bullish"):                               pressure += 1
        if entry_ema_tf == "bullish":                            pressure += 1
        if tb == "buy_dominant":                                 pressure += 1
        if fvg.get("bullish_fvg_count", 0) >= 2 and not bfv:    pressure += 1
        if ma20 > 0 and cp > ma20 and ma20_slope > 0:            pressure += 1

    p_adj = min(pressure * config.HEADWIND_PRESSURE_PER_FACTOR, config.HEADWIND_PRESSURE_MAX_ADJ)
    if p_adj > 0:
        thr = min(90, thr + p_adj)
        logger.info(f"[A-2/{d.upper()}] 역풍 {pressure}요소 × {config.HEADWIND_PRESSURE_PER_FACTOR}pt = +{p_adj}pt → 임계:{thr}pt")

    # ── [A-3] 하락 모멘텀 컨텍스트 ──────────────────────────
    # 조건: 최근3봉 음봉≥2 AND price<MA20 AND MACD음수 AND MA20slope음수
    # 충돌 없음: A-2와 독립 레이어 (A-2=역풍요소카운트, A-3=복합컨텍스트확인)
    mom_adj = 0
    bear3   = candle_1h.get("recent_bear_count_3", 0)   # [v3.2] analysis_engine 추가 필드
    if d == "long":
        if bear3 >= 2 and ma20 > 0 and cp < ma20 and macd_1h.get("bearish") and ma20_slope < 0:
            mom_adj = config.MOMENTUM_CONTEXT_ADJ
            thr = min(90, thr + mom_adj)
            logger.info(f"[A-3/{d.upper()}] 음봉{bear3}/3+MA20하단+MACD음수 → +{mom_adj}pt 임계:{thr}pt")
    elif d == "short":
        bull3 = 3 - bear3
        if bull3 >= 2 and ma20 > 0 and cp > ma20 and macd_1h.get("bullish") and ma20_slope > 0:
            mom_adj = config.MOMENTUM_CONTEXT_ADJ
            thr = min(90, thr + mom_adj)
            logger.info(f"[A-3/{d.upper()}] 양봉{bull3}/3+MA20상단+MACD양수 → +{mom_adj}pt 임계:{thr}pt")

    # ── [C-1] MA20 위치 + 기울기 ──────────────────────────────
    # 충돌 없음: A-2의 "price<MA20+slope음수" 요소는 threshold 카운터용,
    # C-1은 별도 임계값 부스트 (두 가지 모두 독립 적용)
    c1_adj = 0
    if d == "long" and ma20 > 0 and cp < ma20 and ma20_slope < 0:
        c1_adj = config.EMA20_POSITION_ADJ
        thr = min(90, thr + c1_adj)
        logger.info(f"[C-1/{d.upper()}] price<MA20({ma20:.2f})+slope음 → +{c1_adj}pt 임계:{thr}pt")
    elif d == "short" and ma20 > 0 and cp > ma20 and ma20_slope > 0:
        c1_adj = config.EMA20_POSITION_ADJ
        thr = min(90, thr + c1_adj)
        logger.info(f"[C-1/{d.upper()}] price>MA20({ma20:.2f})+slope양 → +{c1_adj}pt 임계:{thr}pt")

    # ── [E-1] RANGING 지속시간 ────────────────────────────────
    # 충돌 없음: meta_adj (RANGING×RANGING +5pt)는 4h/1h 레짐 조합 기준,
    # E-1은 현재 1h RANGING 국면의 절대 시간 기준. 독립 적용
    dur_adj = 0
    if rn == "RANGING" and sym:
        dur_h = get_regime_duration_hours(sym, "RANGING")
        dur_adj = (config.RANGING_DURATION_ADJ_LONG if dur_h >= 6 else
                   config.RANGING_DURATION_ADJ_MID  if dur_h >= 3 else 0)
        if dur_adj:
            thr = min(90, thr + dur_adj)
            logger.info(f"[E-1/{d.upper()}] RANGING {dur_h:.1f}h 지속 → +{dur_adj}pt 임계:{thr}pt")

    # ── [v3.1 ⑥] 연속 동방향 신호 ────────────────────────────
    consec_adj = 0
    if sym:
        cnt = get_consecutive_signal_count(sym, d)
        if cnt >= 2:
            consec_adj = min(config.CONSECUTIVE_SIGNAL_MAX_ADJ, (cnt-1) * config.CONSECUTIVE_SIGNAL_ADJ)
            thr = min(90, thr + consec_adj)
            logger.info(f"[⑥/{d.upper()}] 연속 {cnt}회 → +{consec_adj}pt 임계:{thr}pt")

    # ── 신호 판정 ────────────────────────────────────────────
    signal = (final_score >= thr)

    # [A-1] 3중 역풍 하드블록 (threshold 비교 이후 override)
    # 충돌 없음: A-2는 threshold 상향, A-1은 그 결과를 override하는 별도 레이어
    # 극단 과매도/매수 시에는 예외 (진짜 반전 신호 보호)
    triple_blocked = False
    if signal and not (is_ext_oversold or is_ext_overbought):
        triple_long  = d=="long"  and macd_1h.get("bearish") and entry_ema_tf=="bearish" and tb=="sell_dominant"
        triple_short = d=="short" and macd_1h.get("bullish") and entry_ema_tf=="bullish" and tb=="buy_dominant"
        if triple_long or triple_short:
            triple_blocked = True
            signal = False
            logger.info(f"[A-1/{d.upper()}] 3중역풍(MACD+EMA+Taker) → 신호 차단 (score:{final_score:.1f}pt)")

    if signal and both and vs < config.FVG_AMBIGUOUS_VOL_THRESHOLD:
        signal = False

    # ── 로그 요약 ─────────────────────────────────────────────
    adj_parts = []
    if meta_adj:    adj_parts.append(f"메타{meta_adj:+d}")
    if bias_adj:    adj_parts.append(f"바이어스{bias_adj:+d}")
    if sess_adj:    adj_parts.append(f"세션{sess_adj:+d}")
    if fc_adj:      adj_parts.append(f"펀딩{fc_adj:+d}")
    if ema_s_adj:   adj_parts.append(f"EMA구조{ema_s_adj:+d}")
    if p_adj:       adj_parts.append(f"역풍카운터+{p_adj}({pressure}요소)")
    if mom_adj:     adj_parts.append(f"하락모멘텀+{mom_adj}")
    if c1_adj:      adj_parts.append(f"MA20위치+{c1_adj}")
    if dur_adj:     adj_parts.append(f"RANGING지속+{dur_adj}")
    if consec_adj:  adj_parts.append(f"연속신호+{consec_adj}")
    pen_parts = []
    if macd_pen:        pen_parts.append(f"MACD{macd_pen:+d}")
    if fvg_pen:         pen_parts.append(f"FVG{fvg_pen:+d}")
    if triple_blocked:  pen_parts.append("⛔A-1차단")

    logger.info(
        f"[Score/{d.upper()}] [{rn}|4h:{r4h_name}|{db.get('bias','?')}]"
        f" raw:{raw_score:.1f}×EMA{ema_mult:.2f}"
        + (f"×gate{gate_penalty:.2f}" if gate_penalty < 1.0 else "")
        + f" +보너스{bonus_total}[cap:{bonus_cap}/raw:{bonus_raw}]"
        + (f" ×soft{soft:.3f}" if soft < 1.0 else "")
        + (f" micro{micro_pen:+d}" if micro_pen else "")
        + (f" vol{vol_pen:+d}" if vol_pen else "")
        + (" " + " ".join(pen_parts) if pen_parts else "")
        + f" = {final_score:.1f}pt / 임계:{thr}pt"
        + (f" [{', '.join(adj_parts)}]" if adj_parts else "")
        + (" 🚨 신호!" if signal else "")
    )

    return {
        "direction": d, "final_score": final_score,
        "raw_score": round(raw_score, 2), "weighted_score": round(base_score, 2),
        "ema_multiplier": ema_mult, "passed_gate": True, "signal": signal,
        "component_scores": scores, "bonuses": bonuses,
        "bonus_total": bonus_total, "bonus_cap": bonus_cap, "bonus_raw": bonus_raw,
        "gate_info": gate, "bb_suppressed": False, "regime": regime,
        "regime_threshold": thr, "triple_blocked": triple_blocked,
        "headwind_pressure": pressure, "pressure_adj": p_adj,
        "momentum_adj": mom_adj, "c1_adj": c1_adj,
        "ranging_dur_adj": dur_adj, "consec_adj": consec_adj,
        "macd_penalty": macd_pen, "fvg_conflict_penalty": fvg_pen,
        "soft_penalty": soft, "vol_penalty": vol_pen,
        "meta_adj": meta_adj, "bias_adj": bias_adj, "session_adj": sess_adj,
    }


def _suppressed_result(d, raw_score, base_score, ema_mult, gate, regime, reason):
    logger.info(f"[Score/{d.upper()}] ⛔ BB연속이탈 억제: {reason}")
    return {
        "direction": d, "final_score": 0.0, "raw_score": round(raw_score,2),
        "weighted_score": round(base_score,2), "ema_multiplier": ema_mult,
        "passed_gate": True, "signal": False, "component_scores": {},
        "bonuses": [], "bonus_total": 0, "bonus_cap": 0, "bonus_raw": 0,
        "gate_info": gate, "bb_suppressed": True, "bb_suppress_reason": reason,
        "regime": regime, "regime_threshold": 0, "triple_blocked": False,
        "headwind_pressure": 0, "pressure_adj": 0, "momentum_adj": 0,
        "c1_adj": 0, "ranging_dur_adj": 0, "consec_adj": 0,
        "macd_penalty": 0, "fvg_conflict_penalty": 0, "soft_penalty": 1.0, "vol_penalty": 0,
        "meta_adj": 0, "bias_adj": 0, "session_adj": 0,
    }


def evaluate_signals(analysis: dict, micro_long=None, micro_short=None) -> dict:
    lr = calculate_entry_score(analysis, "long",  micro_long)
    sr = calculate_entry_score(analysis, "short", micro_short)
    ls = lr["final_score"]; ss = sr["final_score"]
    primary = None; suppressed = None

    if lr["signal"] and sr["signal"]:
        if abs(ls - ss) < 5.0: suppressed = f"양방향 차이 {abs(ls-ss):.1f}pt"
        else: primary = "long" if ls > ss else "short"
    elif lr["signal"]: primary = "long"
    elif sr["signal"]: primary = "short"

    ps = ls if primary=="long" else (ss if primary=="short" else 0.0)
    if primary: logger.info(f"[Signal] 🚨 {primary.upper()} {ps:.1f}pt")
    else:       logger.info(f"[Signal] 없음 — 롱:{ls:.1f} 숏:{ss:.1f}")
    return {"long": lr, "short": sr, "primary": primary, "primary_score": ps, "suppressed": suppressed}


# ════════════════════════════════════════════════
# 상태 관리
# ════════════════════════════════════════════════
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
        with open(config.SIGNAL_STATE_FILE, "w") as f: json.dump(state, f)
    except Exception as e: logger.warning(f"[State] 저장 실패: {e}")

def _effective_cooldown(symbol, direction, current_price):
    lp = _load_state().get(f"{symbol}_{direction}_last_price", 0)
    if not lp: return config.SIGNAL_COOLDOWN_MINUTES
    dm = (current_price - lp) / lp * (1 if direction=="long" else -1)
    if dm >= config.PRICE_MOVE_SUPPRESS_STRONG: return config.COOLDOWN_SUPPRESSED_STRONG
    if dm >= config.PRICE_MOVE_SUPPRESS_MILD:   return config.COOLDOWN_SUPPRESSED_MILD
    if dm <= config.PRICE_MOVE_RESET_THRESHOLD: return 0
    return config.SIGNAL_COOLDOWN_MINUTES

def is_in_cooldown(symbol, direction, current_price=0.0) -> bool:
    last = _load_state().get(f"{symbol}_{direction}")
    if not last: return False
    em = _effective_cooldown(symbol, direction, current_price)
    if em == 0: return False
    elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    cd = timedelta(minutes=em)
    if elapsed < cd:
        logger.info(f"[Cooldown] {symbol} {direction.upper()} 잔여:{int((cd-elapsed).total_seconds()/60)}분")
        return True
    return False

def record_signal_sent(symbol, direction, current_price=0.0) -> None:
    """[v3.1 ①] notification 성공 여부와 무관하게 쿨다운 즉시 저장"""
    st = _load_state()
    st[f"{symbol}_{direction}"] = datetime.now(timezone.utc).isoformat()
    if current_price > 0: st[f"{symbol}_{direction}_last_price"] = current_price
    _save_state(st)
    logger.info(f"[State] {symbol} {direction.upper()} 쿨다운 저장 price:{current_price:.4f}")

def is_in_price_band_cooldown(symbol, direction, current_price) -> bool:
    """[v3.1 ②] 마지막 진입가 ±0.5% 이내 재진입 억제"""
    if current_price <= 0: return False
    lp = _load_state().get(f"{symbol}_{direction}_last_price", 0)
    if not lp: return False
    pct = abs(current_price - lp) / lp
    if pct < config.PRICE_BAND_COOLDOWN_PCT:
        logger.info(f"[PriceBand] {symbol} {direction.upper()} ${lp:.4f} 대비 {pct:.2%} 이내 → 억제")
        return True
    return False

def get_consecutive_signal_count(symbol, direction) -> int:
    return _load_state().get(f"{symbol}_{direction}_consecutive", 0)

def record_consecutive_signal(symbol, direction) -> None:
    st = _load_state()
    cnt = st.get(f"{symbol}_{direction}_consecutive", 0) + 1
    st[f"{symbol}_{direction}_consecutive"] = cnt
    opp = "short" if direction=="long" else "long"
    st[f"{symbol}_{opp}_consecutive"] = 0
    _save_state(st)
    logger.info(f"[연속신호] {symbol} {direction.upper()} {cnt}회")

def record_regime_duration(symbol, regime_name) -> None:
    """[v3.2 E-1] 국면 변경 감지 및 시작 시간 기록"""
    st = _load_state()
    if st.get(f"{symbol}_current_regime") != regime_name:
        st[f"{symbol}_current_regime"] = regime_name
        st[f"{symbol}_regime_start"]   = datetime.now(timezone.utc).isoformat()
        logger.info(f"[레짐변경] {symbol} →{regime_name} 타이머 리셋")
    _save_state(st)

def get_regime_duration_hours(symbol, regime_name) -> float:
    """현재 국면 지속 시간(h) 반환"""
    st = _load_state()
    if st.get(f"{symbol}_current_regime") != regime_name: return 0.0
    s = st.get(f"{symbol}_regime_start")
    if not s: return 0.0
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(s)).total_seconds() / 3600
    except: return 0.0

def _load_prev_regime(symbol): return _load_state().get(f"{symbol}_prev_regime", "")
def _save_prev_regime(symbol, rn):
    st = _load_state(); st[f"{symbol}_prev_regime"] = rn; _save_state(st)


# ════════════════════════════════════════════════
# 파이프라인
# ════════════════════════════════════════════════
def run_scoring_pipeline(symbol, analysis, market_data=None):
    import datetime as dt
    logger.info(f"{'─'*55}")
    logger.info(f"🎯 점수 산출 [v3.2]: {symbol}")

    rn     = analysis.get("regime", {}).get("regime", "UNKNOWN")
    r4h    = analysis.get("regime_4h", {})
    db     = analysis.get("daily_bias", {})
    macd   = analysis.get("macd_1h", {})
    es     = analysis.get("ema_structure", {})
    sm     = analysis.get("smart_money", {})
    oi     = analysis.get("oi_matrix", {})

    logger.info(
        f"  레짐:1h={rn} 4h={r4h.get('regime','?')} | "
        f"바이어스:{db.get('bias','?')} | EMA구조:{es.get('structure','?')} | "
        f"스마트머니:{sm.get('smart_direction','?')} | OI:{oi.get('quadrant','?')} | "
        f"MACD:{'🔴음수' if macd.get('bearish') else '🟢양수' if macd.get('bullish') else '중립'}"
    )

    prev = _load_prev_regime(symbol)
    if prev: analysis["prev_regime"] = prev

    # [v3.2] symbol 주입 (A-2/E-1/⑥ 에서 사용)
    analysis["_symbol"] = symbol

    # [v3.2 E-1] RANGING 지속시간 기록
    record_regime_duration(symbol, rn)

    ml  = {"total_penalty": 0, "raw_total": 0, "details": [], "suggested_entry": None}
    ms_ = {"total_penalty": 0, "raw_total": 0, "details": [], "suggested_entry": None}
    if market_data:
        try:
            from microstructure_analyzer import compute_microstructure_penalties
            md   = market_data.get("microstructure", {})
            price = market_data.get("price") or analysis.get("current_price") or 0.0
            tbp  = market_data.get("taker_volume", {}).get("buy_pct", 50.0)
            plp  = market_data.get("ls_ratio", {}).get("long_pct", 0.5)
            pb   = analysis.get("bollinger", {}).get("pct_b", 0.5)
            ml   = compute_microstructure_penalties(micro_data=md, current_price=price, direction="long",
                                                    regime=rn, percent_b=pb, taker_buy_pct=tbp, position_long_pct=plp)
            ms_  = compute_microstructure_penalties(micro_data=md, current_price=price, direction="short",
                                                    regime=rn, percent_b=pb, taker_buy_pct=tbp, position_long_pct=plp)
        except Exception as e:
            logger.warning(f"[Pipeline] 마이크로구조 계산 실패: {e}")

    signals = evaluate_signals(analysis, micro_long=ml, micro_short=ms_)
    primary = signals["primary"]; ps = signals["primary_score"]
    cp      = analysis.get("current_price") or 0.0
    cooldown = False; should_notify = False

    if primary:
        if is_in_cooldown(symbol, primary, cp):
            cooldown = True
        elif is_in_price_band_cooldown(symbol, primary, cp):
            cooldown = True
        else:
            should_notify = True
            # [v3.1 ①] 쿨다운 즉시 저장 (notification 실패와 무관)
            record_signal_sent(symbol, primary, cp)
            # [v3.1 ⑥] 연속신호 카운트
            record_consecutive_signal(symbol, primary)
            logger.info(f"[Pipeline] ✅ {symbol} {primary.upper()} {ps:.1f}pt")
    else:
        logger.info(f"[Pipeline] {symbol} 신호 없음 — 롱:{signals['long']['final_score']:.1f} 숏:{signals['short']['final_score']:.1f}")

    _save_prev_regime(symbol, rn)

    return {
        "symbol": symbol, "should_notify": should_notify,
        "direction": primary, "score": ps,
        "signal_result": signals, "cooldown_skip": cooldown,
        "regime": analysis.get("regime", {}),
        "regime_4h": r4h, "daily_bias": db,
        "scored_at": dt.datetime.now(timezone.utc).isoformat(),
        "micro_result": ml if primary=="long" else ms_,
    }
