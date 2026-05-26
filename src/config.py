"""
config.py — 전역 설정 (1h Bot v2.0)
────────────────────────────────────────────────────────────────────
[v2.0 추가: 5개 개선 기능]

① 4h 메타 레짐 레이어
   META_REGIME_THRESHOLD_ADJ: (4h레짐, 1h레짐) → 임계값 보정값
   4h TRENDING + 1h RANGING = 눌림목 → 보정 없음
   4h RANGING  + 1h TRENDING = 큰그림불명 → +5pt
   4h EXPLOSIVE + 1h TRENDING = 추격위험 → +8pt
   4h SQUEEZE  + 1h SQUEEZE = 이중압축 → -5pt (대폭발 직전)

② 일봉 바이어스
   DAILY_BIAS_THRESHOLD_ADJ_ALIGN   = -3  (방향 일치)
   DAILY_BIAS_THRESHOLD_ADJ_AGAINST = +7  (역추세)

③ 4h BOS/CHoCH
   BONUS_BOS_CONFIRM_4H    = 12  (1h: 8pt)
   CHOCH_4H_AGAINST_PENALTY = 0.80  (1h: 0.88)
   BOS_4H_CONFLICT_PENALTY  = 0.78  (1h: 0.82)

④ 거래 세션 필터 (UTC 기준)
   SESSION_ADJ_OVERLAP = -3  (런던+NY 오버랩 13-16h)
   SESSION_ADJ_NY      = -2  (NY 16-22h)
   SESSION_ADJ_LONDON  =  0  (런던 07-13h)
   SESSION_ADJ_ASIA    = +4  (아시아/데드존 22-07h)
   SESSION_ADJ_WEEKEND = +6  (토일)

⑦ 펀딩비 8h 사이클
   FUNDING_CYCLE_ADJ   = +3  (OKX 정산 ±1h: 23,0,7,8,15,16)

[1h Bot v1.0 기반]
"""
import os

# ══════════════════════════════════════════════════════════════
# API / 환경
# ══════════════════════════════════════════════════════════════
OKX_API_KEY    = os.getenv("OKX_API_KEY",    "")
OKX_API_SECRET = os.getenv("OKX_API_SECRET", "")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")

SYMBOLS: list = ["BTC/USDT", "ETH/USDT", "HYPE/USDT"]

TIMEFRAMES    = {"entry": "1h", "mid": "4h", "macro": "1d"}
CANDLE_LIMITS = {"1h": 250, "4h": 210, "1d": 100}

# ══════════════════════════════════════════════════════════════
# 지표 파라미터
# ══════════════════════════════════════════════════════════════
RSI_PERIOD     = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD   = 30
BOLLINGER_PERIOD = 20
BOLLINGER_STD    = 2.0
ATR_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21

ADX_PERIOD      = 14
ADX_NO_TREND    = 20
ADX_WEAK_TREND  = 25
ADX_STRONG      = 50

VOLUME_4H_BASELINE_CANDLES  = 30
VOLUME_1H_BASELINE_CANDLES  = 120
VOLUME_CONFIRM_LOOKBACK     = 48
VOLUME_SPIKE_MULTIPLIER     = 1.5
VOLUME_STRONG_MULTIPLIER    = 2.5
VOLUME_EXPLOSION_MULTIPLIER = 2.0

# ══════════════════════════════════════════════════════════════
# EMA 배율
# ══════════════════════════════════════════════════════════════
EMA_MULTIPLIER = {3: 0.52, 2: 0.72, 1: 0.88, 0: 1.00}

EMA_MULTIPLIER_RANGING   = {3: 0.82, 2: 0.90, 1: 0.96, 0: 1.00}
EMA_MULTIPLIER_TRENDING  = {3: 0.52, 2: 0.72, 1: 0.88, 0: 1.00}
EMA_MULTIPLIER_EXPLOSIVE = {3: 0.75, 2: 0.84, 1: 0.93, 0: 1.00}
EMA_MULTIPLIER_SQUEEZE   = {3: 0.80, 2: 0.87, 1: 0.95, 0: 1.00}

REGIME_EMA_MULTIPLIERS = {
    "RANGING":   EMA_MULTIPLIER_RANGING,
    "TRENDING":  EMA_MULTIPLIER_TRENDING,
    "EXPLOSIVE": EMA_MULTIPLIER_EXPLOSIVE,
    "SQUEEZE":   EMA_MULTIPLIER_SQUEEZE,
    "UNKNOWN":   EMA_MULTIPLIER,
}

