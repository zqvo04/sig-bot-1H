"""L1 — 직교 3축 + schema v3 원시 피처.

C 맥락 : 레짐 + 거시방향 + 일봉바이어스 → 허용 셋업 라우팅
L 위치 : (close−VWAP/EMA20)/ATR · BB%b 자기분포 백분위 + 컨플루언스(FVG/OB/피보/주간)
F 흐름 : RSI/MACD 소진·동조 + OKX 포지셔닝(펀딩백분위·OI사분면·청산스파이크·고래vs군중·테이커)

축은 절대 임계 없이 코인별 자기분포 백분위로만 매긴다. 라우팅을 위해 regime이
허용 셋업 집합을 결정한다. 출력 raw는 JSONL schema v3에 그대로 박제된다.
"""
from __future__ import annotations

import logging
from datetime import timezone

import numpy as np

from . import percentile as pct

logger = logging.getLogger(__name__)

try:
    import config
except ImportError:  # pragma: no cover
    from src import config  # type: ignore


def _f(v):
    try:
        if v is None:
            return None
        x = float(v)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _sign(pos, neg) -> int:
    return 1 if pos else (-1 if neg else 0)


def _ema_code(s: str) -> int:
    return {"bullish": 1, "bearish": -1}.get(s, 0)


# 레짐 → 허용 셋업 라우팅 (C 맥락의 1차 산출물)
REGIME_SETUPS = {
    "TRENDING":  ["TF", "RV"],
    "EXPLOSIVE": ["TF", "BO", "RV"],
    "SQUEEZE":   ["BO"],
    "RANGING":   ["MR", "RV"],
    "UNKNOWN":   ["MR"],
}


def allowed_setups(regime_1h: str, regime_4h: str) -> list:
    """레짐(1H 우선, 4H 보강) → 허용 셋업 집합."""
    s = list(REGIME_SETUPS.get(regime_1h, ["MR"]))
    # 4H가 추세면 TF 허용 보강, 4H 스퀴즈면 BO 허용 보강
    if regime_4h in ("TRENDING", "EXPLOSIVE") and "TF" not in s:
        s.append("TF")
    if regime_4h == "SQUEEZE" and "BO" not in s:
        s.append("BO")
    return s


