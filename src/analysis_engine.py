"""
analysis_engine.py — 분석 엔진 (1h Bot v2.0)
────────────────────────────────────────────────────────────────────
[1h Bot v1.0 → v2.0 전체 변경 요약]

★ 타임프레임 전체 시프트
  entry:  15m → 1h   (df_15m → df_1h)
  mid:    1h  → 4h   (df_1h  → df_4h)
  macro:  4h  → 1d   (신규,   df_1d)

★ analyze_mtf_rsi(df_1h, df_4h, df_1d)
  출력 키 호환성 유지:
    "value"    → 1h RSI  (scoring: rsi_val_15m)
    "value_1h" → 4h RSI  (scoring: rsi_val_1h)
    "value_4h" → 1d RSI  (scoring: rsi_val_4h)
  눌림목 조건: 4h(mid) vs 1h(entry)
  macro 바이어스: 1d RSI

★ check_volume_confirmation(df_1h, df_4h=None)
  baseline: mean(df_4h[-32:-2]) / 4  (30×4h → 1h 환산, 120h)
  cur_vol:  df_1h[-2]
  폴백: df_4h 부족 시 df_1h 48개 직접 평균

★ calculate_ema_multiplier
  TF 키: "15m","1h","4h" → "1h","4h","1d"

★ [v2.0 신규] analyze_daily_bias(df_1d)
  1d 캔들 기반 방향 바이어스 (BULL/BEAR/NEUTRAL)
  조건 3개 중 2개 이상 충족:
    - 전일 양봉/음봉
    - 1d EMA9 vs EMA21
    - 당일가 vs 전일 종가

★ run_full_analysis
  반환 키:
    "adx_15m" → "adx_1h"  (entry ADX)
    신규: "regime_4h", "bos_choch_4h", "daily_bias"
────────────────────────────────────────────────────────────────────
"""
import logging
from typing import Optional
import numpy as np
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
# 1. 기본 유틸
# ══════════════════════════════════════════════

def calculate_atr(df, period=None):
    if df is None or df.empty or "high" not in df.columns:
        return pd.Series(dtype=float)
    period = period or config.ATR_PERIOD
    high, low, close = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0/period, adjust=False).mean()


def get_atr_state(df):
    if df is None or len(df) < config.ATR_PERIOD + 5:
        return {"current": 0.0, "pct": 0.0, "expanding": False, "ratio": 1.0}
    atr   = calculate_atr(df)
    cur   = float(atr.iloc[-1])
    avg   = float(atr.iloc[-20:].mean()) if len(atr) >= 20 else float(atr.mean())
    price = float(df["close"].iloc[-1])
    ratio = cur / avg if avg > 0 else 1.0
    return {"current": round(cur,6), "pct": round(cur/price*100,4),
            "expanding": bool(ratio>1.3), "ratio": round(ratio,3)}


def check_volume_confirmation(df_1h, df_4h=None):
    """
    [1h Bot] 거래량 baseline: 4h 캔들 30개 평균 / 4

    formula:
      baseline = mean(df_4h[-32:-2]) / 4  (30개 4h 완성 캔들 → 1h 환산)
      cur_vol  = df_1h[-2]                (직전 완성 1h 캔들)
      ratio    = cur_vol / baseline

    30×4h = 120h = 5 trading days → 평일 사이클 완전 포함, 요일 편향 제거
    폴백: df_4h 없거나 부족 시 df_1h 48개 직접 평균
    """
    _empty = {"confirmed": False, "strong": False, "ratio": 0.0, "score": 50.0,
              "current_vol": 0.0, "avg_vol": 0.0, "baseline_method": "none"}

    n   = config.VOLUME_4H_BASELINE_CANDLES  # 30
    req = n + 2                               # 32

    if df_4h is not None and len(df_4h) >= req:
        avg_4h_vol = float(df_4h["volume"].iloc[-(n+2):-2].mean())
        baseline   = avg_4h_vol / 4
        if df_1h is None or len(df_1h) < 3:
            return _empty
        cur_vol = float(df_1h["volume"].iloc[-2])
        method  = f"4h_{n*4}h"
    else:
        lb = config.VOLUME_CONFIRM_LOOKBACK  # 48
        if df_1h is None or len(df_1h) < lb + 3:
            return _empty
        cur_vol    = float(df_1h["volume"].iloc[-2])
        baseline   = float(df_1h["volume"].iloc[-(lb+2):-2].mean())
        avg_4h_vol = None
        method     = "1h_fallback"
        logger.debug(f"[Volume] 4h 데이터 부족 → 1h 폴백 (df_4h: {len(df_4h) if df_4h is not None else None}개)")

    if baseline <= 0:
        return _empty

    ratio     = cur_vol / baseline
    confirmed = ratio >= config.VOLUME_SPIKE_MULTIPLIER
    strong    = ratio >= config.VOLUME_STRONG_MULTIPLIER

    if   ratio <= 0:   score = 0.0
    elif ratio <= 0.5: score = (ratio / 0.5) * 25.0
    elif ratio <= 1.0: score = 25.0 + ((ratio - 0.5) / 0.5) * 25.0
    elif ratio <= 1.5: score = 50.0 + ((ratio - 1.0) / 0.5) * 20.0
    elif ratio <= 2.5: score = 70.0 + ((ratio - 1.5) / 1.0) * 20.0
    else:              score = min(100.0, 90.0 + (ratio - 2.5) * 4.0)

    logger.debug(
        f"[Volume/{method}] cur_1h:{cur_vol:.1f} "
        + (f"4h_avg:{avg_4h_vol:.1f} " if avg_4h_vol else "")
        + f"baseline:{baseline:.1f} ratio:{ratio:.3f}x → score:{score:.1f}pt"
    )
    return {
        "confirmed":       confirmed,
        "strong":          strong,
        "ratio":           round(ratio, 3),
        "score":           round(min(100.0, max(0.0, score)), 2),
        "current_vol":     round(cur_vol, 2),
        "avg_vol":         round(baseline, 2),
        "baseline_method": method,
    }


# ══════════════════════════════════════════════
# 2. 멀티TF RSI + 다이버전스
# ══════════════════════════════════════════════

