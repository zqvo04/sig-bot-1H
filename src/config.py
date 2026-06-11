"""
config.py — 전역 설정 (1h Bot v3.4)
────────────────────────────────────────────────────────────────────
[v3.4 변경사항]
  [개선 1] 청산 방향 로직 버그픽스 → analysis_engine.py에서 처리
  [개선 2] SHORT 역풍필터 확장 파라미터 추가
           - LIQ_REVERSE_PRESSURE, FAILED_BREAKDOWN_PRESSURE, WEEKLY_LEVEL_PRESSURE
  [개선 3] SQUEEZE 메타레짐 완화 제거 (SQUEEZE×* → 0 또는 축소)
  [개선 4] 모순 시장구조 보너스 상쇄 → scoring_system.py에서 처리
  [개선 5] SQUEEZE BOS 보너스 삭감 파라미터 추가
           - SQUEEZE_BOS_BONUS_MULT = 0.30
────────────────────────────────────────────────────────────────────
"""
import os

# ══════════════════════════════════════════════════════════════════════
# API / 환경
# ══════════════════════════════════════════════════════════════════════
OKX_API_KEY        = os.getenv("OKX_API_KEY",    "")
OKX_API_SECRET     = os.getenv("OKX_API_SECRET", "")
OKX_PASSPHRASE     = os.getenv("OKX_PASSPHRASE", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")

SYMBOLS: list     = ["BTC/USDT", "ETH/USDT", "HYPE/USDT"]
TIMEFRAMES        = {"entry": "1h", "mid": "4h", "macro": "1d"}
CANDLE_LIMITS     = {"1h": 250, "4h": 210, "1d": 100}

# ══════════════════════════════════════════════════════════════════════
# 지표 파라미터
# ══════════════════════════════════════════════════════════════════════
RSI_PERIOD       = 14
RSI_OVERBOUGHT   = 70
RSI_OVERSOLD     = 30
BOLLINGER_PERIOD = 20
BOLLINGER_STD    = 2.0
ATR_PERIOD       = 14
EMA_FAST         = 9
EMA_SLOW         = 21

ADX_PERIOD       = 14
ADX_NO_TREND     = 20