def build_features(measures: dict, ohlcv: dict, btc_macro: str) -> dict:
    """측정치(run_full_analysis) + 캔들 + 거시방향 → L1 raw·백분위·ctx.

    반환: {"raw": {...schema v3 L1...}, "pct": {...백분위...},
           "ctx": {...}, "ts": iso, "p0": float}
    """
    a = measures or {}
    df_1h = (ohlcv or {}).get("1h")
    df_4h = (ohlcv or {}).get("4h")
    df_1d = (ohlcv or {}).get("1d")
    if df_1h is None or len(df_1h) == 0:
        raise ValueError("1h OHLCV 없음 — features 불가")

    last_ts = df_1h.index[-1]
    if last_ts.tzinfo is None:
        last_ts = last_ts.tz_localize(timezone.utc)
    else:
        last_ts = last_ts.tz_convert(timezone.utc)
    price = _f(a.get("current_price")) or _f(df_1h["close"].iloc[-1])

    rsi = a.get("rsi", {})
    bb = a.get("bollinger", {})
    adx = a.get("adx_1h", {})
    atr = a.get("atr", {})
    macd = a.get("macd_1h", {})
    vol = a.get("volume", {})
    ema_l = a.get("ema_long", {}).get("tf_signals", {})
    bos = a.get("bos_choch", {})
    bos4 = a.get("bos_choch_4h", {})
    fvg = a.get("fvg", {})
    ob = a.get("order_blocks", {})
    fib = a.get("fibonacci", {})
    wk = a.get("weekly_levels", {})
    fund = a.get("funding_rate", {})
    ftr = a.get("funding_trend", {})
    lsr = a.get("ls_ratio", {})
    tak = a.get("taker_volume", {})
    oim = a.get("oi_matrix", {})
    sm = a.get("smart_money", {})
    liq = a.get("liquidations", {})
    regime = a.get("regime", {})
    regime4 = a.get("regime_4h", {})
    dbias = a.get("daily_bias", {})

    # ── 백분위 시계열 구성 (무상태, 캔들에서 재구성) ──────────────────
    win = getattr(config, "WRF_PCT_WINDOW", 200)
    vwin = getattr(config, "WRF_VWAP_WINDOW", 48)
    close = df_1h["close"]
    atr_period = getattr(config, "ATR_PERIOD", 14)
    # ATR 시계열
    tr = (df_1h["high"] - df_1h["low"]).combine(
        (df_1h["high"] - close.shift()).abs(), max).combine(
        (df_1h["low"] - close.shift()).abs(), max)
    atr_ser = tr.ewm(alpha=1 / atr_period, min_periods=atr_period).mean()
    ema20_ser = close.ewm(span=20, adjust=False).mean()
    vwap_ser = pct.rolling_vwap(df_1h, vwin)
    rsi_ser = pct.series_rsi(df_1h, getattr(config, "RSI_PERIOD", 14))

    dist_vwap = pct.dist_series(close, vwap_ser, atr_ser)
    dist_ema20 = pct.dist_series(close, ema20_ser, atr_ser)

    cur_dist_vwap = _f(dist_vwap.iloc[-1])
    cur_dist_ema20 = _f(dist_ema20.iloc[-1])
    cur_rsi = _f(rsi.get("value_1h")) if rsi.get("value_1h") is not None else _f(rsi_ser.iloc[-1])
    cur_macd = _f(macd.get("histogram"))
    cur_bbpos = _f(bb.get("pct_b"))

    tail = slice(-win, None)
    p_loc_vwap = pct.pct_rank(dist_vwap.iloc[tail].tolist(), cur_dist_vwap)
    p_loc_ema20 = pct.pct_rank(dist_ema20.iloc[tail].tolist(), cur_dist_ema20)
    p_rsi = pct.pct_rank(rsi_ser.iloc[tail].tolist(), cur_rsi)
    macd_ser = (df_1h["close"].ewm(span=12, adjust=False).mean()
                - df_1h["close"].ewm(span=26, adjust=False).mean())
    macd_hist_ser = macd_ser - macd_ser.ewm(span=9, adjust=False).mean()
    p_macd = pct.pct_rank(macd_hist_ser.iloc[tail].tolist(), cur_macd)
    p_bbpos = cur_bbpos if cur_bbpos is not None else 0.5  # %b 자체가 0~1 백분위적
    # 펀딩 백분위(가용 이력에서)
    fund_hist = a.get("_funding_hist_rates") or []
    p_funding = pct.pct_rank(fund_hist, _f(fund.get("rate"))) if fund_hist else 0.5

    # 컨플루언스 카운트(FVG/OB/피보/주간 동시중첩)
    confluence_long = sum([
        bool(fvg.get("in_bullish_fvg")), bool(ob.get("in_bullish_ob")),
        bool(fib.get("in_golden_pocket_long") or fib.get("near_key_level_long")),
        bool(wk.get("near_level") and not wk.get("is_resistance")),
    ])
    confluence_short = sum([
        bool(fvg.get("in_bearish_fvg")), bool(ob.get("in_bearish_ob")),
        bool(fib.get("in_golden_pocket_short") or fib.get("near_key_level_short")),
        bool(wk.get("near_level") and wk.get("is_resistance")),
    ])

    liq_spike = bool(liq.get("is_large", False))

    raw = {
        # 모멘텀/추세
        "rsi": cur_rsi,
        "rsi_4h": _f(rsi.get("value_4h")),
        "rsi_1d": _f(rsi.get("value_1d")),
        "bb_pctb": cur_bbpos,
        "dist_vwap_atr": cur_dist_vwap,
        "dist_ema20_atr": cur_dist_ema20,
        "atr_pct": _f(atr.get("pct")),
        "adx": _f(adx.get("adx")),
        "adx_slope": _f(adx.get("adx_slope")),
        "macd": cur_macd,
        "macd_bull": bool(macd.get("bullish", False)),
        "ema": _ema_code(ema_l.get("1h", "neutral")),
        "ema_4h": _ema_code(ema_l.get("4h", "neutral")),
        "ema_1d": _ema_code(ema_l.get("1d", "neutral")),
        # 구조(SMC)
        "fvg": _sign(fvg.get("in_bullish_fvg"), fvg.get("in_bearish_fvg")),
        "ob": _sign(ob.get("in_bullish_ob"), ob.get("in_bearish_ob")),
        "fib_gp": _sign(fib.get("in_golden_pocket_long"), fib.get("in_golden_pocket_short")),
        "weekly": _sign(wk.get("near_level") and not wk.get("is_resistance"),
                        wk.get("near_level") and wk.get("is_resistance")),
        "bos": _sign(bos.get("bos_bullish"), bos.get("bos_bearish")),
        "choch": _sign(bos.get("choch_bullish"), bos.get("choch_bearish")),
        "bos_4h": _sign(bos4.get("bos_bullish"), bos4.get("bos_bearish")),
        "choch_4h": _sign(bos4.get("choch_bullish"), bos4.get("choch_bearish")),
        "confluence_long": int(confluence_long),
        "confluence_short": int(confluence_short),
        # 크립토 포지셔닝
        "funding": _f(fund.get("rate")),
        "funding_slope": _f(ftr.get("slope")) if ftr.get("slope") is not None else None,
        "oi_chg": _f(oim.get("oi_change_pct")),
        "oi_slope": _f(oim.get("oi_slope")),
        "oi_quadrant": oim.get("quadrant", "neutral"),
        "ls_long": _f(lsr.get("long_pct")),
        "taker_buy": _f(tak.get("buy_ratio")),
        "smart_div": _f(sm.get("divergence")),
        "liq_signal": liq.get("signal", "none"),
        "liq_spike": liq_spike,
        "vol_ratio": _f(vol.get("ratio")),
        # 시간
        "hour_utc": int(last_ts.hour),
        "dow": int(last_ts.weekday()),
    }

    pcts = {
        "loc_vwap": p_loc_vwap, "loc_ema20": p_loc_ema20,
        "bb_pctb": p_bbpos, "rsi": p_rsi, "macd": p_macd, "funding": p_funding,
    }

    r1 = regime.get("regime", "UNKNOWN")
    r4 = regime4.get("regime", "UNKNOWN")
    bd = dbias.get("bias", "NEUTRAL")
    ctx = {
        "regime_1h": r1, "regime_4h": r4, "bias_1d": bd, "btc_macro": btc_macro,
        "fp_key": f"{r1}|{r4}|{bd}|{btc_macro}",
        "allowed_setups": allowed_setups(r1, r4),
    }

    return {
        "raw": raw, "pct": pcts, "ctx": ctx,
        "confluence_long": int(confluence_long),
        "confluence_short": int(confluence_short),
        "ts": last_ts.isoformat(), "p0": price,
        "df_1h": df_1h, "df_4h": df_4h, "df_1d": df_1d,
        "measures": a,
    }
