"""
notification.py — 텔레그램 알림 (1h Bot v2.0)
──────────────────────────────────────────────────────────────────────────────
[1h Bot 전환]
  헤더에 "🕐 [1H]" 배지 → 15m봇 알림과 즉시 구분
  RSI TF 표기: 15m/1h/4h → 1h/4h/1d
  ADX 키: adx_15m → adx_1h
  눌림목 설명: "4h RSI 강세 + 1h 과매도" (TF 시프트)

[v2.0 추가 표시]
  ① 4h 메타 레짐    → 시장 컨텍스트 섹션
  ② 일봉 바이어스   → 시장 컨텍스트 섹션
  ③ 4h BOS/CHoCH   → SMC 섹션 (1h 아래 추가)
  ④ 거래 세션 필터  → 시장 컨텍스트 섹션 + 임계값 근거
  ⑦ 펀딩비 사이클   → 시장 컨텍스트 섹션 + 임계값 근거
  임계값 근거 표시  → 푸터에 조정 내역 전체 표시

[v2.1]
  시간 표시 전면 KST(한국 표준시) 기준으로 통일
  UTC+9, 포맷: YYYY-MM-DD HH:MM KST

[v3.7 유지]
  EXPLOSIVE 준과매도/과매수 패널티 (P1)
  청산 역방향 패널티 (P3)
──────────────────────────────────────────────────────────────────────────────
"""
import logging, time
from datetime import datetime, timezone, timedelta
from typing import Optional
import requests

import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import config

logger = logging.getLogger(__name__)
_TG_BASE = "https://api.telegram.org/bot{token}/{method}"

# ── KST 시간대 상수 ───────────────────────────────────────────────
KST = timezone(timedelta(hours=9))

def _now_kst() -> datetime:
    """현재 KST 시각 반환"""
    return datetime.now(timezone.utc).astimezone(KST)

def _fmt_kst(dt_obj: datetime = None) -> str:
    """datetime → 'YYYY-MM-DD HH:MM KST' 포맷"""
    if dt_obj is None:
        dt_obj = _now_kst()
    return dt_obj.strftime("%Y-%m-%d %H:%M KST")


# ══════════════════════════════════════════════════════════════════════════════
# 텔레그램 공통
# ══════════════════════════════════════════════════════════════════════════════

def _send_telegram(method, payload, retries=3):
    if not config.TELEGRAM_BOT_TOKEN:
        return None
    url = _TG_BASE.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                d = r.json()
                if d.get("ok"):
                    return d
                logger.error(f"[TG] API 오류: {d.get('description')}")
                return None
            elif r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 5)))
            else:
                time.sleep(3 * attempt)
        except Exception as e:
            logger.error(f"[TG] 오류: {e}")
            time.sleep(3 * attempt)
    return None


def send_message(text, parse_mode="HTML"):
    if not config.TELEGRAM_CHAT_ID:
        return None
    return _send_telegram("sendMessage", {
        "chat_id":                  config.TELEGRAM_CHAT_ID,
        "text":                     text,
        "parse_mode":               parse_mode,
        "disable_web_page_preview": True,
    })


# ══════════════════════════════════════════════════════════════════════════════
# 유틸리티
# ══════════════════════════════════════════════════════════════════════════════

def _bar(score, width=10):
    f = max(0, min(width, int(round(score / 100 * width))))
    return f"{'█'*f}{'░'*(width-f)} {score:.0f}pt"


def _fmt_price(price, symbol):
    if price is None:
        return "N/A"
    return (f"${price:,.2f}" if any(s in symbol for s in ["BTC","ETH"])
            else f"${price:,.4f}")


def _micro_label(name: str) -> str:
    return {
        "LiqCascade":   "청산캐스케이드",
        "OrderBook":    "오더북벽",
        "OBImbalance":  "호가잔량불균형",
        "CandleMom":    "캔들모멘텀",
        "MarkFunding":  "마크/펀딩",
        "LSDivergence": "LS괴리(고래)",
    }.get(name, name)


def _micro_severity(penalty: int) -> str:
    if penalty <= -12: return "🔴"
    if penalty < 0:    return "🟡"
    if penalty > 0:    return "🟢"
    return "⚪"


def _get_session_label() -> str:
    """현재 UTC 기준 세션 레이블 (세션 판정은 UTC 유지)"""
    now     = datetime.now(timezone.utc)
    hour    = now.hour
    weekday = now.weekday()
    if weekday >= 5:      return "주말 🌙"
    if 13 <= hour < 16:   return "런던+NY 🔥"
    if 16 <= hour < 22:   return "NY 세션 🗽"
    if  7 <= hour < 13:   return "런던 세션 🇬🇧"
    return "아시아 🌏"


def _get_funding_cycle_label() -> str:
    """펀딩비 사이클 상태 (UTC 기준 유지)"""
    hour = datetime.now(timezone.utc).hour
    if hour in config.FUNDING_CYCLE_HOURS:
        return f"⚠️ 정산±1h (hour={hour})"
    return "정상 구간"


# ══════════════════════════════════════════════════════════════════════════════
# 신호 메시지 빌더
# ══════════════════════════════════════════════════════════════════════════════

