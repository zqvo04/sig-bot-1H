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
import pandas as pd

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


def _lin_slope(rates) -> float:
    """펀딩 이력(최근값이 앞) → 시간순 최소제곱 기울기(스텝당). 3점 미만이면 None."""
    seq = [r for r in (rates or []) if r is not None and np.isfinite(r)]
    if len(seq) < 3:
        return None
    chrono = list(reversed(seq))  # 오래된→최근 순으로
    x = np.arange(len(chrono), dtype=float)
    try:
        slope = float(np.polyfit(x, np.asarray(chrono, dtype=float), 1)[0])
        return slope if np.isfinite(slope) else None
    except Exception:
        return None


def _fwd_favorable_pctile(df_1h, atr_ser, direction: str, n: int, window: int,
                          q: float, min_n: int) -> float | None:
    """[개선안4] 심볼 자기 N봉 순방향 유리이동(ATR배수) 분포의 Q백분위 — TP 상한 근거.

    각 과거봉 i의 '그 이후 n봉 유리극값'은 i 시점 기준 이미 실현된 값이라 미래참조가
    아니다(현재 미완성 마지막 n봉만 자동 제외). 절대임계 아님 — 심볼·변동성에 자동
    적응하는 자기분포 백분위(5-C). 표본 부족 시 None(호출부가 상한 미적용으로 폴백)."""
    try:
        lookback = min(len(df_1h), window + n + 1)
        if lookback <= n + min_n:
            return None
        h = df_1h["high"].to_numpy(dtype=float)[-lookback:]
        l = df_1h["low"].to_numpy(dtype=float)[-lookback:]
        c = df_1h["close"].to_numpy(dtype=float)[-lookback:]
        a = atr_ser.to_numpy(dtype=float)[-lookback:]
        if direction == "long":
            roll = pd.Series(h[::-1]).rolling(n, min_periods=n).max().to_numpy()[::-1]
            fwd = np.concatenate([roll[1:], [np.nan]])
            fav = (fwd - c) / a
        else:
            roll = pd.Series(l[::-1]).rolling(n, min_periods=n).min().to_numpy()[::-1]
            fwd = np.concatenate([roll[1:], [np.nan]])
            fav = (c - fwd) / a
        valid = fav[np.isfinite(fav) & (a > 0)]
        if len(valid) < min_n:
            return None
        return float(np.quantile(valid, q))
    except Exception:
        return None


def _ema_code(s: str) -> int:
    return {"bullish": 1, "bearish": -1}.get(s, 0)


def _bars_since_sign_flip(ser) -> int | None:
    """[V5-0 계측] 시계열 끝값의 부호가 마지막으로 바뀐 뒤 경과 봉 수(0=이번 봉 플립).

    매 실행 캔들에서 재구성되는 시계열(dist_vwap/dist_ema20)에서 즉시 계산 — 무상태(5-E).
    끝값이 0/NaN이거나 플립 전에 NaN 경계를 만나면 None(신선도 불명 = 보수적 비신선)."""
    try:
        a = ser.to_numpy(dtype=float)
        cur = a[-1]
        if not np.isfinite(cur) or cur == 0.0:
            return None
        for i in range(2, len(a) + 1):
            x = a[-i]
            if not np.isfinite(x):
                return None
            if x * cur <= 0.0:
                return i - 2
        return None
    except Exception:
        return None


# 레짐 → 허용 셋업 라우팅 (C 맥락의 1차 산출물)
REGIME_SETUPS = {
    "TRENDING":  ["TF", "RV"],
    "EXPLOSIVE": ["TF", "BO", "RV"],
    "SQUEEZE":   ["BO", "RV"],   # 압축 극단은 돌파 또는 반전 — RV는 ≥3확인·소진축으로 강게이트
    "RANGING":   ["MR", "RV"],
    "UNKNOWN":   ["MR"],
}


