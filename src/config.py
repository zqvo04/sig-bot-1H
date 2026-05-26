"""
config.py — 전역 설정 (1h Bot v3.0)
────────────────────────────────────────────────────────────────────
[v3.0 추가: 9개 개선 기능]

① 스마트머니 LS 다이버전스  (Top Trader vs Retail)
② OI 변화 + 가격 방향 매트릭스
③ 펀딩비 히스토리 추세
④ 1D 캔들 패턴
⑤ 4H 캔들 패턴
⑥ 멀티TF 모멘텀 정합 스코어
⑦ (Basis 분석 - Phase3)
⑧ 주간 키레벨 S/R
⑨ 1D EMA 구조 스코어

가중치 체계 1h 최적화:
  RANGING:   RSI↑ BB↑ Taker↓ Volume↑ (평균회귀 집중)
  TRENDING:  LS↑  Volume↑ Taker↓    (추세 확증 집중)
  EXPLOSIVE: LS↑  Volume↑           (모멘텀 집중)
  SQUEEZE:   BB↑  Volume↑ Taker↓    (압축 감지 집중)
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
ADX_WEAK_TREND   = 25
ADX_STRONG       = 50

VOLUME_4H_BASELINE_CANDLES  = 30
VOLUME_1H_BASELINE_CANDLES  = 120
VOLUME_CONFIRM_LOOKBACK     = 48
VOLUME_SPIKE_MULTIPLIER     = 1.5
VOLUME_STRONG_MULTIPLIER    = 2.5
VOLUME_EXPLOSION_MULTIPLIER = 2.0

# ══════════════════════════════════════════════════════════════════════
# EMA 배율
# ══════════════════════════════════════════════════════════════════════
EMA_MULTIPLIER           = {3: 0.52, 2: 0.72, 1: 0.88, 0: 1.00}
EMA_MULTIPLIER_RANGING   = {3: 0.82, 2: 0.90, 1: 0.96, 0: 1.00}
EMA_MULTIPLIER_TRENDING  = {3: 0.52, 2: 0.72, 1: 0.88, 0: 1.00}
EMA_MULTIPLIER_EXPLOSIVE = {3: 0.75, 2: 0.84, 1: 0.93, 0: 1.00}
EMA_MULTIPLIER_SQUEEZE   = {3: 0.80, 2: 0.87, 1: 0.95, 0: 1.00}
REGIME_EMA_MULTIPLIERS   = {
    "RANGING":   EMA_MULTIPLIER_RANGING,
    "TRENDING":  EMA_MULTIPLIER_TRENDING,
    "EXPLOSIVE": EMA_MULTIPLIER_EXPLOSIVE,
    "SQUEEZE":   EMA_MULTIPLIER_SQUEEZE,
    "UNKNOWN":   EMA_MULTIPLIER,
}

# ══════════════════════════════════════════════════════════════════════
# 시장 심리 임계값
# ══════════════════════════════════════════════════════════════════════
FUNDING_LONG_STRONG  = -0.0005
FUNDING_LONG_MILD    = -0.0001
FUNDING_SHORT_MILD   =  0.0005
FUNDING_SHORT_STRONG =  0.001

LS_LONG_EXTREME  = 0.72
LS_LONG_HIGH     = 0.65
LS_SHORT_EXTREME = 0.62
LS_SHORT_HIGH    = 0.55

TAKER_LOOKBACK    = 100
TAKER_STRONG_BUY  = 0.65
TAKER_STRONG_SELL = 0.65

LIQ_LOOKBACK_MINUTES = 60

REGIME_SQUEEZE_RATIO = 0.70
REGIME_TREND_ADX     = 25
REGIME_STRONG_ADX    = 40

# ══════════════════════════════════════════════════════════════════════
# [v3.0] 국면별 가중치 — 1h 최적화
# ══════════════════════════════════════════════════════════════════════

SCORE_WEIGHTS = {  # 기본 (UNKNOWN)
    "rsi":              0.26,
    "bollinger":        0.21,
    "funding_rate":     0.18,
    "long_short_ratio": 0.15,
    "taker_volume":     0.15,
    "volume":           0.05,
}

# RANGING: 평균회귀 집중
# 1h RSI/BB 신뢰도 높음 / Taker(5m)는 범위진입에 덜 중요 / Volume 의미↑
SCORE_WEIGHTS_RANGING = {
    "rsi":              0.30,   # +0 → 과매도/과매수 명확
    "bollinger":        0.27,   # +1 → %B 위치 중요
    "funding_rate":     0.12,
    "long_short_ratio": 0.12,
    "taker_volume":     0.09,   # -1 → 5m 데이터, 범위진입 덜 중요
    "volume":           0.10,   # +3 → 낮은 거래량 = 오실레이터 함정
}

# TRENDING: 추세 확증 집중
# LS 방향 + 거래량 중요 / RSI/BB 추세에선 덜 중요
SCORE_WEIGHTS_TRENDING = {
    "rsi":              0.10,
    "bollinger":        0.08,
    "funding_rate":     0.16,
    "long_short_ratio": 0.25,   # +3 → 추세 = 포지션 방향 중요
    "taker_volume":     0.30,   # -4 → 여전히 중요하나 1h에서 다소 완화
    "volume":           0.11,   # +2
}

# EXPLOSIVE: 모멘텀 집중
# Taker + LS + Volume 가장 중요
SCORE_WEIGHTS_EXPLOSIVE = {
    "rsi":              0.06,
    "bollinger":        0.05,
    "funding_rate":     0.13,
    "long_short_ratio": 0.26,   # +2
    "taker_volume":     0.36,   # -2
    "volume":           0.14,   # +4 → 거래량 폭발 확인 중요
}

# SQUEEZE: BB 압축 감지 집중
# BB가 핵심 / Volume↑ (거래량 없는 스퀴즈 = 노이즈)
SCORE_WEIGHTS_SQUEEZE = {
    "rsi":              0.13,   # -2
    "bollinger":        0.38,   # +3 → 핵심 지표
    "funding_rate":     0.12,
    "long_short_ratio": 0.13,
    "taker_volume":     0.15,   # -4
    "volume":           0.09,   # +4
}

REGIME_SCORE_WEIGHTS = {
    "RANGING":   SCORE_WEIGHTS_RANGING,
    "TRENDING":  SCORE_WEIGHTS_TRENDING,
    "EXPLOSIVE": SCORE_WEIGHTS_EXPLOSIVE,
    "SQUEEZE":   SCORE_WEIGHTS_SQUEEZE,
    "UNKNOWN":   SCORE_WEIGHTS,
}

# ══════════════════════════════════════════════════════════════════════
# 기존 보너스 체계
# ══════════════════════════════════════════════════════════════════════
BONUS_PULLBACK_ENTRY        = 12
BONUS_PULLBACK_ENTRY_WEAK   = 8
BONUS_PULLBACK_ENTRY_MICRO  = 4
BONUS_TREND_STRONG          = 12
BONUS_BB_RSI_ALIGN          = 8
BONUS_LIQUIDATION           = 10
BONUS_VOL_PRICE_DIV         = 10
BONUS_FAILED_BREAKOUT       = 12
BONUS_EXTREME_OVERSOLD_MTF  = 10
BONUS_FVG_ENTRY             = 8
BONUS_FVG_ENTRY_CONFLICTED  = 4
BONUS_BOS_CONFIRM           = 8
BONUS_BOS_CONFIRM_4H        = 12
BONUS_FIB_GOLDEN_POCKET     = 10
BONUS_FIB_KEY_LEVEL         = 5
BONUS_CANDLE_PIN_BAR        = 10
BONUS_CANDLE_ENGULFING      = 8
BONUS_HIDDEN_DIVERGENCE     = 6
BONUS_VOLUME_EXPLOSION      = 7
BONUS_POST_SQUEEZE          = 10
BONUS_MARKET_STRUCT_TREND   = 8
BONUS_FUNDING_LS_ALIGN      = 6

# [v3.0] 보너스 캡 상향 (새 보너스 반영)
BONUS_CAP_TIERS = [(38, 22), (48, 32), (9999, 42)]

# ══════════════════════════════════════════════════════════════════════
# [v3.0] 신규 보너스 상수
# ══════════════════════════════════════════════════════════════════════

# ① 스마트머니 LS 다이버전스
BONUS_SMART_MONEY_STRONG    = 15   # 고래 강력 반대편 포착
BONUS_SMART_MONEY_MILD      = 8
SMART_MONEY_DIV_STRONG      = 0.15  # 15%p 이상 괴리
SMART_MONEY_DIV_MILD        = 0.10  # 10%p 이상 괴리

# ② OI 변화 + 가격 방향 매트릭스
BONUS_OI_TREND_CONFIRM      = 10   # 가격 + OI 방향 일치 → 추세 확증
BONUS_OI_REVERSAL_SIGNAL    = 6    # 가격↓ + OI↓ → 청산 소진 (롱 기대)
OI_CHANGE_THRESHOLD         = 0.02  # OI 2% 이상 변화 시 유의미
OI_PRICE_CHANGE_THRESHOLD   = 0.008 # 가격 0.8% 이상 변화 시 유의미

# ③ 펀딩비 히스토리
BONUS_FUNDING_FLIP          = 8    # 음→양 or 양→음 전환
BONUS_FUNDING_EXTREME_ACCUM = 8    # 4연속 극단 → 역방향 유리
FUNDING_HISTORY_LIMIT       = 8    # 수집 개수 (8 × 8h = 64h)
FUNDING_EXTREME_THRESHOLD   = 0.001 # 0.1% 이상 = 극단값

# ④ 1D 캔들 패턴 (1h보다 2배 가중)
BONUS_CANDLE_1D_PIN_BAR     = 20
BONUS_CANDLE_1D_ENGULFING   = 18

# ⑤ 4H 캔들 패턴 (1h보다 1.4배 가중)
BONUS_CANDLE_4H_PIN_BAR     = 14
BONUS_CANDLE_4H_ENGULFING   = 12

# ⑥ 멀티TF 모멘텀 정합
BONUS_MTF_MOMENTUM_FULL     = 15   # 3/3 TF 방향 일치
BONUS_MTF_MOMENTUM_PARTIAL  = 7    # 2/3 TF 방향 일치
MTF_MOMENTUM_RSI_SLOPE_MIN  = 2.0  # RSI 기울기 최소값 (4캔들 기준)

# ⑧ 주간 키레벨 S/R
BONUS_WEEKLY_KEY_LEVEL      = 8    # 주간 고/저가 근접
WEEKLY_LEVEL_TOLERANCE      = 0.003 # 0.3% 이내

# ⑨ 1D EMA 구조
EMA_STRUCTURE_ALIGN_ADJ     = -5   # 임계값 완화 (구조 순방향)
EMA_STRUCTURE_AGAINST_ADJ   = +8   # 임계값 강화 (구조 역방향)
EMA_DISTANCE_EXTREME        = 0.15  # EMA200 대비 15% 이상 이격
EMA_DISTANCE_EXTREME_ADJ    = +5   # 극단 이격 시 임계값 추가 강화

# ══════════════════════════════════════════════════════════════════════
# 극단 과매도/과매수 (1h Bot TF 매핑)
# ══════════════════════════════════════════════════════════════════════
EXTREME_OVERSOLD_15M  = 32   # entry(1h)
EXTREME_OVERSOLD_1H   = 32   # mid(4h)
EXTREME_OVERSOLD_4H   = 38   # macro(1d)
EXTREME_OVERBOUGHT_15M = 68
EXTREME_OVERBOUGHT_1H  = 68
EXTREME_OVERBOUGHT_4H  = 62

BB_STREAK_SUPPRESS_RSI_EXEMPT = 28

# ══════════════════════════════════════════════════════════════════════
# 패널티 파라미터
# ══════════════════════════════════════════════════════════════════════
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

CHOCH_AGAINST_PENALTY    = 0.88
BOS_CONFLICT_PENALTY     = 0.82
CHOCH_4H_AGAINST_PENALTY = 0.80
BOS_4H_CONFLICT_PENALTY  = 0.78

CANDLE_MOMENTUM_PENALTY_RANGING   = 0.80
CANDLE_MOMENTUM_PENALTY_EXPLOSIVE = 0.85
CANDLE_MOMENTUM_PENALTY_TRENDING  = 0.90
SQUEEZE_CANDLE_BONUS_MULT         = 0.50

GATE_PENALTY_SINGLE = 0.92
GATE_PENALTY_DUAL   = 0.80

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

# ══════════════════════════════════════════════════════════════════════
# SMC / 피보나치
# ══════════════════════════════════════════════════════════════════════
FIB_LOOKBACK      = 50
FIB_TOLERANCE     = 0.015
FIB_MIN_SWING_PCT = 0.03

VOL_DIV_PRICE_THRESHOLD   = 0.005
VOL_DIV_BULL_VOLUME_RATIO = 1.50
VOL_DIV_BEAR_VOLUME_RATIO = 0.67
MARKET_STRUCT_SWING_THRESHOLD = 0.005

# ══════════════════════════════════════════════════════════════════════
# 신호 임계값
# ══════════════════════════════════════════════════════════════════════
REGIME_THRESHOLDS = {
    "SQUEEZE":   66,
    "TRENDING":  64,
    "RANGING":   63,
    "EXPLOSIVE": 66,
}

# ══════════════════════════════════════════════════════════════════════
# 동적 쿨다운
# ══════════════════════════════════════════════════════════════════════
PRICE_MOVE_SUPPRESS_STRONG  = 0.05
PRICE_MOVE_SUPPRESS_MILD    = 0.03
PRICE_MOVE_RESET_THRESHOLD  = -0.025
COOLDOWN_SUPPRESSED_STRONG  = 480
COOLDOWN_SUPPRESSED_MILD    = 300

# ══════════════════════════════════════════════════════════════════════
# 시스템
# ══════════════════════════════════════════════════════════════════════
MAX_RETRIES             = 3
RETRY_DELAY_S           = 5
SIGNAL_COOLDOWN_MINUTES = 240
SIGNAL_STATE_FILE       = "/tmp/bot_state/signal_state.json"
ORDERBOOK_DEPTH         = 20
LOG_LEVEL               = "INFO"
LOG_FILE                = "logs/bot.log"

# ══════════════════════════════════════════════════════════════════════
# v2.0 메타 레짐 / 바이어스 / 세션 / 펀딩사이클
# ══════════════════════════════════════════════════════════════════════
META_REGIME_THRESHOLD_ADJ: dict = {
    ("TRENDING",  "TRENDING"):  -3,
    ("TRENDING",  "RANGING"):    0,
    ("TRENDING",  "SQUEEZE"):   -2,
    ("TRENDING",  "EXPLOSIVE"): +2,
    ("RANGING",   "TRENDING"):  +5,
    ("RANGING",   "RANGING"):   +5,
    ("RANGING",   "SQUEEZE"):   +3,
    ("RANGING",   "EXPLOSIVE"): +3,
    ("EXPLOSIVE", "TRENDING"):  +8,
    ("EXPLOSIVE", "RANGING"):   +3,
    ("EXPLOSIVE", "SQUEEZE"):   +4,
    ("EXPLOSIVE", "EXPLOSIVE"): +6,
    ("SQUEEZE",   "TRENDING"):  -2,
    ("SQUEEZE",   "RANGING"):    0,
    ("SQUEEZE",   "SQUEEZE"):   -5,
    ("SQUEEZE",   "EXPLOSIVE"): -3,
    ("UNKNOWN",   "TRENDING"):   0,
    ("UNKNOWN",   "RANGING"):    0,
    ("UNKNOWN",   "SQUEEZE"):    0,
    ("UNKNOWN",   "EXPLOSIVE"):  0,
}

DAILY_BIAS_THRESHOLD_ADJ_ALIGN   = -3
DAILY_BIAS_THRESHOLD_ADJ_AGAINST = +7

SESSION_ADJ_OVERLAP = -3
SESSION_ADJ_NY      = -2
SESSION_ADJ_LONDON  =  0
SESSION_ADJ_ASIA    = +4
SESSION_ADJ_WEEKEND = +6

FUNDING_CYCLE_ADJ   = +3
FUNDING_CYCLE_HOURS = [23, 0, 7, 8, 15, 16]