def calculate_rsi(df, period=None):
    period = period or config.RSI_PERIOD
    close  = df["close"].astype(float)
    delta  = close.diff()
    gain, loss = delta.clip(lower=0), (-delta).clip(lower=0)
    alpha = 1.0 / period
    ag = gain.ewm(alpha=alpha, adjust=False).mean()
    al = loss.ewm(alpha=alpha, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return (100 - (100/(1+rs))).fillna(50)


def _rsi_to_score(v):
    if v <= 20:   ls = 95
    elif v <= 30: ls = 85 - (v-20)/10*10
    elif v <= 50: ls = 75 - (v-30)/20*25
    elif v <= 70: ls = 50 - (v-50)/20*30
    else:         ls = max(5, 20 - (v-70)*1.5)
    return round(min(100,max(0,ls)),2), round(min(100,max(0,100-ls)),2)


def _detect_bull_div(df, rsi, lb=6):
    if df is None or len(df) < lb*2: return False
    c = df["close"].values; r = rsi.values
    return bool(c[-lb:].min() < c[-lb*2:-lb].min() and r[-lb:].min() > r[-lb*2:-lb].min())

def _detect_bear_div(df, rsi, lb=6):
    if df is None or len(df) < lb*2: return False
    c = df["close"].values; r = rsi.values
    return bool(c[-lb:].max() > c[-lb*2:-lb].max() and r[-lb:].max() < r[-lb*2:-lb].max())

def _detect_hidden_bull_div(df, rsi, lb=8):
    if df is None or len(df) < lb*2: return False
    c = df["close"].values; r = rsi.values
    return bool(c[-lb:].min() > c[-lb*2:-lb].min() and r[-lb:].min() < r[-lb*2:-lb].min())

def _detect_hidden_bear_div(df, rsi, lb=8):
    if df is None or len(df) < lb*2: return False
    c = df["close"].values; r = rsi.values
    return bool(c[-lb:].max() < c[-lb*2:-lb].max() and r[-lb:].max() > r[-lb*2:-lb].max())


def analyze_mtf_rsi(df_1h, df_4h, df_1d):
    """
    [1h Bot] 멀티TF RSI

    입력:  df_1h (entry), df_4h (mid), df_1d (macro)
    출력 키:
      "value"    → 1h RSI  (scoring: rsi_val_15m)
      "value_1h" → 4h RSI  (scoring: rsi_val_1h)
      "value_4h" → 1d RSI  (scoring: rsi_val_4h)

    눌림목: 4h(mid) vs 1h(entry)
    macro 바이어스: 1d RSI
    """
    def _get(df):
        if df is None or len(df) < config.RSI_PERIOD + 1: return None
        return float(calculate_rsi(df).iloc[-1])

    v_1h = _get(df_1h)   # entry
    v_4h = _get(df_4h)   # mid
    v_1d = _get(df_1d)   # macro

    weights   = [(v_1h, 0.50), (v_4h, 0.30), (v_1d, 0.20)]
    available = [(v, w) for v, w in weights if v is not None]
    if not available: return _empty_rsi()

    total_w    = sum(w for _, w in available)
    v_weighted = sum(v*w for v, w in available) / total_w
    v_entry    = v_1h if v_1h is not None else v_weighted
    state      = ("oversold"   if v_entry <= config.RSI_OVERSOLD  else
                  "overbought" if v_entry >= config.RSI_OVERBOUGHT else "neutral")

    long_score_raw, short_score_raw = _rsi_to_score(v_weighted)

    # ── 눌림목: 4h(mid) 방향 + 1h(entry) 되돌림 ─────────────
    pls = (v_4h is not None and v_4h > 58 and v_1h is not None and v_1h < 40)
    plw = (v_4h is not None and v_4h > 52 and v_1h is not None and v_1h < 44 and not pls)
    plm = (v_4h is not None and v_4h > 48 and v_1h is not None and v_1h < 42 and not pls and not plw)
    pl  = pls or plw or plm

    pss = (v_4h is not None and v_4h < 42 and v_1h is not None and v_1h > 60)
    psw = (v_4h is not None and v_4h < 48 and v_1h is not None and v_1h > 56 and not pss)
    psm = (v_4h is not None and v_4h < 52 and v_1h is not None and v_1h > 58 and not pss and not psw)
    ps  = pss or psw or psm

    # ── macro 바이어스: 1d RSI ───────────────────────────────
    macro_bull = v_1d is not None and v_1d > 52
    macro_bear = v_1d is not None and v_1d < 48

    pla = (14 if pls else 9 if plw else 5 if plm else 0)
    psa = (14 if pss else 9 if psw else 5 if psm else 0)

    if pl:
        long_score_raw  = min(100, long_score_raw  + pla)
        short_score_raw = max(0,   short_score_raw - pla)
    if ps:
        short_score_raw = min(100, short_score_raw + psa)
        long_score_raw  = max(0,   long_score_raw  - psa)
    if macro_bull and long_score_raw  > 50: long_score_raw  = min(100, long_score_raw  + 5)
    if macro_bear and short_score_raw > 50: short_score_raw = min(100, short_score_raw + 5)

    long_score  = round(min(100, max(0, long_score_raw)),  2)
    short_score = round(min(100, max(0, short_score_raw)), 2)

    # ── 다이버전스 (entry TF = 1h) ───────────────────────────
    rsi_1h_s = calculate_rsi(df_1h) if df_1h is not None and len(df_1h) >= 12 else None
    bull_div  = bool(_detect_bull_div(df_1h,   rsi_1h_s)) if rsi_1h_s is not None else False
    bear_div  = bool(_detect_bear_div(df_1h,   rsi_1h_s)) if rsi_1h_s is not None else False
    hbd       = bool(_detect_hidden_bull_div(df_1h, rsi_1h_s)) if rsi_1h_s is not None and len(df_1h) >= 16 else False
    hsd       = bool(_detect_hidden_bear_div(df_1h, rsi_1h_s)) if rsi_1h_s is not None and len(df_1h) >= 16 else False

    v1hs = f"{v_1h:.1f}" if v_1h is not None else "N/A"
    v4hs = f"{v_4h:.1f}" if v_4h is not None else "N/A"
    v1ds = f"{v_1d:.1f}" if v_1d is not None else "N/A"
    pb_tag = ((" ★눌림목롱(강)" if pls else " ★눌림목롱(약)" if plw else " ★눌림목롱(미)" if plm else "") +
              (" ★눌림목숏(강)" if pss else " ★눌림목숏(약)" if psw else " ★눌림목숏(미)" if psm else ""))
    div_tag = ((" 📊히든롱다이버" if hbd else "") + (" 📊히든숏다이버" if hsd else ""))
    logger.info(
        f"[MTF-RSI] 1h:{v1hs} 4h:{v4hs} 1d:{v1ds} 가중:{v_weighted:.1f} [{state}] "
        f"롱:{long_score:.1f}pt 숏:{short_score:.1f}pt" + pb_tag + div_tag
    )

    return {
        "value":          round(v_entry, 2),
        "value_1h":       round(v_4h, 2) if v_4h is not None else None,  # scoring: rsi_val_1h = 4h
        "value_4h":       round(v_1d, 2) if v_1d is not None else None,  # scoring: rsi_val_4h = 1d
        "value_weighted": round(v_weighted, 2),
        "state":          state,
        "long_score":     long_score,
        "short_score":    short_score,
        "bullish_divergence": bull_div,
        "bearish_divergence": bear_div,
        "hidden_bull_div":    hbd,
        "hidden_bear_div":    hsd,
        "pullback_long":        pl,
        "pullback_short":       ps,
        "pullback_long_strong": pls,
        "pullback_long_weak":   plw,
        "pullback_long_micro":  plm,
        "pullback_short_strong": pss,
        "pullback_short_weak":   psw,
        "pullback_short_micro":  psm,
    }


def _empty_rsi():
    return {
        "value": 50.0, "value_1h": None, "value_4h": None, "value_weighted": 50.0,
        "state": "neutral", "long_score": 50.0, "short_score": 50.0,
        "bullish_divergence": False, "bearish_divergence": False,
        "hidden_bull_div": False, "hidden_bear_div": False,
        "pullback_long": False, "pullback_short": False,
        "pullback_long_strong": False, "pullback_long_weak": False, "pullback_long_micro": False,
        "pullback_short_strong": False, "pullback_short_weak": False, "pullback_short_micro": False,
    }


def get_rsi_signal(df):
    if df is None or len(df) < config.RSI_PERIOD + 1: return _empty_rsi()
    rsi_s = calculate_rsi(df); v = float(rsi_s.iloc[-1])
    state = "oversold" if v <= config.RSI_OVERSOLD else ("overbought" if v >= config.RSI_OVERBOUGHT else "neutral")
    ls, ss = _rsi_to_score(v)
    return {
        "value": round(v,2), "value_1h": None, "value_4h": None, "value_weighted": round(v,2),
        "state": state, "long_score": ls, "short_score": ss,
        "bullish_divergence": bool(_detect_bull_div(df, rsi_s)),
        "bearish_divergence": bool(_detect_bear_div(df, rsi_s)),
        "hidden_bull_div": False, "hidden_bear_div": False,
        "pullback_long": False, "pullback_short": False,
        "pullback_long_strong": False, "pullback_long_weak": False, "pullback_long_micro": False,
        "pullback_short_strong": False, "pullback_short_weak": False, "pullback_short_micro": False,
    }


# ══════════════════════════════════════════════
# 3. 볼린저 밴드 (entry TF = 1h)
# ══════════════════════════════════════════════

def analyze_bollinger_bands(df):
    period = config.BOLLINGER_PERIOD; std_dev = config.BOLLINGER_STD
    if df is None or len(df) < period + 1: return _empty_bb()
    close = df["close"].astype(float)
    mid   = close.rolling(period).mean()
    std   = close.rolling(period).std()
    upper = mid + std_dev*std
    lower = mid - std_dev*std
    bw_s  = (upper - lower) / mid.replace(0, np.nan)
    cur_bw = float(bw_s.iloc[-1]) if not pd.isna(bw_s.iloc[-1]) else 0.0
    avg_bw = (float(bw_s.iloc[-50:].mean()) if len(bw_s) >= 50 else
              float(bw_s.iloc[-20:].mean()) if len(bw_s) >= 20 else cur_bw)
    squeeze    = bool(cur_bw < avg_bw * config.REGIME_SQUEEZE_RATIO and avg_bw > 0)
    c_close    = float(close.iloc[-1])
    c_upper    = float(upper.iloc[-1])
    c_lower    = float(lower.iloc[-1])
    c_mid      = float(mid.iloc[-1])
    band_range = c_upper - c_lower
    if band_range <= 0: return _empty_bb()
    pct_b = (c_close - c_lower) / band_range
    if   pct_b <= 0.0:  ls,ss,state = 92, 8, "lower_breakout"
    elif pct_b <= 0.15: ls,ss,state = 82,18, "near_lower"
    elif pct_b <= 0.35: ls,ss,state = 65,35, "lower_zone"
    elif pct_b <= 0.65: ls,ss,state = 50,50, "middle"
    elif pct_b <= 0.85: ls,ss,state = 35,65, "upper_zone"
    elif pct_b <= 1.0:  ls,ss,state = 18,82, "near_upper"
    else:               ls,ss,state =  8,92, "upper_breakout"
    pctb_s = (close - lower) / (upper - lower).replace(0, np.nan).fillna(0.5)
    lower_streak = upper_streak = 0
    for pb in reversed(pctb_s.iloc[-10:].values):
        if pb < 0.0: lower_streak += 1
        else: break
    for pb in reversed(pctb_s.iloc[-10:].values):
        if pb > 1.0: upper_streak += 1
        else: break
    return {
        "long_score": ls, "short_score": ss, "pct_b": round(pct_b,4), "squeeze": squeeze,
        "state": state, "upper": round(c_upper,6), "lower": round(c_lower,6), "mid": round(c_mid,6),
        "band_width": round(cur_bw,6), "avg_band_width": round(avg_bw,6),
        "lower_streak": lower_streak, "upper_streak": upper_streak, "available": True,
    }

def _empty_bb():
    return {
        "long_score": 50, "short_score": 50, "pct_b": 0.5, "squeeze": False, "state": "unknown",
        "upper": 0, "lower": 0, "mid": 0, "band_width": 0, "avg_band_width": 0,
        "lower_streak": 0, "upper_streak": 0, "available": False,
    }


# ══════════════════════════════════════════════
# 4. EMA 배율 (TF 키: "1h","4h","1d")
# ══════════════════════════════════════════════

def _calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def _ema_direction(df):
    if df is None or len(df) < config.EMA_SLOW + 1: return "neutral"
    close    = df["close"].astype(float)
    ema_fast = float(_calc_ema(close, config.EMA_FAST).iloc[-1])
    ema_slow = float(_calc_ema(close, config.EMA_SLOW).iloc[-1])
    gap_pct  = abs(ema_fast - ema_slow) / ema_slow if ema_slow > 0 else 0
    if gap_pct < 0.0005: return "neutral"
    return "bullish" if ema_fast > ema_slow else "bearish"

def calculate_ema_multiplier(ohlcv_dict, direction, regime="UNKNOWN"):
    """[1h Bot] TF 키: "1h" (entry), "4h" (mid), "1d" (macro)"""
    tf_signals = {
        "1h": _ema_direction(ohlcv_dict.get("1h")),
        "4h": _ema_direction(ohlcv_dict.get("4h")),
        "1d": _ema_direction(ohlcv_dict.get("1d")),
    }
    opposite      = "bearish" if direction == "long" else "bullish"
    reverse_count = sum(1 for sig in tf_signals.values() if sig == opposite)
    same_count    = sum(1 for sig in tf_signals.values() if sig == ("bullish" if direction=="long" else "bearish"))
    regime_mult_table = config.REGIME_EMA_MULTIPLIERS.get(regime, config.EMA_MULTIPLIER)
    multiplier    = regime_mult_table.get(reverse_count, 1.0)
    if same_count == 3:      ema_dir = "bullish" if direction=="long" else "bearish"
    elif reverse_count == 3: ema_dir = "bearish" if direction=="long" else "bullish"
    else:                    ema_dir = "mixed"
    logger.info(f"[EMA배율/{direction.upper()}] {tf_signals} → ×{multiplier:.2f}  [{regime}]")
    return {
        "tf_signals": tf_signals, "same_count": same_count, "reverse_count": reverse_count,
        "multiplier": multiplier, "direction": ema_dir, "regime": regime,
        "reason": f"EMA {same_count}/3 {direction}방향 일치 (역방향:{reverse_count}개 → ×{multiplier:.2f}) [{regime}]",
    }


# ══════════════════════════════════════════════
# 5. ADX
# ══════════════════════════════════════════════

def calculate_adx(df, period=None):
    period = period or config.ADX_PERIOD
    _n = {"adx":0.0,"plus_di":0.0,"minus_di":0.0,"trend_dir":"neutral","strength":"none","multiplier":1.0,"available":False}
    if df is None or len(df) < period*2+1: return _n
    high  = df["high"].astype(float); low = df["low"].astype(float); close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([high-low,(high-prev_close).abs(),(low-prev_close).abs()],axis=1).max(axis=1)
    up_move  = high - high.shift(1); down_move = low.shift(1) - low
    plus_dm  = up_move.where((up_move>down_move)&(up_move>0), 0.0)
    minus_dm = down_move.where((down_move>up_move)&(down_move>0), 0.0)
    alpha    = 1.0/period
    atr_ema  = tr.ewm(alpha=alpha,adjust=False).mean()
    plus_ema = plus_dm.ewm(alpha=alpha,adjust=False).mean()
    minus_ema= minus_dm.ewm(alpha=alpha,adjust=False).mean()
    plus_di  = 100*plus_ema /atr_ema.replace(0,np.nan)
    minus_di = 100*minus_ema/atr_ema.replace(0,np.nan)
    dx  = 100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan)
    adx = dx.ewm(alpha=alpha,adjust=False).mean()
    c_adx = round(float(adx.iloc[-1])    if not pd.isna(adx.iloc[-1])    else 0.0, 2)
    c_pdi = round(float(plus_di.iloc[-1]) if not pd.isna(plus_di.iloc[-1]) else 0.0, 2)
    c_mdi = round(float(minus_di.iloc[-1])if not pd.isna(minus_di.iloc[-1])else 0.0, 2)
    if c_adx < config.ADX_NO_TREND:     strength,mult = "none",  0.70
    elif c_adx < config.ADX_WEAK_TREND: strength,mult = "weak",  0.85
    elif c_adx < config.ADX_STRONG:     strength,mult = "normal",1.00
    else:                                strength,mult = "strong",1.00
    trend_dir = "bullish" if c_pdi>c_mdi else ("bearish" if c_mdi>c_pdi else "neutral")
    return {"adx":c_adx,"plus_di":c_pdi,"minus_di":c_mdi,"trend_dir":trend_dir,
            "strength":strength,"multiplier":mult,"available":True}