# ══════════════════════════════════════════════════════════════
# 시장 심리 임계값
# ══════════════════════════════════════════════════════════════
FUNDING_LONG_STRONG  = -0.0005
FUNDING_LONG_MILD    = -0.0001
FUNDING_SHORT_MILD   =  0.0005
FUNDING_SHORT_STRONG =  0.001

LS_LONG_EXTREME  = 0.72
LS_LONG_HIGH     = 0.65
LS_SHORT_EXTREME = 0.62
LS_SHORT_HIGH    = 0.55

OI_CHANGE_STRONG = 0.05
OI_CHANGE_MILD   = 0.02

TAKER_LOOKBACK    = 100
TAKER_STRONG_BUY  = 0.65
TAKER_STRONG_SELL = 0.65

LIQ_LOOKBACK_MINUTES  = 60
LIQ_LARGE_THRESHOLD   = 500_000
LIQ_SIGNAL_THRESHOLD  = 1_000_000

REGIME_SQUEEZE_RATIO = 0.70
REGIME_TREND_ADX     = 25
REGIME_STRONG_ADX    = 40

# ══════════════════════════════════════════════════════════════
# 국면별 가중치
# ══════════════════════════════════════════════════════════════
SCORE_WEIGHTS = {
    "rsi": 0.25, "bollinger": 0.20, "funding_rate": 0.19,
    "long_short_ratio": 0.14, "taker_volume": 0.18, "volume": 0.04,
}
SCORE_WEIGHTS_RANGING = {
    "rsi": 0.32, "bollinger": 0.26, "funding_rate": 0.13,
    "long_short_ratio": 0.12, "taker_volume": 0.10, "volume": 0.07,
}
SCORE_WEIGHTS_TRENDING = {
    "rsi": 0.11, "bollinger": 0.09, "funding_rate": 0.15,
    "long_short_ratio": 0.22, "taker_volume": 0.34, "volume": 0.09,
}
SCORE_WEIGHTS_EXPLOSIVE = {
    "rsi": 0.07, "bollinger": 0.06, "funding_rate": 0.15,
    "long_short_ratio": 0.24, "taker_volume": 0.38, "volume": 0.10,
}
SCORE_WEIGHTS_SQUEEZE = {
    "rsi": 0.15, "bollinger": 0.35, "funding_rate": 0.13,
    "long_short_ratio": 0.13, "taker_volume": 0.19, "volume": 0.05,
}
REGIME_SCORE_WEIGHTS = {
    "RANGING":   SCORE_WEIGHTS_RANGING,
    "TRENDING":  SCORE_WEIGHTS_TRENDING,
    "EXPLOSIVE": SCORE_WEIGHTS_EXPLOSIVE,
    "SQUEEZE":   SCORE_WEIGHTS_SQUEEZE,
    "UNKNOWN":   SCORE_WEIGHTS,
}

# ══════════════════════════════════════════════════════════════
# 보너스 체계
# ══════════════════════════════════════════════════════════════
BONUS_PULLBACK_ENTRY       = 12
BONUS_PULLBACK_ENTRY_WEAK  = 8
BONUS_PULLBACK_ENTRY_MICRO = 4
BONUS_TREND_STRONG         = 12
BONUS_BB_RSI_ALIGN         = 8
BONUS_LIQUIDATION          = 10
BONUS_VOL_PRICE_DIV        = 10
BONUS_FAILED_BREAKOUT      = 12
BONUS_EXTREME_OVERSOLD_MTF = 10
BONUS_FVG_ENTRY            = 8
BONUS_FVG_ENTRY_CONFLICTED = 4
BONUS_BOS_CONFIRM          = 8
BONUS_FIB_GOLDEN_POCKET    = 10
BONUS_FIB_KEY_LEVEL        = 5
BONUS_CANDLE_PIN_BAR       = 10
BONUS_CANDLE_ENGULFING     = 8
BONUS_HIDDEN_DIVERGENCE    = 6
BONUS_VOLUME_EXPLOSION     = 7
BONUS_POST_SQUEEZE         = 10
BONUS_MARKET_STRUCT_TREND  = 8
BONUS_FUNDING_LS_ALIGN     = 6

BONUS_CAP_TIERS = [(36, 18), (44, 26), (9999, 36)]

# ══════════════════════════════════════════════════════════════
# 극단 과매도/과매수 (1h Bot: entry=1h, mid=4h, macro=1d)
# ══════════════════════════════════════════════════════════════
EXTREME_OVERSOLD_15M  = 32    # entry(1h)
EXTREME_OVERSOLD_1H   = 32    # mid(4h)
EXTREME_OVERSOLD_4H   = 38    # macro(1d) — 1d는 더 느리게 회복
EXTREME_OVERBOUGHT_15M = 68
EXTREME_OVERBOUGHT_1H  = 68
EXTREME_OVERBOUGHT_4H  = 62   # macro(1d) 62 이상 = 명확한 과매수