def build_signal_message(pipeline_result: dict, analysis: dict) -> str:
    direction   = pipeline_result["direction"]
    score       = pipeline_result["score"]
    symbol      = pipeline_result["symbol"]
    signals     = pipeline_result["signal_result"]
    side_result = signals[direction]
    regime_info = pipeline_result.get("regime", {})

    # [v2.0] 새 데이터
    regime_4h_info  = pipeline_result.get("regime_4h",  {})
    daily_bias_info = pipeline_result.get("daily_bias",  {})
    bos_choch_4h    = analysis.get("bos_choch_4h", {})

    micro: dict   = pipeline_result.get("micro_result") or {}
    micro_total   = micro.get("total_penalty", 0)
    micro_raw     = micro.get("raw_total", micro_total)
    micro_details = micro.get("details", [])
    micro_entry   = micro.get("suggested_entry")
    micro_critical = [d for d in micro_details if d[1] <= -10]
    micro_bonus    = [d for d in micro_details if d[1] > 0]

    rsi       = analysis.get("rsi",           {})
    bb        = analysis.get("bollinger",      {})
    ema       = analysis.get(f"ema_{direction}", {})
    adx       = analysis.get("adx_1h",        {})
    funding   = analysis.get("funding_rate",   {})
    ls        = analysis.get("ls_ratio",       {})
    taker     = analysis.get("taker_volume",   {})
    liq       = analysis.get("liquidations",   {})
    fvg       = analysis.get("fvg",            {})
    bos_choch = analysis.get("bos_choch",      {})
    fibonacci = analysis.get("fibonacci",      {})
    atr       = analysis.get("atr",            {})
    price     = analysis.get("current_price")

    cs         = side_result.get("component_scores", {})
    bonuses    = side_result.get("bonuses",           [])
    gate       = side_result.get("gate_info",         {})
    regime_thr = side_result.get("regime_threshold",  64)

    # v3.7 패널티
    mtf_penalty             = side_result.get("mtf_penalty",              1.0)
    exhaustion_mult         = side_result.get("exhaustion_mult",           1.0)
    explosive_oversold_mult = side_result.get("explosive_oversold_mult",   1.0)
    liq_reverse_mult        = side_result.get("liq_reverse_mult",          1.0)
    candle_momentum_m       = side_result.get("candle_momentum_mult",      1.0)
    choch_penalty           = side_result.get("choch_penalty",             1.0)
    bos_conflict_penalty    = side_result.get("bos_conflict_penalty",      1.0)
    explosive_bos_penalty   = side_result.get("explosive_bos_penalty",    1.0)
    bonus_cap               = side_result.get("bonus_cap",                  36)
    bonus_total             = side_result.get("bonus_total",                 0)
    volume_penalty          = side_result.get("volume_penalty",              0)

    # [v2.0] 신규 패널티 및 임계값 조정
    choch_4h_penalty        = side_result.get("choch_4h_penalty",         1.0)
    bos_4h_conflict_penalty = side_result.get("bos_4h_conflict_penalty",  1.0)
    meta_adj                = side_result.get("meta_adj",                    0)
    bias_adj                = side_result.get("bias_adj",                    0)
    session_adj             = side_result.get("session_adj",                 0)
    funding_cycle_adj       = side_result.get("funding_cycle_adj",           0)

    # [v2.1] KST 시각
    now_str = _fmt_kst()

    lines = []

    same_count    = ema.get("same_count",    0)
    reverse_count = ema.get("reverse_count", 0)

    # ── 등급 ──────────────────────────────────────────────────
    if score >= 85:
        grade_icon, grade_label, grade_desc = "🔥🔥", "STRONG", "매우 강한 신호 — 즉시 대응 권장"
    elif score >= 72:
        grade_icon, grade_label, grade_desc = "🔥",   "GOOD",   "좋은 신호 — 표준 진입"
    else:
        grade_icon, grade_label, grade_desc = "📊",   "WATCH",  "기준 통과 — 확인 후 진입"

    if micro_critical and grade_label != "WATCH":
        grade_icon  = "⚠️"
        grade_label = grade_label + "⚠"
        grade_desc  = grade_desc + " | 마이크로구조 경고 확인"

    # ── EMA 정합 ──────────────────────────────────────────────
    if   same_count == 3: trend_align, trend_detail = "✅ 순방향 3/3", "3개 TF EMA 모두 신호 방향 일치"
    elif same_count == 2: trend_align, trend_detail = "✅ 순방향 2/3", "2개 TF EMA 신호 방향 일치"
    elif same_count == 1: trend_align, trend_detail = "⚠️ 부분 역방향 2/3", "상위 TF와 방향 불일치 — 주의"
    else:                 trend_align, trend_detail = "⚠️ 역방향 3/3", "모든 TF EMA 반대 방향 — 역추세 진입"

    # ── 눌림목 ────────────────────────────────────────────────
    pb_strong = rsi.get("pullback_long_strong"  if direction=="long" else "pullback_short_strong", False)
    pb_weak   = rsi.get("pullback_long_weak"    if direction=="long" else "pullback_short_weak",   False)
    pb_micro  = rsi.get("pullback_long_micro"   if direction=="long" else "pullback_short_micro",  False)
    pullback_str = ""
    if direction == "long":
        if pb_strong:  pullback_str = "  ★ 눌림목 롱(강) — 4h RSI 강세(>58) + 1h 과매도(<40)"
        elif pb_weak:  pullback_str = "  ★ 눌림목 롱(약) — 4h RSI 중립상(>52) + 1h 눌림(<44)"
        elif pb_micro: pullback_str = "  ★ 눌림목 롱(미) — 4h RSI 최소조건 + 1h 소폭 눌림"
    else:
        if pb_strong:  pullback_str = "  ★ 눌림목 숏(강) — 4h RSI 약세(<42) + 1h 과매수(>60)"
        elif pb_weak:  pullback_str = "  ★ 눌림목 숏(약) — 4h RSI 중립하(<48) + 1h 과열(>56)"
        elif pb_micro: pullback_str = "  ★ 눌림목 숏(미) — 4h RSI 최소조건 + 1h 소폭 과열"

    # ── SMC 태그 ──────────────────────────────────────────────
    smc_tags = []
    if fvg.get("in_bullish_fvg" if direction=="long" else "in_bearish_fvg"):
        smc_tags.append("FVG")
    if bos_choch.get("bos_bullish" if direction=="long" else "bos_bearish"):
        smc_tags.append("1h-BOS↑" if direction=="long" else "1h-BOS↓")
    if bos_choch_4h.get("bos_bullish" if direction=="long" else "bos_bearish"):
        smc_tags.append("4h-BOS↑" if direction=="long" else "4h-BOS↓")
    if fibonacci.get("in_golden_pocket_long" if direction=="long" else "in_golden_pocket_short"):
        retr = fibonacci.get("long_retracement" if direction=="long" else "short_retracement")
        smc_tags.append(f"황금포켓({retr}%)" if retr else "황금포켓")

    # ══════════════════════════════════════════════════════════
    # ── 헤더
    # ══════════════════════════════════════════════════════════
    dir_icon = "🟢" if direction == "long" else "🔴"
    dir_text = "롱(LONG)" if direction == "long" else "숏(SHORT)"
    lines.append(f"🕐 <b>[1H봇]</b>  {dir_icon} <b>{dir_text} 진입 신호</b>  {grade_icon} <b>{grade_label}</b>")
    lines.append(f"<code>{'─'*34}</code>")
    lines.append(f"🪙 <b>{symbol}</b>   💰 <b>{_fmt_price(price, symbol)}</b>")

    micro_note = f"  <i>(micro:{micro_total:+d}pt)</i>" if micro_total != 0 else ""
    lines.append(f"🎯 신뢰도: <b>{score:.1f}pt</b>  {_bar(score)}  (임계:{regime_thr}pt){micro_note}")
    lines.append(f"📌 {grade_desc}")
    lines.append(f"📐 추세 정합: {trend_align}  <i>{trend_detail}</i>")
    if pullback_str:
        lines.append(f"<b>{pullback_str}</b>")
    if smc_tags:
        lines.append(f"🏛 SMC 확인: <b>{' | '.join(smc_tags)}</b>")
    # [v2.1] KST 시각
    lines.append(f"🕐 {now_str}")
    lines.append("")

    # ── 마이크로구조 필터 ─────────────────────────────────────
    if micro_details:
        cap_note = f" → cap {micro_total:+d}pt" if micro_raw != micro_total else ""
        lines.append(f"🔬 <b>마이크로구조</b>  합계:<b>{micro_raw:+d}pt</b>{cap_note}")
        for name, p, reason in micro_details:
            icon    = _micro_severity(p)
            label   = _micro_label(name)
            r_short = reason.replace("⚠️","").replace("✅","").strip()[:60]
            lines.append(f"  {icon} {label}: <b>{p:+d}pt</b>  <i>{r_short}</i>")
        obi = next((d for d in micro_details if d[0]=="OBImbalance"), None)
        if obi and obi[1] != 0:
            obi_icon = "🟢" if obi[1] > 0 else "🔴"
            lines.append(f"  └ 호가잔량: {obi_icon} {obi[2].replace('✅','').replace('⚠️','').strip()[:45]}")
        lines.append("")

    # ══════════════════════════════════════════════════════════
    # ── [v2.0] 시장 컨텍스트
    # ══════════════════════════════════════════════════════════
    regime_1h_name = regime_info.get("regime", "?")
    regime_4h_name = regime_4h_info.get("regime", "?")
    regime_1h_icon = regime_info.get("icon", "")
    regime_4h_icon = regime_4h_info.get("icon", "")
    bias_str       = daily_bias_info.get("bias", "NEUTRAL")
    bias_bull      = daily_bias_info.get("bull_count", 0)
    bias_bear      = daily_bias_info.get("bear_count", 0)

    bias_icon = "🟢" if bias_str=="BULL" else ("🔴" if bias_str=="BEAR" else "⚪")
    session_label   = _get_session_label()
    funding_c_label = _get_funding_cycle_label()

    # 임계값 조정 내역
    base_thr = regime_info.get("threshold", 64)
    thr_parts = []
    if meta_adj != 0:          thr_parts.append(f"메타레짐{meta_adj:+d}pt")
    if bias_adj != 0:          thr_parts.append(f"바이어스{bias_adj:+d}pt")
    if session_adj != 0:       thr_parts.append(f"세션{session_adj:+d}pt")
    if funding_cycle_adj != 0: thr_parts.append(f"펀딩{funding_cycle_adj:+d}pt")
    thr_summary = f"기본 {base_thr}pt → {' → '.join(thr_parts)} = {regime_thr}pt" if thr_parts else f"{regime_thr}pt"

    lines.append(f"🗺 <b>시장 컨텍스트</b>")
    lines.append(f"  4h국면: {regime_4h_icon} <b>{regime_4h_name}</b>  ×  1h국면: {regime_1h_icon} <b>{regime_1h_name}</b>")
    lines.append(f"  일봉바이어스: {bias_icon} <b>{bias_str}</b>  (강세{bias_bull}/3 약세{bias_bear}/3)")
    lines.append(f"  세션: <b>{session_label}</b>  |  펀딩사이클: {funding_c_label}")
    lines.append(f"  <i>임계값: {thr_summary}</i>")
    lines.append("")

    # ── 1h 시장 국면 ─────────────────────────────────────────
    r_desc = regime_info.get("description", "")
    lines.append(f"📊 <b>1h 국면: {regime_1h_icon} {regime_1h_name}</b>")
    lines.append(f"   <i>{r_desc}</i>")
    lines.append("")

    # ── 기술 지표 ────────────────────────────────────────────
    lines.append("📈 <b>기술 지표</b>")

    rsi_val = rsi.get("value",    50.0)
    rsi_1h  = rsi.get("value_1h")
    rsi_4h  = rsi.get("value_4h")
    rsi_tag = ("⚡ 과매도" if rsi.get("state")=="oversold" else
               "⚡ 과매수" if rsi.get("state")=="overbought" else "— 중립")

    div_s = ""
    if direction == "long":
        if rsi.get("hidden_bull_div"):      div_s = "  📊히든강세(추세지속)"
        elif rsi.get("bullish_divergence"): div_s = "  ✅강세다이버전스(반전)"
    else:
        if rsi.get("hidden_bear_div"):      div_s = "  📊히든약세(추세지속)"
        elif rsi.get("bearish_divergence"): div_s = "  ✅약세다이버전스(반전)"

    rsi_tf = [f"1h:<code>{rsi_val:.0f}</code>"]
    if rsi_1h is not None: rsi_tf.append(f"4h:<code>{rsi_1h:.0f}</code>")
    if rsi_4h is not None: rsi_tf.append(f"1d:<code>{rsi_4h:.0f}</code>")
    lines.append(f"  RSI({config.RSI_PERIOD}) : {' / '.join(rsi_tf)}  {rsi_tag}{div_s}")

    bb_map = {
        "lower_breakout": "🔵 하단이탈", "near_lower": "↘하단영역",
        "lower_zone":     "↘하단영역",   "middle":     "— 중앙",
        "upper_zone":     "↗상단영역",   "near_upper": "🔴 상단근접",
        "upper_breakout": "🔴 상단이탈",
    }
    bb_tag = bb_map.get(bb.get("state",""), "—")
    sq_s   = "  🔊 스퀴즈" if bb.get("squeeze") else ""
    sk_s   = ""
    if bb.get("lower_streak",0) >= 2: sk_s = f"  ⚠️하단이탈{bb['lower_streak']}캔들"
    if bb.get("upper_streak",0) >= 2: sk_s = f"  ⚠️상단이탈{bb['upper_streak']}캔들"
    lines.append(f"  볼린저밴드: {bb_tag}  (%B:{bb.get('pct_b',0.5):.2f}){sq_s}{sk_s}")

    ema_tf   = ema.get("tf_signals", {})
    ema_mult = ema.get("multiplier", 1.0)
    ema_str  = " | ".join(
        f"{tf}:{'↑' if s=='bullish' else ('↓' if s=='bearish' else '—')}"
        for tf, s in ema_tf.items()
    )
    ema_rev  = ema.get("reverse_count", 0)
    ema_warn = "" if ema_mult==1.0 else f"  ⚠️역방향{ema_rev}TF(×{ema_mult:.2f})"
    lines.append(f"  EMA교차  : [{ema_str}]{ema_warn}")

    adx_map = {"strong":"🔥강한추세","normal":"📈추세중","weak":"〰약한추세","none":"💤횡보"}
    lines.append(
        f"  ADX(1h)  : <code>{adx.get('adx',0):.1f}</code>  "
        f"{adx_map.get(adx.get('strength','none'),'—')}"
    )
    lines.append("")

    # ── SMC / 구조 분석 ──────────────────────────────────────
    has_1h_smc = (
        fvg.get("in_bullish_fvg") or fvg.get("in_bearish_fvg") or
        bos_choch.get("bos_bullish") or bos_choch.get("bos_bearish") or
        bos_choch.get("choch_bullish") or bos_choch.get("choch_bearish") or
        fibonacci.get("in_golden_pocket_long") or fibonacci.get("in_golden_pocket_short") or
        fibonacci.get("near_key_level_long")   or fibonacci.get("near_key_level_short")
    )
    has_4h_smc = (
        bos_choch_4h.get("bos_bullish") or bos_choch_4h.get("bos_bearish") or
        bos_choch_4h.get("choch_bullish") or bos_choch_4h.get("choch_bearish")
    )

    if has_1h_smc or has_4h_smc:
        lines.append("🏛 <b>SMC / 구조 분석</b>")

        bull_fvg = fvg.get("in_bullish_fvg", False)
        bear_fvg = fvg.get("in_bearish_fvg", False)
        if bull_fvg and bear_fvg:
            lines.append("  FVG        : ⚠️ 강세+약세 동시 — 방향 모호 (보너스 ÷2)")
        elif bull_fvg:
            lines.append(f"  FVG        : ✅ 강세 FVG ({fvg.get('bullish_fvg_count',0)}개) — 기관 매수 구간")
        elif bear_fvg:
            lines.append(f"  FVG        : ✅ 약세 FVG ({fvg.get('bearish_fvg_count',0)}개) — 기관 매도 구간")
        else:
            lines.append("  FVG        : — 외부")

        def _bos_line(bos_data, tf_label, bos_penalty, choch_p):
            if bos_data.get("bos_bullish"):
                if direction == "short":
                    return [f"  {tf_label}-BOS : ✅ 상승 BOS → 역추세 숏  ⛔ 패널티 ×{bos_penalty:.2f}"]
                return [f"  {tf_label}-BOS : ✅ 상승 BOS 확증 — 상승 구조 지속"]
            elif bos_data.get("bos_bearish"):
                if direction == "long":
                    return [f"  {tf_label}-BOS : ✅ 하락 BOS → 역추세 롱  ⛔ 패널티 ×{bos_penalty:.2f}"]
                return [f"  {tf_label}-BOS : ✅ 하락 BOS 확증 — 하락 구조 지속"]
            elif bos_data.get("choch_bullish"):
                s = [f"  {tf_label}-CHoCH: ⚠️ 상승전환 경고 — 하락→상승 전환"]
                if direction == "short": s.append(f"    └ ⛔ 숏 역방향 패널티 ×{choch_p:.2f}")
                return s
            elif bos_data.get("choch_bearish"):
                s = [f"  {tf_label}-CHoCH: ⚠️ 하락전환 경고 — 상승→하락 전환"]
                if direction == "long": s.append(f"    └ ⛔ 롱 역방향 패널티 ×{choch_p:.2f}")
                return s
            else:
                sh = bos_data.get("last_swing_high"); sl_v = bos_data.get("last_swing_low")
                parts = []
                if sh:   parts.append(f"고점:{_fmt_price(sh, symbol)}")
                if sl_v: parts.append(f"저점:{_fmt_price(sl_v, symbol)}")
                return [f"  {tf_label}-BOS : — 구조 유지  ({', '.join(parts)})"]

        for ln in _bos_line(bos_choch,    "1h", bos_conflict_penalty, choch_penalty):
            lines.append(ln)
        for ln in _bos_line(bos_choch_4h, "4h", bos_4h_conflict_penalty, choch_4h_penalty):
            lines.append(ln)

        if direction == "long":
            if fibonacci.get("in_golden_pocket_long"):
                lines.append(f"  피보나치   : 🥇 황금포켓 {fibonacci.get('long_retracement','?')}%")
            elif fibonacci.get("near_key_level_long"):
                lines.append(f"  피보나치   : ✅ 주요레벨 {fibonacci.get('long_retracement','?')}%")
            else:
                retr = fibonacci.get("long_retracement")
                lines.append(f"  피보나치   : — 외부" + (f"  ({retr}% 되돌림)" if retr else ""))
        else:
            if fibonacci.get("in_golden_pocket_short"):
                lines.append(f"  피보나치   : 🥇 황금포켓 {fibonacci.get('short_retracement','?')}%")
            elif fibonacci.get("near_key_level_short"):
                lines.append(f"  피보나치   : ✅ 주요레벨 {fibonacci.get('short_retracement','?')}%")
            else:
                retr = fibonacci.get("short_retracement")
                lines.append(f"  피보나치   : — 외부" + (f"  ({retr}% 반등)" if retr else ""))

        lines.append("")

    # ── 시장 심리 ─────────────────────────────────────────────
    lines.append("💡 <b>시장 심리</b>")

    fr_pct  = funding.get("rate_pct",0.0) or 0.0
    fr_bias = funding.get("bias","neutral")
    fr_icon = ("🟢" if ((direction=="long"  and fr_bias=="long_favorable") or
                        (direction=="short" and fr_bias=="short_favorable"))
               else ("🔴" if fr_bias!="neutral" else "⚪"))
    lines.append(
        f"  펀딩비   : {fr_icon} {fr_pct:+.4f}%  [{fr_bias}]"
        if funding.get("available") else "  펀딩비   : ⚪ N/A"
    )

    mf_detail = next((d for d in micro_details if d[0]=="MarkFunding"), None)
    if mf_detail and mf_detail[1] != 0:
        mf_icon  = "🔴" if mf_detail[1]<0 else "🟢"
        mf_short = mf_detail[2].replace("[MF]","").strip()[:45]
        lines.append(f"  마크/펀딩 : {mf_icon} {mf_short}  <i>({mf_detail[1]:+d}pt)</i>")

    if ls.get("available"):
        ls_bias_v = ls.get("bias","neutral")
        ls_icon   = ("🟢" if ((direction=="long"  and ls_bias_v in ("long_favorable","long_extreme")) or
                              (direction=="short" and ls_bias_v in ("short_favorable","short_extreme")))
                     else ("🔴" if ls_bias_v!="neutral" else "⚪"))
        lines.append(
            f"  롱숏비율 : {ls_icon} 롱{ls.get('long_pct',0.5)*100:.1f}% / "
            f"숏{ls.get('short_pct',0.5)*100:.1f}%  [{ls_bias_v}]"
        )
        ls_div = next((d for d in micro_details if d[0]=="LSDivergence"), None)
        if ls_div and ls_div[1] != 0:
            ls_i2 = "🔴" if ls_div[1]<0 else "🟢"
            ls_short = ls_div[2].replace("⚠️","").replace("✅","").strip()[:50]
            lines.append(f"  └ 고래포지션: {ls_i2} {ls_short}  <i>({ls_div[1]:+d}pt)</i>")
    else:
        lines.append("  롱숏비율 : ⚪ N/A")

    if taker.get("available"):
        tk_bias = taker.get("bias","neutral")
        tk_icon = ("🟢" if ((direction=="long"  and tk_bias=="buy_dominant") or
                             (direction=="short" and tk_bias=="sell_dominant"))
                   else ("🔴" if tk_bias!="neutral" else "⚪"))
        lines.append(
            f"  Taker    : {tk_icon} "
            f"매수{taker.get('buy_ratio',0.5)*100:.1f}% / "
            f"매도{taker.get('sell_ratio',0.5)*100:.1f}%  [{tk_bias}]"
        )

    if liq.get("available") and liq.get("signal","none") != "none":
        liq_icon     = "💥" if liq.get("is_large") else "⚡"
        display_hint = liq.get("display_hint","")
        fav_dir      = liq.get("favorable_direction")
        lw = liq.get("long_liq_proxy",  0)
        sw = liq.get("short_liq_proxy", 0)
        liq_cascade = next((d for d in micro_details if d[0]=="LiqCascade"), None)
        if liq_cascade and liq_cascade[1] < 0:
            lines.append(f"  청산감지  : ⚠️ {display_hint}  <i>(API패널티 {liq_cascade[1]:+d}pt 우선)</i>")
        elif fav_dir == direction:
            lines.append(f"  청산감지  : {liq_icon} {display_hint}  (롱:{lw:.2f} / 숏:{sw:.2f})")
        else:
            lines.append(f"  청산감지  : ⚠️ {display_hint}  ← 역방향 주의  (롱:{lw:.2f} / 숏:{sw:.2f})")
    lines.append("")

    # ── 지표별 점수 ───────────────────────────────────────────
    lines.append("📉 <b>지표별 점수</b>")
    regime_name    = regime_info.get("regime","UNKNOWN")
    actual_weights = config.REGIME_SCORE_WEIGHTS.get(regime_name, config.SCORE_WEIGHTS)
    label_map = {
        "rsi":              "RSI(1h)     ",
        "bollinger":        "볼린저(1h)  ",
        "funding_rate":     "펀딩비      ",
        "long_short_ratio": "롱숏비율    ",
        "taker_volume":     "Taker비율   ",
        "volume":           "거래량(1h)  ",
    }
    for key, weight in actual_weights.items():
        s = cs.get(key,0.0); contrib = s * weight
        lines.append(f"  {label_map.get(key,key)}: {_bar(s,8)}  <i>({contrib:.1f}pt)</i>")

    ema_m_d  = side_result.get("ema_multiplier", 1.0)
    gate_p   = gate.get("funding_penalty",       1.0)
    rsi_1h_v = rsi.get("value_1h") or 0
    rsi_4h_v = rsi.get("value_4h") or 0
    pct_b_v  = bb.get("pct_b", 0.5)

    if ema_m_d              < 1.0: lines.append(f"  EMA역방향 배율              : ×{ema_m_d:.2f}")
    if gate_p               < 1.0: lines.append(f"  복합 페널티                 : ×{gate_p:.2f}")
    if mtf_penalty          < 1.0:
        lines.append(f"  ⚠️ MTF RSI 과열 패널티    : ×{mtf_penalty:.2f}  (4h:{rsi_1h_v:.0f} 1d:{rsi_4h_v:.0f})")
    if exhaustion_mult      < 1.0:
        lines.append(f"  ⚠️ EXPLOSIVE 소진 패널티  : ×{exhaustion_mult:.2f}  (4h RSI:{rsi_1h_v:.0f})")
    if explosive_oversold_mult < 1.0:
        guard_tag = (
            f"4h RSI:{rsi_1h_v:.0f}<{config.EXPLOSIVE_OVERSOLD_GUARD_RSI} + %B:{pct_b_v:.2f} 과매도 반등 위험"
            if direction=="short" else
            f"4h RSI:{rsi_1h_v:.0f}>{config.EXPLOSIVE_OVERBOUGHT_GUARD_RSI} + %B:{pct_b_v:.2f} 과매수 반락 위험"
        )
        lines.append(f"  ⚠️ EXPLOSIVE 타이밍 패널티: ×{explosive_oversold_mult:.2f}  {guard_tag}")
    if liq_reverse_mult     < 1.0:
        lines.append(f"  ⚠️ 청산 역방향 패널티      : ×{liq_reverse_mult:.2f}  (청산≠진입방향)")
    if candle_momentum_m    < 1.0: lines.append(f"  ⚠️ 캔들 모멘텀 역방향      : ×{candle_momentum_m:.2f}")
    if choch_penalty        < 1.0: lines.append(f"  ⚠️ 1h-CHoCH 역방향 패널티 : ×{choch_penalty:.2f}")
    if choch_4h_penalty     < 1.0: lines.append(f"  ⚠️ 4h-CHoCH 역방향 패널티 : ×{choch_4h_penalty:.2f}  (강화)")
    if bos_conflict_penalty < 1.0:
        lines.append(f"  ⚠️ 1h-BOS 역방향 패널티   : ×{bos_conflict_penalty:.2f}")
    if bos_4h_conflict_penalty < 1.0:
        lines.append(f"  ⚠️ 4h-BOS 역방향 패널티   : ×{bos_4h_conflict_penalty:.2f}  (강화)")
    if explosive_bos_penalty < 1.0:
        combined = round(bos_conflict_penalty * bos_4h_conflict_penalty * explosive_bos_penalty, 3)
        lines.append(f"  ⚠️ EXPLOSIVE+BOS 강화패널티: ×{explosive_bos_penalty:.2f}  (합산 ×{combined:.3f})")

    base_threshold = regime_info.get("threshold", 64)
    if regime_thr > base_threshold and reverse_count == 3:
        ct_boost    = regime_thr - base_threshold
        adx_val_cur = adx.get("adx", 0.0)
        lines.append(f"  ⚠️ ADX 역추세 임계값 상향 : +{ct_boost}pt  (ADX:{adx_val_cur:.0f})")
    if volume_penalty != 0:
        lines.append(f"  거래량 페널티              : {volume_penalty:+d}pt")
    if micro_total != 0:
        cap_sfx = f" (raw:{micro_raw:+d}pt→cap)" if micro_raw!=micro_total else ""
        lines.append(f"  🔬 마이크로구조 합계       : {micro_total:+d}pt{cap_sfx}")
    lines.append("")

    # ── 판단 근거 ─────────────────────────────────────────────
    lines.append("🤖 <b>판단 근거</b>")
    reasons = []

    if micro_critical:
        for _, p, r in micro_critical[:2]:
            r_clean = (r.replace("⚠️","").replace("[Liq]","").replace("[OI]","")
                        .replace("[OB]","").replace("[MF]","").replace("[LS]","")
                        .replace("[OBI]","").replace("[CM]","").strip())
            reasons.append(f"⚠️ {r_clean[:55]}")

    meta_combo = f"4h {regime_4h_name} × 1h {regime_name}"
    if meta_adj < 0:
        reasons.append(f"★ 메타레짐 확인 ({meta_combo}) — 임계값 {meta_adj}pt 완화")
    elif meta_adj > 0:
        reasons.append(f"⚠️ 메타레짐 불일치 ({meta_combo}) — 임계값 +{meta_adj}pt 강화")

    if bias_str != "NEUTRAL":
        align_dir = "롱" if bias_str=="BULL" else "숏"
        if (bias_str=="BULL" and direction=="long") or (bias_str=="BEAR" and direction=="short"):
            reasons.append(f"★ 일봉 {bias_str} 바이어스 — {align_dir} 방향 일치 ({bias_adj}pt 완화)")
        else:
            reasons.append(f"⚠️ 일봉 {bias_str} 바이어스 역행 — 역추세 ({bias_adj}pt 강화)")

    pb_any = rsi.get("pullback_long" if direction=="long" else "pullback_short", False)
    if pb_any:
        grade    = "강" if pb_strong else ("약" if pb_weak else "미세")
        rsi_4h_s = f"{rsi_1h_v:.1f}" if rsi_1h_v else "-"
        reasons.append(f"★ 눌림목({grade}) — 4h RSI({rsi_4h_s})+1h({rsi_val:.0f})")

    if direction=="long"  and rsi.get("hidden_bull_div"): reasons.append("★ 히든 강세 다이버전스 — 추세 지속 (1h)")
    elif direction=="short" and rsi.get("hidden_bear_div"): reasons.append("★ 히든 약세 다이버전스 — 추세 지속 (1h)")

    if fvg.get("in_bullish_fvg") and fvg.get("in_bearish_fvg"):
        reasons.append("⚠️ FVG 방향 모호성 높음")
    elif direction=="long"  and fvg.get("in_bullish_fvg"): reasons.append("FVG 강세 구간 — 기관 매수 주문 레벨")
    elif direction=="short" and fvg.get("in_bearish_fvg"): reasons.append("FVG 약세 구간 — 기관 매도 주문 레벨")

    if direction=="long"  and fibonacci.get("in_golden_pocket_long"):
        reasons.append(f"피보 황금포켓 {fibonacci.get('long_retracement','?')}% — 최강 반전 구간")
    elif direction=="short" and fibonacci.get("in_golden_pocket_short"):
        reasons.append(f"피보 황금포켓 {fibonacci.get('short_retracement','?')}% — 최강 재진입 구간")

    if direction=="long"  and bos_choch_4h.get("bos_bullish"):
        reasons.append("★★ 4h-BOS 상승 확증 — 4h 스윙고점 돌파 (강력)")
    elif direction=="short" and bos_choch_4h.get("bos_bearish"):
        reasons.append("★★ 4h-BOS 하락 확증 — 4h 스윙저점 이탈 (강력)")
    elif direction=="long"  and bos_choch.get("bos_bullish"):
        reasons.append("★ 1h-BOS 상승 확증")
    elif direction=="short" and bos_choch.get("bos_bearish"):
        reasons.append("★ 1h-BOS 하락 확증")
    elif direction=="long"  and bos_choch_4h.get("bos_bearish"):
        reasons.append(f"⚠️ 4h-BOS 하락 역추세 롱 — 강화 패널티 ×{bos_4h_conflict_penalty:.2f}")
    elif direction=="short" and bos_choch_4h.get("bos_bullish"):
        reasons.append(f"⚠️ 4h-BOS 상승 역추세 숏 — 강화 패널티 ×{bos_4h_conflict_penalty:.2f}")

    taker_bias = taker.get("bias","neutral"); vol_strong = analysis.get("volume",{}).get("strong",False)
    bb_state_n = bb.get("state",""); st = rsi.get("state","neutral")

    if same_count == 3:
        if direction=="long"  and taker_bias=="buy_dominant": reasons.append("★ 추세 지속 — EMA 3TF+Taker 매수 일치")
        elif direction=="short" and taker_bias=="sell_dominant": reasons.append("★ 추세 지속 — EMA 3TF+Taker 매도 일치")
        if vol_strong: reasons.append("추세 가속 — 거래량 급증 동반")

    if direction=="long"  and st=="oversold":    reasons.append("1h RSI 과매도 — 반등 구간")
    elif direction=="short" and st=="overbought": reasons.append("1h RSI 과매수 — 하락 구간")
    if direction=="long"  and bb_state_n in ("lower_breakout","near_lower"): reasons.append("볼린저 하단 — 반등 타이밍")
    if direction=="short" and bb_state_n in ("upper_breakout","near_upper"): reasons.append("볼린저 상단 — 하락 타이밍")
    if bb.get("squeeze"): reasons.append("볼린저 스퀴즈 — 큰 움직임 임박")

    if micro_bonus:
        for name, p, r in micro_bonus[:1]:
            r_clean = r.replace("✅","").replace("[OI]","").replace("[Liq]","").replace("[OBI]","").replace("[CM]","").strip()[:50]
            reasons.append(f"✅ {r_clean}")

    for i, r in enumerate(reasons[:7], 1):
        lines.append(f"  {i}. {r}")
    lines.append("")

    # ── 보너스 ────────────────────────────────────────────────
    if bonuses:
        applied_bonus = sum(v for _,v in bonuses)
        cap_note = (f"  <i>(역추세 캡:{bonus_cap}pt)</i>" if bonus_cap==config.COUNTER_TREND_BONUS_CAP and bonus_total<applied_bonus else
                    f"  <i>(상한:{bonus_cap}pt)</i>" if bonus_total<applied_bonus else "")
        lines.append(f"🎁 보너스 +{bonus_total}pt{cap_note}")
        main_b = [(n,v) for n,v in bonuses if v >= 4]
        minor  = sum(v for _,v in bonuses if v < 4)
        parts  = [f"{n}(+{v}pt)" for n,v in main_b]
        if minor > 0: parts.append(f"기타(+{minor}pt)")
        lines.append(f"  {' · '.join(parts)}")
        lines.append("")

    if gate.get("penalty_reason"):
        lines.append(f"⚠️ <i>{gate['penalty_reason']}</i>")
        lines.append("")

    # ── 푸터 ─────────────────────────────────────────────────
    lines.append(f"<code>{'─'*34}</code>")
    lines.append(f"⚙️ 임계값 {regime_thr}pt ({thr_summary if thr_parts else str(base_thr)+'pt'})")
    lines.append(f"⏰ 봉 주기: 1h | 쿨다운: {config.SIGNAL_COOLDOWN_MINUTES}분 | OKX 선물")
    lines.append("<i>⚠️ 참고용 신호입니다. 투자 결정은 본인 책임입니다.</i>")

    msg = "\n".join(lines)
    return msg[:3980] + "\n\n<i>...(생략)</i>" if len(msg) > 4000 else msg