# ══════════════════════════════════════════════
# 6. 펀딩비
# ══════════════════════════════════════════════

def analyze_funding_rate(funding_data):
    if funding_data is None:
        return {"rate":0.0,"rate_pct":0.0,"long_score":50.0,"short_score":50.0,"bias":"neutral","strength":"neutral","available":False}
    rate = float(funding_data.get("rate",0.0))
    if rate <= config.FUNDING_LONG_STRONG:
        ls=90+min(10,abs(rate-config.FUNDING_LONG_STRONG)/abs(config.FUNDING_LONG_STRONG)*10); ss=10; bias,st="long_favorable","strong"
    elif rate <= config.FUNDING_LONG_MILD:
        ratio=(rate-config.FUNDING_LONG_MILD)/(config.FUNDING_LONG_STRONG-config.FUNDING_LONG_MILD)
        ls=65+ratio*25; ss=35-ratio*25; bias,st="long_favorable","mild"
    elif rate >= config.FUNDING_SHORT_STRONG:
        ss=90+min(10,(rate-config.FUNDING_SHORT_STRONG)/config.FUNDING_SHORT_STRONG*10); ls=10; bias,st="short_favorable","strong"
    elif rate >= config.FUNDING_SHORT_MILD:
        ratio=(rate-config.FUNDING_SHORT_MILD)/(config.FUNDING_SHORT_STRONG-config.FUNDING_SHORT_MILD)
        ss=65+ratio*25; ls=35-ratio*25; bias,st="short_favorable","mild"
    else:
        t=rate/config.FUNDING_LONG_MILD if rate<0 else rate/config.FUNDING_SHORT_MILD
        ls=50-t*15; ss=50+t*15; bias,st="neutral","neutral"
    ls=round(min(100,max(0,ls)),2); ss=round(min(100,max(0,ss)),2)
    logger.info(f"[FundingRate] {rate*100:+.4f}% [{bias}] 롱:{ls:.1f} 숏:{ss:.1f}")
    return {"rate":rate,"rate_pct":round(rate*100,6),"long_score":ls,"short_score":ss,"bias":bias,"strength":st,"available":True}