BB_STREAK_SUPPRESS_RSI_EXEMPT = 28

# ══════════════════════════════════════════════════════════════
# 페널티 파라미터
# ══════════════════════════════════════════════════════════════
MTF_RSI_OVERBOUGHT_1H         = 72
MTF_RSI_OVERBOUGHT_1H_MILD    = 68
MTF_RSI_OVERBOUGHT_4H         = 65
MTF_RSI_OVERSOLD_1H           = 28
MTF_RSI_OVERSOLD_1H_MILD      = 32
MTF_RSI_OVERSOLD_4H           = 35
MTF_RSI_PENALTY_STRONG        = 0.85
MTF_RSI_PENALTY_MILD          = 0.92
MTF_RSI_OVERSOLD_1H_EXTREME   = 24
MTF_RSI_OVERBOUGHT_1H_EXTREME = 76

EXPLOSIVE_EXHAUSTION_RSI_LONG  = 70
EXPLOSIVE_EXHAUSTION_RSI_SHORT = 30
EXPLOSIVE_EXHAUSTION_PENALTY   = 0.88

CHOCH_AGAINST_PENALTY = 0.88
BOS_CONFLICT_PENALTY  = 0.82

CANDLE_MOMENTUM_PENALTY_RANGING   = 0.80
CANDLE_MOMENTUM_PENALTY_EXPLOSIVE = 0.85
CANDLE_MOMENTUM_PENALTY_TRENDING  = 0.90

SQUEEZE_CANDLE_BONUS_MULT = 0.50

GATE_PENALTY_SINGLE = 0.92
GATE_PENALTY_DUAL   = 0.80

OI_SPIKE_THRESHOLD     = 0.80
OI_SPIKE_SCORE_PENALTY = 20

VOLUME_PENALTY_LOW_THRESHOLD = 20
VOLUME_PENALTY_MID_THRESHOLD = 35
VOLUME_PENALTY_LOW = -8
VOLUME_PENALTY_MID = -5

EXPLOSIVE_BOS_CONFLICT_PENALTY = 0.85

ADX_COUNTER_TREND_THRESHOLD_STRONG = 45
ADX_COUNTER_TREND_THRESHOLD_MID    = 35
ADX_COUNTER_TREND_THRESHOLD_WEAK   = 25
ADX_COUNTER_TREND_BOOST_STRONG     = 15
ADX_COUNTER_TREND_BOOST_MID        = 10
ADX_COUNTER_TREND_BOOST_WEAK       = 5

COUNTER_TREND_BONUS_CAP   = 14
BOS_ONLY_BONUS_CAP        = 22
ADX_BOS_COUNTER_THRESHOLD = 30

FVG_AMBIGUOUS_VOL_THRESHOLD = 30.0

EXPLOSIVE_OVERSOLD_GUARD_RSI   = 45
EXPLOSIVE_OVERSOLD_GUARD_BB    = 0.25
EXPLOSIVE_OVERBOUGHT_GUARD_RSI = 60
EXPLOSIVE_OVERBOUGHT_GUARD_BB  = 0.75
EXPLOSIVE_OVERSOLD_PENALTY     = 0.80

LIQ_REVERSE_PENALTY = 0.92
HIDDEN_DIV_MIN_ADX  = 18

# ══════════════════════════════════════════════════════════════
# SMC / 피보나치
# ══════════════════════════════════════════════════════════════
FIB_LOOKBACK      = 50
FIB_TOLERANCE     = 0.015
FIB_MIN_SWING_PCT = 0.03

VOL_DIV_PRICE_THRESHOLD   = 0.005
VOL_DIV_BULL_VOLUME_RATIO = 1.50
VOL_DIV_BEAR_VOLUME_RATIO = 0.67

MARKET_STRUCT_SWING_THRESHOLD = 0.005

# ══════════════════════════════════════════════════════════════
# 신호 임계값
# ══════════════════════════════════════════════════════════════
REGIME_THRESHOLDS = {
    "SQUEEZE":   66,
    "TRENDING":  64,
    "RANGING":   63,
    "EXPLOSIVE": 66,
}

# ══════════════════════════════════════════════════════════════
# 동적 쿨다운
# ══════════════════════════════════════════════════════════════
PRICE_MOVE_SUPPRESS_STRONG = 0.05
PRICE_MOVE_SUPPRESS_MILD   = 0.03
PRICE_MOVE_RESET_THRESHOLD = -0.025
COOLDOWN_SUPPRESSED_STRONG = 480
COOLDOWN_SUPPRESSED_MILD   = 300