def allowed_setups(regime_1h: str, regime_4h: str) -> list:
    """레짐(1H 우선, 4H 보강) → 허용 셋업 집합."""
    s = list(REGIME_SETUPS.get(regime_1h, ["MR"]))
    # [연결결함#1] 박스권 돌파는 RANGING에서 출발 → RANGING에도 BO 허용(강게이트로 통제)
    if getattr(config, "WRF_BO_IN_RANGING", True) and regime_1h == "RANGING" and "BO" not in s:
        s.append("BO")
    # 4H가 추세면 TF 허용 보강, 4H 스퀴즈면 BO 허용 보강
    if regime_4h in ("TRENDING", "EXPLOSIVE") and "TF" not in s:
        s.append("TF")
    if regime_4h == "SQUEEZE" and "BO" not in s:
        s.append("BO")
    # [⑤] TC(추세지속·섀도)는 TF와 동일 추세레짐에서 활성 — 섀도라 발사엔 무영향(오프라인 표본만).
    if getattr(config, "WRF_TC_ENABLED", True) and "TF" in s and "TC" not in s:
        s.append("TC")
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
    c1 = a.get("candle_pattern", {})   # [BR정합 계측] MR/RV가 쓰는 반전캔들 판정과 동일 소스
    fund = a.get("funding_rate", {})
    lsr = a.get("ls_ratio", {})
    tak = a.get("taker_volume", {})
    oim = a.get("oi_matrix", {})
    sm = a.get("smart_money", {})
    liq = a.get("liquidations", {})
    ms = a.get("market_structure", {})
    regime = a.get("regime", {})
    regime4 = a.get("regime_4h", {})
    dbias = a.get("daily_bias", {})
    retr = a.get("retracement", {})    # [A1] 4H 피보 되돌림 zone
    mat = a.get("maturity", {})        # [A1] 추세 성숙도(HH/HL 카운트)
    ema_struct = a.get("ema_structure", {})  # [#4/#5] 일봉 EMA20/50 구조(전략 추세정의)

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
    adx_ser = pct.series_adx(df_1h, getattr(config, "ADX_PERIOD", 14))

    dist_vwap = pct.dist_series(close, vwap_ser, atr_ser)
    dist_ema20 = pct.dist_series(close, ema20_ser, atr_ser)

    cur_dist_vwap = _f(dist_vwap.iloc[-1])
    cur_dist_ema20 = _f(dist_ema20.iloc[-1])
    cur_rsi = _f(rsi.get("value_1h")) if rsi.get("value_1h") is not None else _f(rsi_ser.iloc[-1])
    cur_macd = _f(macd.get("histogram"))
    cur_bbpos = _f(bb.get("pct_b"))
    cur_adx = _f(adx.get("adx")) if adx.get("adx") is not None else _f(adx_ser.iloc[-1])

    tail = slice(-win, None)
    p_loc_vwap = pct.pct_rank(dist_vwap.iloc[tail].tolist(), cur_dist_vwap)
    p_loc_ema20 = pct.pct_rank(dist_ema20.iloc[tail].tolist(), cur_dist_ema20)
    p_rsi = pct.pct_rank(rsi_ser.iloc[tail].tolist(), cur_rsi)
    macd_ser = (df_1h["close"].ewm(span=12, adjust=False).mean()
                - df_1h["close"].ewm(span=26, adjust=False).mean())
    macd_hist_ser = macd_ser - macd_ser.ewm(span=9, adjust=False).mean()
    p_macd = pct.pct_rank(macd_hist_ser.iloc[tail].tolist(), cur_macd)
    # [개선-B] 추세강도 자기분포 백분위 — 반전셋업의 '거스를 추세가 얼마나 센가'.
    # 계측만(현재 어떤 디텍터도 미소비). 5-C: 절대 임계 대신 코인 자기분포 백분위.
    p_adx = pct.pct_rank(adx_ser.iloc[tail].tolist(), cur_adx)
    p_bbpos = cur_bbpos if cur_bbpos is not None else 0.5  # %b 자체가 0~1 백분위적
    # 펀딩 백분위(가용 이력에서)
    fund_hist = a.get("_funding_hist_rates") or []
    p_funding = pct.pct_rank(fund_hist, _f(fund.get("rate"))) if fund_hist else 0.5
    funding_slope = _lin_slope(fund_hist)  # 펀딩 이력 추세 기울기(최근으로 갈수록 +)

    # [개선안1] 방향 드리프트 자기분포 백분위 — btc_macro(BTC 7D 절대% 임계)가 CHOP
    # 태그일 때 방향 베토가 무작동이던 공백을 메운다(심볼 자기 드리프트, 5-C).
    drift_win = getattr(config, "WRF_DRIFT_WINDOW", 42)
    if len(close) > drift_win:
        drift_ser = (close - close.shift(drift_win)) / atr_ser
        cur_drift = _f(drift_ser.iloc[-1])
        p_drift = pct.pct_rank(drift_ser.iloc[tail].tolist(), cur_drift)
    else:
        cur_drift = None
        p_drift = 0.5

    # [개선안4] TF/RV/BR TP 상한 근거 — 심볼 자기 N봉 순방향 유리이동 분포 Q백분위
    # (ATR배수). levels.py가 tp_dist = min(구조타깃, mfe_pctile×ATR)로 소비한다.
    mfe_n = getattr(config, "WRF_TP_MFE_HORIZON", 48)
    mfe_q = getattr(config, "WRF_TP_MFE_Q", 0.65)
    mfe_minn = getattr(config, "WRF_TP_MFE_MINN", 20)
    mfe_pctile_long = _fwd_favorable_pctile(df_1h, atr_ser, "long", mfe_n, win, mfe_q, mfe_minn)
    mfe_pctile_short = _fwd_favorable_pctile(df_1h, atr_ser, "short", mfe_n, win, mfe_q, mfe_minn)

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

    # [A5/G7] 반전봉 거래량비 — 반전캔들(마지막 '완성'봉 -2) / 그 직전 N봉 평균.
    # iloc[-1]은 미완성 형성봉(잡 실행 시점 몇 분치만 누적)이라 분자로 쓰면 값이 상시
    # <1.0로 짓눌려 _rev_vol_ok 게이트가 99.6% 상시-거짓 → TF/MR/RV 반전 후보 계통 소멸(FN).
    # vol_ratio(BO용)·candle(offset=1)과 동일하게 완성봉 -2 기준으로 정렬(사과-대-사과 비교).
    rev_vol_ratio = None
    try:
        vlb = getattr(config, "WRF_REV_VOL_LOOKBACK", 5)
        vol_ser = df_1h["volume"].astype(float)
        if len(vol_ser) >= vlb + 2:
            base_v = float(vol_ser.iloc[-(vlb + 2):-2].mean())
            if base_v > 0:
                rev_vol_ratio = round(float(vol_ser.iloc[-2]) / base_v, 3)
    except Exception:
        rev_vol_ratio = None

    raw = {
        # 모멘텀/추세
        "rsi": cur_rsi,
        "rsi_4h": _f(rsi.get("value_4h")),
        "rsi_1d": _f(rsi.get("value_1d")),
        "bb_pctb": cur_bbpos,
        "dist_vwap_atr": cur_dist_vwap,
        "dist_ema20_atr": cur_dist_ema20,
        # [V5-0 계측] 신선도 — VWAP/EMA20 부호플립 후 경과 봉 수(리클레임 부스트 입력 +
        # 오프라인 검증용 박제. 부스트 OFF여도 기록돼 표본이 쌓인다)
        "bars_since_vwap_flip": _bars_since_sign_flip(dist_vwap),
        "bars_since_ema20_flip": _bars_since_sign_flip(dist_ema20),
        # [BR정합 계측] 반전캔들 부호(+1=강세 pin/engulf, -1=약세) — MR/RV가 precond에
        # 쓰는 것과 동일 판정을 raw에 영구 박제(schema는 raw 전체를 그대로 저장하므로
        # 스키마 변경 불요). BR precond는 이 필드를 아직 요구하지 않음(계측만, 5-I).
        "rev_candle": _sign(bool(c1.get("bullish_pin") or c1.get("bullish_engulf")),
                            bool(c1.get("bearish_pin") or c1.get("bearish_engulf"))),
        # [④트리거 시간창] 반전캔들이 몇 봉 전에 났나(0=마지막 완성봉, None=최근 창에 없음).
        # 디텍터가 WRF_TRIG_WINDOW로 '최근 N봉 내 반전캔들'을 트리거로 인정하는 데 소비.
        "bars_since_rev_bull": (a.get("rev_candle_window") or {}).get("bull_bars_since"),
        "bars_since_rev_bear": (a.get("rev_candle_window") or {}).get("bear_bars_since"),
        "atr_pct": _f(atr.get("pct")),
        "adx": _f(adx.get("adx")),
        "adx_slope": _f(adx.get("adx_slope")),
        "macd": cur_macd,
        "macd_bull": bool(macd.get("bullish", False)),
        "ema": _ema_code(ema_l.get("1h", "neutral")),
        "ema_4h": _ema_code(ema_l.get("4h", "neutral")),
        "ema_1d": _ema_code(ema_l.get("1d", "neutral")),
        # [#4/#5] 일봉 EMA20/50 구조: +1=강세(price>EMA20>EMA50)/-1=약세/0=중립
        "ema_1d_struct": (1 if ema_struct.get("structure") == "bull"
                          else -1 if ema_struct.get("structure") == "bear" else 0),
        # 구조(SMC)
        "fvg": _sign(fvg.get("in_bullish_fvg"), fvg.get("in_bearish_fvg")),
        "ob": _sign(ob.get("in_bullish_ob"), ob.get("in_bearish_ob")),
        "fib_gp": _sign(fib.get("in_golden_pocket_long"), fib.get("in_golden_pocket_short")),
        "weekly": _sign(wk.get("near_level") and not wk.get("is_resistance"),
                        wk.get("near_level") and wk.get("is_resistance")),
        "bos": _sign(bos.get("bos_bullish"), bos.get("bos_bearish")),
        "choch": _sign(bos.get("choch_bullish"), bos.get("choch_bearish")),
        # 실패한 돌파/유동성 스윕: +1=하향이탈실패(강세) / -1=상향이탈실패(약세)
        "failed_break": _sign(ms.get("failed_breakdown"), ms.get("failed_breakout")),
        "bos_4h": _sign(bos4.get("bos_bullish"), bos4.get("bos_bearish")),
        "choch_4h": _sign(bos4.get("choch_bullish"), bos4.get("choch_bearish")),
        "confluence_long": int(confluence_long),
        "confluence_short": int(confluence_short),
        # 크립토 포지셔닝
        "funding": _f(fund.get("rate")),
        "funding_slope": funding_slope,
        "oi_chg": _f(oim.get("oi_change_pct")),
        "oi_slope": _f(oim.get("oi_slope")),
        "oi_quadrant": oim.get("quadrant", "neutral"),
        "ls_long": _f(lsr.get("long_pct")),
        "taker_buy": _f(tak.get("buy_ratio")),
        "smart_div": _f(sm.get("divergence")),
        "liq_signal": liq.get("signal", "none"),
        "liq_spike": liq_spike,
        "vol_ratio": _f(vol.get("ratio")),         # 돌파봉(-2) 기준(BO용)
        "rev_vol_ratio": rev_vol_ratio,            # 반전봉(-1)/직전5봉 (TF/MR/RV용)
        # [A1] 되돌림·성숙도 (TF 눌림 판정 + 학습/로깅 배선)
        "retrace_long_zone": retr.get("long_zone", "none"),
        "retrace_short_zone": retr.get("short_zone", "none"),
        "maturity": mat.get("maturity", "none"),
        "maturity_net": int(mat.get("bull_count", 0) or 0) - int(mat.get("bear_count", 0) or 0),
        # 시간
        "hour_utc": int(last_ts.hour),
        "dow": int(last_ts.weekday()),
        # [개선안1] 방향 드리프트(ATR정규화 순변화, 계측값 — 베토는 pct["drift"] 소비)
        "drift_norm": cur_drift,
        # [개선안4] TP 상한 근거(ATR배수, levels.py 소비)
        "mfe_pctile_long": mfe_pctile_long,
        "mfe_pctile_short": mfe_pctile_short,
    }

    pcts = {
        "loc_vwap": p_loc_vwap, "loc_ema20": p_loc_ema20,
        "bb_pctb": p_bbpos, "rsi": p_rsi, "macd": p_macd, "funding": p_funding,
        "adx": p_adx, "drift": p_drift,
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