# ══════════════════════════════════════════════
# 7. 롱숏 비율
# ══════════════════════════════════════════════

def analyze_long_short_ratio(ls_data, regime_name="RANGING"):
    if not ls_data or not ls_data.get("available"):
        return {"long_score":50,"short_score":50,"bias":"neutral","long_pct":0.5,"short_pct":0.5,"available":False}
    long_pct=ls_data.get("long_pct",0.5); short_pct=ls_data.get("short_pct",0.5)
    if regime_name=="TRENDING":
        if long_pct>=0.60:    ls,ss,bias=80,20,"long_momentum"
        elif long_pct>=0.52:  ls,ss,bias=62,38,"long_lean"
        elif short_pct>=0.60: ls,ss,bias=20,80,"short_momentum"
        elif short_pct>=0.52: ls,ss,bias=38,62,"short_lean"
        else:                 ls,ss,bias=50,50,"neutral"
    else:
        if long_pct>=config.LS_LONG_EXTREME:     ls,ss,bias=10,90,"short_extreme"
        elif long_pct>=config.LS_LONG_HIGH:
            r=(long_pct-config.LS_LONG_HIGH)/(config.LS_LONG_EXTREME-config.LS_LONG_HIGH)
            ss=70+r*20; ls=100-ss; bias="short_favorable"
        elif short_pct>=config.LS_SHORT_EXTREME: ls,ss,bias=90,10,"long_extreme"
        elif short_pct>=config.LS_SHORT_HIGH:
            r=(short_pct-config.LS_SHORT_HIGH)/(config.LS_SHORT_EXTREME-config.LS_SHORT_HIGH)
            ls=70+r*20; ss=100-ls; bias="long_favorable"
        else:
            t=(long_pct-0.5)*2; ss=50+t*10; ls=100-ss; bias="neutral"
    ls=round(min(100,max(0,ls)),2); ss=round(min(100,max(0,ss)),2)
    logger.info(f"[LS비율] 롱:{long_pct*100:.1f}% [{bias}/{regime_name}] 롱pt:{ls} 숏pt:{ss}")
    return {"long_score":ls,"short_score":ss,"bias":bias,"long_pct":long_pct,"short_pct":short_pct,"available":True}


# ══════════════════════════════════════════════
# 8. Taker 비율
# ══════════════════════════════════════════════

def analyze_taker_volume(taker_data):
    if not taker_data or not taker_data.get("available"):
        return {"long_score":50.0,"short_score":50.0,"bias":"neutral","strength":"neutral","available":False}
    buy_ratio=taker_data.get("buy_ratio",0.5); sell_ratio=taker_data.get("sell_ratio",0.5)
    bias=taker_data.get("bias","neutral"); strength=taker_data.get("strength","neutral")
    if buy_ratio>=config.TAKER_STRONG_BUY:
        ls=85+(buy_ratio-config.TAKER_STRONG_BUY)/(1-config.TAKER_STRONG_BUY)*10; ss=15
    elif buy_ratio>=0.55:
        ls=65+(buy_ratio-0.55)/(config.TAKER_STRONG_BUY-0.55)*20; ss=100-ls
    elif sell_ratio>=config.TAKER_STRONG_SELL:
        ss=85+(sell_ratio-config.TAKER_STRONG_SELL)/(1-config.TAKER_STRONG_SELL)*10; ls=15
    elif sell_ratio>=0.55:
        ss=65+(sell_ratio-0.55)/(config.TAKER_STRONG_SELL-0.55)*20; ls=100-ss
    else:
        ls=50+(buy_ratio-0.5)*80; ss=100-ls
    ls=round(min(100,max(0,ls)),2); ss=round(min(100,max(0,ss)),2)
    logger.info(f"[Taker] 매수:{buy_ratio*100:.1f}% [{bias}/{strength}] 롱:{ls:.1f} 숏:{ss:.1f}")
    return {"long_score":ls,"short_score":ss,"bias":bias,"strength":strength,
            "buy_ratio":buy_ratio,"sell_ratio":sell_ratio,"available":True}


# ══════════════════════════════════════════════
# 9. 청산 프록시 (entry TF = 1h)
# ══════════════════════════════════════════════

def analyze_liquidations(liq_data, df_1h=None):
    """[1h Bot] entry TF = 1h 기준 핀바/꼬리 분석"""
    _empty = {
        "long_score":50,"short_score":50,"signal":"none","is_large":False,
        "long_liq_proxy":0.0,"short_liq_proxy":0.0,
        "favorable_direction":None,"display_hint":None,"available":False,
    }
    if df_1h is None or len(df_1h) < 15: return _empty
    close  = df_1h["close"].astype(float); high   = df_1h["high"].astype(float)
    low    = df_1h["low"].astype(float);   open_  = df_1h["open"].astype(float)
    volume = df_1h["volume"].astype(float)
    avg_vol = float(volume.iloc[-21:-1].mean()) if len(df_1h) >= 21 else float(volume.iloc[:-1].mean())
    if avg_vol <= 0: return _empty
    long_liq_score = short_liq_score = 0.0
    for i in range(-5, 0):
        c=float(close.iloc[i]); h=float(high.iloc[i]); l=float(low.iloc[i])
        o=float(open_.iloc[i]); v=float(volume.iloc[i])
        cr = h - l
        if cr < 1e-9: continue
        bt=max(o,c); bb_=min(o,c); lw=bb_-l; uw=h-bt
        lw_pct=lw/cr; uw_pct=uw/cr; vr=v/avg_vol
        if lw_pct > 0.35 and vr > 1.5: long_liq_score  = max(long_liq_score,  min(1.0, lw_pct*vr/2.0))
        if uw_pct > 0.35 and vr > 1.5: short_liq_score = max(short_liq_score, min(1.0, uw_pct*vr/2.0))
    price_chg = 0.0
    if len(df_1h) >= 7:
        p0=float(close.iloc[-7]); p1=float(close.iloc[-1])
        price_chg = abs(p1-p0)/p0 if p0 > 0 else 0.0
    is_large = price_chg > 0.02 and (long_liq_score > 0.25 or short_liq_score > 0.25)
    signal   = "none"
    if long_liq_score > short_liq_score and long_liq_score > 0.15:    signal = "long_liq_detected"
    elif short_liq_score > long_liq_score and short_liq_score > 0.15: signal = "short_liq_detected"
    ls, ss = 50, 50
    if signal == "long_liq_detected":
        ls=round(60+long_liq_score*30,2); ss=round(40-long_liq_score*10,2)
        if is_large: ls = min(100, ls+10)
        logger.info(f"[청산프록시] 💥 롱청산 {'대규모' if is_large else ''} → 반등 기대")
    elif signal == "short_liq_detected":
        ss=round(60+short_liq_score*30,2); ls=round(40-short_liq_score*10,2)
        if is_large: ss = min(100, ss+10)
        logger.info(f"[청산프록시] 💥 숏청산 {'대규모' if is_large else ''} → 되돌림 기대")
    _liq_display = {
        "long_liq_detected":  ("long",  "롱청산 감지 → 반등 기대"),
        "short_liq_detected": ("short", "숏청산 감지 → 되돌림 기대"),
    }
    fav_dir, display_hint = _liq_display.get(signal, (None, None))
    return {
        "long_score": round(min(100,max(0,ls)),2), "short_score": round(min(100,max(0,ss)),2),
        "signal": signal, "is_large": is_large,
        "long_liq_proxy": round(long_liq_score,4), "short_liq_proxy": round(short_liq_score,4),
        "favorable_direction": fav_dir, "display_hint": display_hint, "available": True,
    }


