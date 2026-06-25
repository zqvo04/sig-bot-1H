"""백분위(자기분포) 유틸 — 무상태.

절대 임계를 쓰지 않고 코인별 자기분포의 백분위로 상대평가한다. 상태 저장 없이
매 실행마다 캔들에서 피처 시계열을 재구성해 현재값을 그 분포에 순위매김한다.
(/tmp 유실 무관, 워크포워드 안전.)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import config
except ImportError:  # pragma: no cover
    try:
        from src import config  # type: ignore
    except ImportError:
        config = None


def pct_rank(series, value: float) -> float:
    """value가 series 분포에서 차지하는 백분위(0~1). 비어있으면 0.5(중립).

    [Pillar4-①] midrank: 순수 (arr<=v) CDF는 추정 백분위를 +1/(2n) 상향 편향시켜
    상단 극단(숏 트리거)은 쉽고 하단 극단(롱 트리거)은 어려운 L/S 비대칭을 만든다.
    midrank=((arr<v)+(arr<=v))/2 로 대칭화(엄밀 정정). 토글 OFF면 구동작(CDF)."""
    if value is None:
        return 0.5
    arr = np.asarray([x for x in series if x is not None and np.isfinite(x)], dtype=float)
    if arr.size < 5:
        return 0.5
    if getattr(config, "WRF_PCT_MIDRANK", True) if config is not None else True:
        return float(((arr < value).mean() + (arr <= value).mean()) / 2.0)
    return float((arr <= value).mean())


def to_axis(p: float) -> float:
    """백분위 p(0~1) → 방향중립 축값 [-1,1] (0.5=0, 1.0=+1, 0.0=-1)."""
    if p is None:
        return 0.0
    return float(max(-1.0, min(1.0, (p - 0.5) * 2.0)))


def rolling_vwap(df: pd.DataFrame, window: int) -> pd.Series:
    """롤링 VWAP (typical price × volume). 무상태·앵커리스."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (tp * df["volume"]).rolling(window, min_periods=max(2, window // 4)).sum()
    vv = df["volume"].rolling(window, min_periods=max(2, window // 4)).sum()
    return pv / vv.replace(0, np.nan)


def dist_series(close: pd.Series, ref: pd.Series, atr: pd.Series) -> pd.Series:
    """(close - ref) / atr 시계열. ATR 정규화 거리(자기분포 백분위 입력용)."""
    return (close - ref) / atr.replace(0, np.nan)


def series_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI 시계열(백분위 입력용). analysis_engine.calculate_rsi와 동일 정의."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))
