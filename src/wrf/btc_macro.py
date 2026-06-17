"""BTC 거시방향(btc_macro) 태깅 — UPLEG / DOWNLEG / CHOP.

매 스냅샷에 BTC 7D/30D 추세·EMA구조를 박아 보정을 거시방향별로 분할한다.
단일 불런(2026-06 데이터)의 "무조건 롱" 비정상성 함정을 차단하기 위한 핵심 태그.
입력은 BTC 1D 캔들(df_1d)만 — 무상태.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import config
except ImportError:  # pragma: no cover
    from src import config  # type: ignore


def _ema(series, span: int):
    return series.ewm(span=span, adjust=False).mean()


def classify_btc_macro(df_btc_1d) -> str:
    """BTC 1D 캔들 → 'UPLEG' | 'DOWNLEG' | 'CHOP'.

    규칙(층화용·보수적): 7D 변화율 부호·크기 + EMA(20/50) 구조 정합.
      - 7D ≥ +UP_PCT 그리고 EMA20≥EMA50  → UPLEG
      - 7D ≤ -UP_PCT 그리고 EMA20≤EMA50  → DOWNLEG
      - |7D| < CHOP_PCT 또는 EMA 구조 불일치 → CHOP
    데이터 부족·예외 시 'CHOP'(가장 보수적).
    """
    try:
        if df_btc_1d is None or len(df_btc_1d) < 8:
            return "CHOP"
        close = df_btc_1d["close"]
        last = float(close.iloc[-1])
        ago7 = float(close.iloc[-8])
        chg7 = (last / ago7 - 1.0) if ago7 else 0.0
        chg30 = 0.0
        if len(close) >= 31:
            ago30 = float(close.iloc[-31])
            chg30 = (last / ago30 - 1.0) if ago30 else 0.0
        ema20 = float(_ema(close, 20).iloc[-1])
        ema50 = float(_ema(close, 50).iloc[-1]) if len(close) >= 50 else ema20
        up_pct = getattr(config, "WRF_MACRO_UP_PCT", 0.03)
        chop_pct = getattr(config, "WRF_MACRO_CHOP_PCT", 0.015)

        struct_up = ema20 >= ema50
        struct_dn = ema20 <= ema50

        if abs(chg7) < chop_pct:
            return "CHOP"
        if chg7 >= up_pct and struct_up and chg30 >= -chop_pct:
            return "UPLEG"
        if chg7 <= -up_pct and struct_dn and chg30 <= chop_pct:
            return "DOWNLEG"
        return "CHOP"
    except Exception as e:  # pragma: no cover
        logger.warning(f"[btc_macro] 분류 실패 → CHOP: {e}")
        return "CHOP"