# ══════════════════════════════════════════════
# 10. 시장 국면 분류 (entry TF = 1h)
# ══════════════════════════════════════════════

def classify_market_regime(df_1h, adx, bb):
    """[1h Bot] entry TF(1h) 기준 국면 분류. df_4h도 동일 함수로 호출 가능."""
    if df_1h is None or len(df_1h) < 25 or not bb.get("available"):
        return {"regime":"UNKNOWN","threshold":64,"description":"데이터 부족","icon":"❓"}
    adx_val=adx.get("adx",0.0); bw=bb.get("band_width",0.0); avg_bw=bb.get("avg_band_width",bw)
    squeeze=bb.get("squeeze",False); bw_ratio=bw/avg_bw if avg_bw>0 else 1.0
    ma20_cross_count=0; efficiency_ratio=1.0
    try:
        close=df_1h["close"].astype(float); ma20_full=close.rolling(20).mean()
        lookback=min(40,len(close)-1)
        seg_close=close.iloc[-lookback-1:].values; seg_ma20=ma20_full.iloc[-lookback-1:].values
        for i in range(1,len(seg_close)):
            if pd.isna(seg_ma20[i]) or pd.isna(seg_ma20[i-1]): continue
            if (seg_close[i-1]>seg_ma20[i-1])!=(seg_close[i]>seg_ma20[i]): ma20_cross_count+=1
        seg=close.iloc[-lookback:].values
        net_chg   = abs(float(seg[-1])-float(seg[0]))
        total_chg = sum(abs(seg[i]-seg[i-1]) for i in range(1,len(seg)))
        efficiency_ratio = round(net_chg/total_chg,4) if total_chg>0 else 1.0
    except: pass
    is_ranging_by_cross=((ma20_cross_count>=2 and efficiency_ratio<0.35) or (efficiency_ratio<0.15))
    if squeeze and adx_val<config.REGIME_TREND_ADX:
        regime="SQUEEZE"; desc=f"BB 스퀴즈+ADX낮음({adx_val:.0f}) — 큰 움직임 대기"; icon="🔄"
    elif adx_val>=config.REGIME_STRONG_ADX and bw_ratio>=1.2:
        regime="EXPLOSIVE"; desc=f"ADX강({adx_val:.0f})+BB확장({bw_ratio:.1f}x) — 변동성 폭발"; icon="💥"
    elif is_ranging_by_cross:
        regime="RANGING"; desc=f"MA20 교차 {ma20_cross_count}회+ER:{efficiency_ratio:.2f} — 박스권 (ADX:{adx_val:.0f})"; icon="↔️"
    elif adx_val>=config.REGIME_TREND_ADX:
        regime="TRENDING"; desc=f"ADX추세({adx_val:.0f}) — 추세 진행 중"; icon="📈"
    else:
        regime="RANGING"; desc=f"ADX낮음({adx_val:.0f})+BB평행 — 박스권 횡보"; icon="↔️"
    threshold = config.REGIME_THRESHOLDS.get(regime, 64)
    logger.info(f"[국면] {icon} {regime} — {desc} (임계값:{threshold}pt)")
    return {
        "regime":regime,"threshold":threshold,"description":desc,"icon":icon,
        "adx":adx_val,"bw_ratio":round(bw_ratio,3),"squeeze":squeeze,
        "ma20_cross_count":ma20_cross_count,"efficiency_ratio":efficiency_ratio,
    }


# ══════════════════════════════════════════════
# 11. 게이트
# ══════════════════════════════════════════════

def evaluate_gates(direction, funding, ls_ratio_result):
    funding_bias=funding.get("bias","neutral"); ls_bias=ls_ratio_result.get("bias","neutral")
    penalty_factor=1.0; penalty_reason=None
    if direction=="long":
        fr_bad=(funding_bias=="short_favorable"); ls_bad=(ls_bias in ("short_favorable","short_extreme"))
    else:
        fr_bad=(funding_bias=="long_favorable");  ls_bad=(ls_bias in ("long_favorable","long_extreme"))
    if fr_bad and ls_bad:
        penalty_factor=config.GATE_PENALTY_DUAL
        penalty_reason=f"펀딩비·롱숏비율 모두 {direction} 불리 — 복합 패널티 ×{penalty_factor}"
        logger.info(f"[Gate] ⚠️ {direction.upper()} 복합 패널티")
    elif fr_bad:
        penalty_factor=config.GATE_PENALTY_SINGLE
        penalty_reason=f"펀딩비 {direction} 불리 ×{penalty_factor}"
        logger.info(f"[Gate] ⚠️ {direction.upper()} 펀딩비 불리")
    elif ls_bad:
        penalty_factor=config.GATE_PENALTY_SINGLE
        penalty_reason=f"롱숏비율 {direction} 불리 ×{penalty_factor}"
        logger.info(f"[Gate] ⚠️ {direction.upper()} 롱숏비율 불리")
    else:
        logger.info(f"[Gate] ✅ {direction.upper()} 통과")
    return {"passed":True,"funding_penalty":penalty_factor,"block_reason":None,"penalty_reason":penalty_reason}


# ══════════════════════════════════════════════
# 12. FVG
# ══════════════════════════════════════════════

def detect_fvg(df, lookback=30):
    _empty = {"in_bullish_fvg":False,"in_bearish_fvg":False,"bullish_fvg_count":0,"bearish_fvg_count":0,
              "nearest_bullish_fvg":None,"nearest_bearish_fvg":None}
    if df is None or len(df) < 5: return _empty
    try:
        lb=min(lookback,len(df)); high=df["high"].astype(float).values[-lb:]
        low=df["low"].astype(float).values[-lb:]; close=df["close"].astype(float).values[-lb:]
        current=close[-1]; bullish_fvgs=[]; bearish_fvgs=[]
        for i in range(2,lb-2):
            if high[i-2]<low[i]:  bullish_fvgs.append((high[i-2],low[i]))
            if low[i-2] >high[i]: bearish_fvgs.append((high[i],   low[i-2]))
        active_bull=[(b,t) for b,t in bullish_fvgs if current>=b*0.99]
        active_bear=[(b,t) for b,t in bearish_fvgs if current<=t*1.01]
        in_bullish_fvg=any(b<=current<=t for b,t in active_bull)
        in_bearish_fvg=any(b<=current<=t for b,t in active_bear)
        nearest_bull=(min(active_bull,key=lambda x:abs((x[0]+x[1])/2-current)) if active_bull else None)
        nearest_bear=(min(active_bear,key=lambda x:abs((x[0]+x[1])/2-current)) if active_bear else None)
        if in_bullish_fvg: logger.info("[FVG] ★ 강세 FVG 내부 — 기관 매수 구간 (롱 유리)")
        if in_bearish_fvg: logger.info("[FVG] ★ 약세 FVG 내부 — 기관 매도 구간 (숏 유리)")
        return {
            "in_bullish_fvg":in_bullish_fvg,"in_bearish_fvg":in_bearish_fvg,
            "bullish_fvg_count":len(active_bull),"bearish_fvg_count":len(active_bear),
            "nearest_bullish_fvg":(round(nearest_bull[0],4),round(nearest_bull[1],4)) if nearest_bull else None,
            "nearest_bearish_fvg":(round(nearest_bear[0],4),round(nearest_bear[1],4)) if nearest_bear else None,
        }
    except Exception as e:
        logger.warning(f"[FVG] 오류: {e}"); return _empty