# ══════════════════════════════════════════════════════════════════════════════
# 시스템 메시지
# ══════════════════════════════════════════════════════════════════════════════

def send_error_alert(error_msg: str, context: str = "") -> None:
    # [v2.1] KST 시각
    now = _fmt_kst()
    send_message(
        f"🚨 <b>[1H봇] 시스템 에러</b>\n<code>{'─'*32}</code>\n🕐 {now}\n"
        f"📍 {context or '—'}\n\n<pre>{error_msg[:800]}</pre>"
    )


def send_heartbeat(symbols: list, scan_count: int, signal_count: int) -> None:
    # [v2.1] KST 시각
    now = _fmt_kst()
    send_message(
        f"💚 <b>[1H봇] 정상 동작 중</b>\n<code>{'─'*32}</code>\n🕐 {now}\n"
        f"🪙 {', '.join(symbols)}\n🔄 실행:{scan_count}회 | 🚨 신호:{signal_count}건"
    )


def notify_signal(pipeline_result: dict, analysis: dict) -> bool:
    from scoring_system import record_signal_sent
    if not pipeline_result.get("should_notify"):
        return False
    symbol        = pipeline_result["symbol"]
    direction     = pipeline_result["direction"]
    current_price = analysis.get("current_price") or 0.0
    logger.info(f"[Notify/1H] {symbol} {direction.upper()} {pipeline_result['score']:.1f}pt — 발송")
    msg    = build_signal_message(pipeline_result, analysis)
    result = send_message(msg)
    if result:
        record_signal_sent(symbol, direction, current_price)
        logger.info("[Notify/1H] ✅ 발송 완료")
        return True
    logger.error("[Notify/1H] ❌ 발송 실패")
    return False