# ══════════════════════════════════════════════════════════════
# 시스템
# ══════════════════════════════════════════════════════════════
MAX_RETRIES             = 3
RETRY_DELAY_S           = 5
SIGNAL_COOLDOWN_MINUTES = 240
SIGNAL_STATE_FILE       = "/tmp/bot_state/signal_state.json"
ORDERBOOK_DEPTH         = 20
LOG_LEVEL               = "INFO"
LOG_FILE                = "logs/bot.log"

# ══════════════════════════════════════════════════════════════
# ① 4h 메타 레짐 레이어
# ── (4h_regime, 1h_regime) → 임계값 조정값 ────────────────────
# 음수: 진입 완화 (추세 확증), 양수: 진입 강화 (불확실/위험)
# ══════════════════════════════════════════════════════════════
META_REGIME_THRESHOLD_ADJ: dict = {
    # 4h 추세 중 — 1h가 같은 추세면 완화, 횡보면 정상(눌림목), 압축이면 소폭 완화
    ("TRENDING",  "TRENDING"):  -3,
    ("TRENDING",  "RANGING"):    0,
    ("TRENDING",  "SQUEEZE"):   -2,
    ("TRENDING",  "EXPLOSIVE"): +2,
    # 4h 횡보 중 — 신뢰도 낮음
    ("RANGING",   "TRENDING"):  +5,
    ("RANGING",   "RANGING"):   +5,
    ("RANGING",   "SQUEEZE"):   +3,
    ("RANGING",   "EXPLOSIVE"): +3,
    # 4h 급등/급락 — 추격 위험
    ("EXPLOSIVE", "TRENDING"):  +8,
    ("EXPLOSIVE", "RANGING"):   +3,
    ("EXPLOSIVE", "SQUEEZE"):   +4,
    ("EXPLOSIVE", "EXPLOSIVE"): +6,
    # 4h 압축 — 방향 선택 구간
    ("SQUEEZE",   "TRENDING"):  -2,
    ("SQUEEZE",   "RANGING"):    0,
    ("SQUEEZE",   "SQUEEZE"):   -5,  # 이중 압축 = 대폭발 직전
    ("SQUEEZE",   "EXPLOSIVE"): -3,
    # UNKNOWN fallback
    ("UNKNOWN",   "TRENDING"):   0,
    ("UNKNOWN",   "RANGING"):    0,
    ("UNKNOWN",   "SQUEEZE"):    0,
    ("UNKNOWN",   "EXPLOSIVE"):  0,
}

# ══════════════════════════════════════════════════════════════
# ② 일봉 바이어스
# ══════════════════════════════════════════════════════════════
DAILY_BIAS_THRESHOLD_ADJ_ALIGN   = -3   # 방향 일치 → 진입 완화
DAILY_BIAS_THRESHOLD_ADJ_AGAINST = +7   # 역추세    → 진입 강화

# ══════════════════════════════════════════════════════════════
# ③ 4h BOS / CHoCH
# 1h 대비 가중치 상향: BOS +12pt(vs +8), CHoCH ×0.80(vs ×0.88)
# ══════════════════════════════════════════════════════════════
BONUS_BOS_CONFIRM_4H     = 12
CHOCH_4H_AGAINST_PENALTY = 0.80
BOS_4H_CONFLICT_PENALTY  = 0.78

# ══════════════════════════════════════════════════════════════
# ④ 거래 세션 필터 (UTC 기준)
# ── OKX 선물 유동성 패턴 반영 ────────────────────────────────
# 런던+NY 오버랩(13-16h): 최고 유동성 → 임계값 완화
# NY(16-22h): 높은 유동성
# 런던(07-13h): 중간 유동성 → 기본값
# 아시아(22-07h): 낮은 유동성 → 오신호 위험 ↑
# 주말: 유동성 급감
# ══════════════════════════════════════════════════════════════
SESSION_ADJ_OVERLAP = -3
SESSION_ADJ_NY      = -2
SESSION_ADJ_LONDON  =  0
SESSION_ADJ_ASIA    = +4
SESSION_ADJ_WEEKEND = +6

# ══════════════════════════════════════════════════════════════
# ⑦ 펀딩비 8h 사이클
# OKX 정산 시간: 00:00, 08:00, 16:00 UTC
# 정산 1h 전후(23,0,7,8,15,16): 포지션 청산 노이즈 구간
# ══════════════════════════════════════════════════════════════
FUNDING_CYCLE_ADJ   = +3
FUNDING_CYCLE_HOURS = [23, 0, 7, 8, 15, 16]