# ══════════════════════════════════════════════
# 13. BOS / CHoCH
# ══════════════════════════════════════════════

def detect_bos_choch(df, lookback=60, n=3):
    """
    [1h Bot]
    1h 호출: lookback=60, n=3  (60h, ±3캔들 스윙)
    4h 호출: lookback=30, n=2  (120h, ±2캔들 스윙 — 더 넓은 구조)
    """
    _empty = {"bos_bullish":False,"bos_bearish":False,"choch_bullish":False,"choch_bearish":False,
              "last_swing_high":None,"last_swing_low":None}
    if df is None or len(df) < max(20,n*4): return _empty
    try:
        lb=min(lookback,len(df)-1); highs=df["high"].astype(float).values[-lb:]
        lows=df["low"].astype(float).values[-lb:]; closes=df["close"].astype(float).values[-lb:]
        s_highs=[]; s_lows=[]
        for i in range(n,lb-n-1):
            wh=highs[max(0,i-n):i+n+1]; wl=lows[max(0,i-n):i+n+1]
            if len(wh)==2*n+1:
                if highs[i]==max(wh): s_highs.append((i,highs[i]))
                if lows[i] ==min(wl): s_lows.append((i,lows[i]))
        current_close=closes[-1]
        bos_bullish=bos_bearish=choch_bullish=choch_bearish=False
        last_sh=s_highs[-1][1] if s_highs else None
        last_sl=s_lows[-1][1]  if s_lows  else None
        if last_sh and current_close>last_sh: bos_bullish=True
        if last_sl and current_close<last_sl: bos_bearish=True
        if not bos_bearish and len(s_highs)>=2 and len(s_lows)>=1:
            sh1,sh2=s_highs[-2],s_highs[-1]
            if sh2[1]>sh1[1]:
                il=[sl for sl in s_lows if sh1[0]<sl[0]<sh2[0]]
                if il and current_close<min(sl[1] for sl in il): choch_bearish=True
        if not bos_bullish and len(s_lows)>=2 and len(s_highs)>=1:
            sl1,sl2=s_lows[-2],s_lows[-1]
            if sl2[1]<sl1[1]:
                ih=[sh for sh in s_highs if sl1[0]<sh[0]<sl2[0]]
                if ih and current_close>max(sh[1] for sh in ih): choch_bullish=True
        if bos_bullish:   logger.info(f"[BOS/{lookback}c] ★ 상승 BOS")
        if bos_bearish:   logger.info(f"[BOS/{lookback}c] ★ 하락 BOS")
        if choch_bullish: logger.info(f"[CHoCH/{lookback}c] ⚠️ 상승전환")
        if choch_bearish: logger.info(f"[CHoCH/{lookback}c] ⚠️ 하락전환")
        return {"bos_bullish":bos_bullish,"bos_bearish":bos_bearish,
                "choch_bullish":choch_bullish,"choch_bearish":choch_bearish,
                "last_swing_high":round(last_sh,4) if last_sh else None,
                "last_swing_low": round(last_sl,4) if last_sl else None}
    except Exception as e:
        logger.warning(f"[BOS/CHoCH] 오류: {e}"); return _empty


# ══════════════════════════════════════════════
# 14. 피보나치
# ══════════════════════════════════════════════

def check_fibonacci_levels(df):
    _empty = {"in_golden_pocket_long":False,"near_key_level_long":False,"long_retracement":None,
              "in_golden_pocket_short":False,"near_key_level_short":False,"short_retracement":None,
              "swing_high":None,"swing_low":None}
    if df is None or len(df) < config.FIB_LOOKBACK//2: return _empty
    try:
        lb=min(config.FIB_LOOKBACK,len(df)); closes=df["close"].astype(float).values[-lb:]
        highs=df["high"].astype(float).values[-lb:]; lows=df["low"].astype(float).values[-lb:]
        current=closes[-1]; end=lb-5
        sh_idx=int(np.argmax(highs[:end])); sl_idx=int(np.argmin(lows[:end]))
        swing_high=highs[sh_idx]; swing_low=lows[sl_idx]
        swing_low_for_long   = min(lows[:sh_idx+1])  if sh_idx>0 else swing_low
        swing_high_for_short = max(highs[:sl_idx+1]) if sl_idx>0 else swing_high
        long_range  = swing_high - swing_low_for_long
        short_range = swing_high_for_short - swing_low
        long_retr=short_retr=None
        if long_range/swing_high>=config.FIB_MIN_SWING_PCT and current<swing_high:
            long_retr=(swing_high-current)/long_range
        if short_range/swing_high_for_short>=config.FIB_MIN_SWING_PCT and current>swing_low:
            short_retr=(current-swing_low)/short_range
        TOL=config.FIB_TOLERANCE
        def _gp(r): return r is not None and 0.618<=r<=0.650
        def _kl(r): return r is not None and any(abs(r-l)<=TOL for l in [0.382,0.500,0.786])
        in_gp_long=_gp(long_retr); in_gp_short=_gp(short_retr)
        near_l=_kl(long_retr) and not in_gp_long; near_s=_kl(short_retr) and not in_gp_short
        if in_gp_long:  logger.info(f"[피보] ★ 롱 황금포켓 {long_retr*100:.1f}%")
        elif near_l:    logger.info(f"[피보] 롱 주요레벨 {long_retr*100:.1f}%")
        if in_gp_short: logger.info(f"[피보] ★ 숏 황금포켓 {short_retr*100:.1f}%")
        elif near_s:    logger.info(f"[피보] 숏 주요레벨 {short_retr*100:.1f}%")
        return {
            "in_golden_pocket_long":in_gp_long, "near_key_level_long":near_l,
            "long_retracement":round(long_retr*100,1) if long_retr else None,
            "in_golden_pocket_short":in_gp_short, "near_key_level_short":near_s,
            "short_retracement":round(short_retr*100,1) if short_retr else None,
            "swing_high":round(swing_high,4),"swing_low":round(swing_low,4),
        }
    except Exception as e:
        logger.warning(f"[피보나치] 오류: {e}"); return _empty


# ══════════════════════════════════════════════
# 15. 캔들 패턴
# ══════════════════════════════════════════════

def analyze_candle_pattern(df):
    _empty = {"long_score":50,"short_score":50,"patterns":[],"bearish_pin":False,"bullish_pin":False,
              "bearish_engulf":False,"bullish_engulf":False,"consecutive_bear":False,"consecutive_bull":False}
    if df is None or len(df) < 4: return _empty
    try:
        c=df["close"].astype(float).values; o=df["open"].astype(float).values
        h=df["high"].astype(float).values;  l=df["low"].astype(float).values
        body=np.abs(c-o); upper=h-np.maximum(c,o); lower=np.minimum(c,o)-l; rng=h-l
        min_rng=float(np.mean(rng[-20:]))*0.3; cur_rng=rng[-1]
        bearish_pin  =(cur_rng>min_rng and upper[-1]>body[-1]*2.0 and lower[-1]<upper[-1]*0.3 and c[-1]<o[-1])
        bullish_pin  =(cur_rng>min_rng and lower[-1]>body[-1]*2.0 and upper[-1]<lower[-1]*0.3 and c[-1]>o[-1])
        bearish_engulf=(c[-1]<o[-1] and c[-2]>o[-2] and o[-1]>=c[-2]*0.999 and c[-1]<=o[-2]*1.001 and body[-1]>body[-2])
        bullish_engulf=(c[-1]>o[-1] and c[-2]<o[-2] and o[-1]<=c[-2]*1.001 and c[-1]>=o[-2]*0.999 and body[-1]>body[-2])
        consecutive_bear=all(c[-i]<o[-i] for i in range(1,4))
        consecutive_bull=all(c[-i]>o[-i] for i in range(1,4))
        doji=body[-1]<cur_rng*0.10 if cur_rng>0 else False
        patterns=[]; short_score,long_score=50,50
        if bearish_pin:    short_score+=20; patterns.append("베어리시핀바")
        if bearish_engulf: short_score+=18; patterns.append("베어리시인걸핑")
        if consecutive_bear and not bearish_pin: short_score+=8; patterns.append("연속음봉3")
        if bullish_pin:    long_score+=20;  patterns.append("불리시핀바")
        if bullish_engulf: long_score+=18;  patterns.append("불리시인걸핑")
        if consecutive_bull and not bullish_pin: long_score+=8; patterns.append("연속양봉3")
        if doji: short_score*=0.85; long_score*=0.85; patterns.append("도지(방향약화)")
        if patterns: logger.info(f"[캔들패턴] {patterns}")
        return {"long_score":round(min(100,max(0,long_score)),2),"short_score":round(min(100,max(0,short_score)),2),
                "patterns":patterns,"bearish_pin":bearish_pin,"bullish_pin":bullish_pin,
                "bearish_engulf":bearish_engulf,"bullish_engulf":bullish_engulf,
                "consecutive_bear":consecutive_bear,"consecutive_bull":consecutive_bull}
    except Exception as e:
        logger.warning(f"[캔들패턴] 오류: {e}"); return _empty


# ══════════════════════════════════════════════
# 16. 시장 구조
# ══════════════════════════════════════════════

def analyze_market_structure(df):
    _empty = {"long_score":50,"short_score":50,"lower_high":False,"higher_low":False,
              "failed_breakout":False,"failed_breakdown":False}
    if df is None or len(df) < 30: return _empty
    try:
        highs=df["high"].astype(float).values; lows=df["low"].astype(float).values
        closes=df["close"].astype(float).values
        swing_highs=[]; swing_lows=[]
        for i in range(3,len(highs)-3):
            if highs[i]==max(highs[i-3:i+4]): swing_highs.append(highs[i])
            if lows[i] ==min(lows[i-3:i+4]):  swing_lows.append(lows[i])
        lower_high=higher_low=failed_breakout=failed_breakdown=False
        THRESH=config.MARKET_STRUCT_SWING_THRESHOLD
        if len(swing_highs)>=2: lower_high  = swing_highs[-1]<swing_highs[-2]*(1-THRESH)
        if len(swing_lows) >=2: higher_low  = swing_lows[-1] >swing_lows[-2] *(1+THRESH)
        lookback=20
        recent_high=max(highs[-lookback:-3]); max_last5=max(highs[-6:-1]); current=closes[-1]
        if max_last5>=recent_high*0.99 and current<recent_high*0.98: failed_breakout=True
        recent_low=min(lows[-lookback:-3]); min_last5=min(lows[-6:-1])
        if min_last5<=recent_low*1.01 and current>recent_low*1.02: failed_breakdown=True
        short_score=50+(10 if lower_high else 0)+(16 if failed_breakout  else 0)
        long_score =50+(10 if higher_low else 0)+(16 if failed_breakdown else 0)
        sigs=[s for s,v in [("LowerHigh",lower_high),("HigherLow",higher_low),
                             ("돌파실패",failed_breakout),("붕괴실패",failed_breakdown)] if v]
        if sigs: logger.info(f"[시장구조] {sigs}")
        return {"long_score":round(min(100,max(0,long_score)),2),"short_score":round(min(100,max(0,short_score)),2),
                "lower_high":lower_high,"higher_low":higher_low,
                "failed_breakout":failed_breakout,"failed_breakdown":failed_breakdown}
    except Exception as e:
        logger.warning(f"[시장구조] 오류: {e}"); return _empty


# ══════════════════════════════════════════════
# 17. 거래량-가격 다이버전스
# ══════════════════════════════════════════════

def analyze_vol_price_divergence(df):
    _empty = {"long_score":50,"short_score":50,"bearish_vol_div":False,"bullish_vol_div":False}
    if df is None or len(df) < 20: return _empty
    try:
        closes=df["close"].astype(float).values[-20:]; volumes=df["volume"].astype(float).values[-20:]
        half=10; prev_c,curr_c=closes[:half],closes[half:]; prev_v,curr_v=volumes[:half],volumes[half:]
        p_hi=int(np.argmax(prev_c)); c_hi=int(np.argmax(curr_c))
        p_lo=int(np.argmin(prev_c)); c_lo=int(np.argmin(curr_c))
        P_THRESH=1+config.VOL_DIV_PRICE_THRESHOLD; V_BULL=config.VOL_DIV_BULL_VOLUME_RATIO; V_BEAR=config.VOL_DIV_BEAR_VOLUME_RATIO
        bearish_vol_div=(curr_c[c_hi]>prev_c[p_hi]*P_THRESH and curr_v[c_hi]<prev_v[p_hi]*V_BEAR)
        bullish_vol_div=(curr_c[c_lo]<prev_c[p_lo]*(2-P_THRESH) and curr_v[c_lo]>prev_v[p_lo]*V_BULL)
        short_score=50+(18 if bearish_vol_div else 0); long_score=50+(18 if bullish_vol_div else 0)
        if bearish_vol_div: logger.info("[거래량다이버] ★ 신고가+거래량감소 — 숏 신호")
        if bullish_vol_div: logger.info("[거래량다이버] ★ 신저가+거래량증가 — 롱 신호")
        return {"long_score":round(min(100,max(0,long_score)),2),"short_score":round(min(100,max(0,short_score)),2),
                "bearish_vol_div":bearish_vol_div,"bullish_vol_div":bullish_vol_div}
    except Exception as e:
        logger.warning(f"[거래량다이버] 오류: {e}"); return _empty


# ══════════════════════════════════════════════
# [v2.0 신규] 18. 일봉 바이어스
# ══════════════════════════════════════════════

def analyze_daily_bias(df_1d):
    """
    [v2.0] 일봉 방향 바이어스

    조건 3개 중 2개 이상 충족:
      ① 전일 양봉/음봉  (close > open)
      ② 1d EMA9 vs EMA21
      ③ 당일가 vs 전일 종가

    반환:
      bias: "BULL" / "BEAR" / "NEUTRAL"
      threshold_adj_long / threshold_adj_short:
        BULL → 롱 -3pt, 숏 +7pt
        BEAR → 숏 -3pt, 롱 +7pt
        NEUTRAL → 0pt
    """
    _neutral = {
        "bias": "NEUTRAL",
        "threshold_adj_long":  0,
        "threshold_adj_short": 0,
        "bull_count": 0,
        "bear_count": 0,
        "ema9":  None,
        "ema21": None,
    }
    if df_1d is None or len(df_1d) < 10:
        return _neutral
    try:
        close = df_1d["close"].astype(float)
        open_ = df_1d["open"].astype(float)

        prev_close = float(close.iloc[-2])
        prev_open  = float(open_.iloc[-2])
        curr_close = float(close.iloc[-1])

        ema9  = float(_calc_ema(close, 9).iloc[-1])
        ema21 = float(_calc_ema(close, 21).iloc[-1])

        bull = [prev_close > prev_open, ema9 > ema21, curr_close > prev_close]
        bear = [prev_close < prev_open, ema9 < ema21, curr_close < prev_close]
        bull_count = sum(bull)
        bear_count = sum(bear)

        if bull_count >= 2:
            bias  = "BULL"
            adj_l = config.DAILY_BIAS_THRESHOLD_ADJ_ALIGN    # -3
            adj_s = config.DAILY_BIAS_THRESHOLD_ADJ_AGAINST  # +7
        elif bear_count >= 2:
            bias  = "BEAR"
            adj_l = config.DAILY_BIAS_THRESHOLD_ADJ_AGAINST  # +7
            adj_s = config.DAILY_BIAS_THRESHOLD_ADJ_ALIGN    # -3
        else:
            bias  = "NEUTRAL"
            adj_l = adj_s = 0

        logger.info(
            f"[일봉바이어스] {bias} (강세:{bull_count}/3 약세:{bear_count}/3) | "
            f"전일{'양봉' if prev_close>prev_open else '음봉'} | "
            f"EMA9({'>' if ema9>ema21 else '<'})EMA21 | "
            f"당일({'↑' if curr_close>prev_close else '↓'}) | "
            f"롱임계:{adj_l:+d}pt 숏임계:{adj_s:+d}pt"
        )
        return {
            "bias":                bias,
            "threshold_adj_long":  adj_l,
            "threshold_adj_short": adj_s,
            "bull_count":          bull_count,
            "bear_count":          bear_count,
            "ema9":                round(ema9,  4),
            "ema21":               round(ema21, 4),
        }
    except Exception as e:
        logger.warning(f"[일봉바이어스] 오류: {e}")
        return _neutral


# ══════════════════════════════════════════════
# 전체 분석 통합
# ══════════════════════════════════════════════

def run_full_analysis(symbol, collected_data):
    """
    [1h Bot v2.0] 전체 분석 통합
    entry=1h, mid=4h, macro=1d

    반환 키:
      "adx_1h"      ← entry ADX (scoring: analysis.get("adx_1h"))
      "adx_4h"      ← mid ADX
      "regime_4h"   ← [v2.0] 4h 메타 레짐
      "bos_choch_4h"← [v2.0] 4h BOS/CHoCH
      "daily_bias"  ← [v2.0] 일봉 바이어스
    """
    import datetime
    logger.info(f"{chr(8213)*50}")
    logger.info(f"🔬 분석 [1H봇]: {symbol}")

    ohlcv        = collected_data.get("ohlcv", {})
    ticker       = collected_data.get("ticker") or {}
    funding_data = collected_data.get("funding_rate")
    ls_raw       = collected_data.get("ls_ratio", {})
    taker_raw    = collected_data.get("taker_volume", {})
    liq_raw      = collected_data.get("liquidations", {})

    # ── 타임프레임 ───────────────────────────────────────────
    df_1h = ohlcv.get("1h")   # entry TF
    df_4h = ohlcv.get("4h")   # mid TF
    df_1d = ohlcv.get("1d")   # macro TF

    # ── 1h 기반 분석 (entry) ─────────────────────────────────
    rsi     = analyze_mtf_rsi(df_1h, df_4h, df_1d)
    bb      = analyze_bollinger_bands(df_1h)
    adx_1h  = calculate_adx(df_1h)
    adx_4h  = calculate_adx(df_4h)
    funding = analyze_funding_rate(funding_data)
    regime  = classify_market_regime(df_1h, adx_1h, bb)
    regime_name = regime.get("regime", "UNKNOWN")

    ls_ratio = analyze_long_short_ratio(ls_raw, regime_name)
    taker    = analyze_taker_volume(taker_raw)
    liq      = analyze_liquidations(liq_raw, df_1h)
    vol      = check_volume_confirmation(df_1h, df_4h=df_4h)
    atr      = get_atr_state(df_1h)

    candle_pattern = analyze_candle_pattern(df_1h)
    market_struct  = analyze_market_structure(df_1h)
    vol_price_div  = analyze_vol_price_divergence(df_1h)

    fvg       = detect_fvg(df_1h)
    bos_choch = detect_bos_choch(df_1h, lookback=60, n=3)   # 1h BOS
    fibonacci = check_fibonacci_levels(df_1h)

    ema_long  = calculate_ema_multiplier(ohlcv, "long",  regime_name)
    ema_short = calculate_ema_multiplier(ohlcv, "short", regime_name)

    gate_long  = evaluate_gates("long",  funding, ls_ratio)
    gate_short = evaluate_gates("short", funding, ls_ratio)

    # ── [v2.0] 4h 메타 레짐 + 4h BOS + 일봉 바이어스 ────────
    bb_4h        = analyze_bollinger_bands(df_4h)
    regime_4h    = classify_market_regime(df_4h, adx_4h, bb_4h)
    bos_choch_4h = detect_bos_choch(df_4h, lookback=30, n=2)   # 4h BOS (넓은 스윙)
    daily_bias   = analyze_daily_bias(df_1d)

    # ── 요약 로그 ────────────────────────────────────────────
    logger.info(
        f"  MTF-RSI: 1h:{rsi['value']:.1f} 4h:{rsi.get('value_1h') or '-'} "
        f"1d:{rsi.get('value_4h') or '-'} [{rsi['state']}] | "
        f"BB(1h):{bb['state']}(%B={bb['pct_b']:.2f}) | "
        f"ADX(1h):{adx_1h['adx']:.1f}[{adx_1h['strength']}] | "
        f"1h국면:{regime_name} | "
        f"Vol:{vol['ratio']:.2f}x({vol['score']:.0f}pt)[{vol.get('baseline_method','?')}] | "
        f"Taker:{taker.get('bias','?')} | 청산:{liq.get('signal','none')}"
    )
    logger.info(
        f"  [v2.0] 4h국면:{regime_4h.get('regime','?')} | "
        f"일봉:{daily_bias.get('bias','?')}(강{daily_bias.get('bull_count',0)}/약{daily_bias.get('bear_count',0)}) | "
        f"4h-BOS: 상승={bos_choch_4h.get('bos_bullish',False)} 하락={bos_choch_4h.get('bos_bearish',False)} | "
        f"4h-CHoCH: 상승전환={bos_choch_4h.get('choch_bullish',False)} 하락전환={bos_choch_4h.get('choch_bearish',False)}"
    )
    if bos_choch.get("bos_bullish") or bos_choch.get("bos_bearish"):
        logger.info(f"  1h-BOS: 상승={bos_choch['bos_bullish']} 하락={bos_choch['bos_bearish']}")
    if fvg.get("in_bullish_fvg") or fvg.get("in_bearish_fvg"):
        logger.info(f"  FVG: 강세={fvg['in_bullish_fvg']} 약세={fvg['in_bearish_fvg']}")

    return {
        "symbol":           symbol,
        "current_price":    ticker.get("last"),
        "rsi":              rsi,
        "bollinger":        bb,
        "ema_long":         ema_long,
        "ema_short":        ema_short,
        "adx_1h":           adx_1h,       # entry ADX — scoring: analysis.get("adx_1h")
        "adx_4h":           adx_4h,
        "funding_rate":     funding,
        "ls_ratio":         ls_ratio,
        "oi_change":        {"available": False},
        "taker_volume":     taker,
        "liquidations":     liq,
        "volume":           vol,
        "atr":              atr,
        "regime":           regime,
        "regime_4h":        regime_4h,    # [v2.0] 4h 메타 레짐
        "daily_bias":       daily_bias,   # [v2.0] 일봉 바이어스
        "bos_choch":        bos_choch,    # 1h BOS/CHoCH
        "bos_choch_4h":     bos_choch_4h, # [v2.0] 4h BOS/CHoCH
        "gate_long":        gate_long,
        "gate_short":       gate_short,
        "candle_pattern":   candle_pattern,
        "market_structure": market_struct,
        "vol_price_div":    vol_price_div,
        "fvg":              fvg,
        "fibonacci":        fibonacci,
        "analyzed_at":      datetime.datetime.utcnow().isoformat() + "Z",
    }
