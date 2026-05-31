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
# [v3.0] 국면별 가중치
# ══════════════════════════════════════════════════════════════════════
SCORE_WEIGHTS = {
    "rsi":          0.38,
    "bollinger":    0.31,
    "taker_volume": 0.23,
    "volume":       0.08,
}
SCORE_WEIGHTS_RANGING = {
    "rsi":          0.39,
    "bollinger":    0.35,
    "taker_volume": 0.13,
    "volume":       0.13,
}
SCORE_WEIGHTS_TRENDING = {
    "rsi":          0.17,
    "bollinger":    0.14,
    "taker_volume": 0.57,
    "volume":       0.12,
}
SCORE_WEIGHTS_EXPLOSIVE = {
    "rsi":          0.10,
    "bollinger":    0.08,
    "taker_volume": 0.59,
    "volume":       0.23,
}
SCORE_WEIGHTS_SQUEEZE = {
    "rsi":          0.17,
    "bollinger":    0.51,
    "taker_volume": 0.20,
    "volume":       0.12,
}
REGIME_SCORE_WEIGHTS = {
    "RANGING":   SCORE_WEIGHTS_RANGING,
    "TRENDING":  SCORE_WEIGHTS_TRENDING,
    "EXPLOSIVE": SCORE_WEIGHTS_EXPLOSIVE,
    "SQUEEZE":   SCORE_WEIGHTS_SQUEEZE,
    "UNKNOWN":   SCORE_WEIGHTS,
}

# ══════════════════════════════════════════════════════════════════════
# 보너스 체계
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

BONUS_CAP_TIERS = [(38, 22), (48, 32), (9999, 42)]

# ══════════════════════════════════════════════════════════════════════
# [v3.0] 신규 보너스
# ══════════════════════════════════════════════════════════════════════
BONUS_SMART_MONEY_STRONG    = 15
BONUS_SMART_MONEY_MILD      = 8
SMART_MONEY_DIV_STRONG      = 0.15
SMART_MONEY_DIV_MILD        = 0.10

BONUS_OI_TREND_CONFIRM      = 10
BONUS_OI_REVERSAL_SIGNAL    = 6
OI_CHANGE_THRESHOLD         = 0.02
OI_PRICE_CHANGE_THRESHOLD   = 0.008

BONUS_FUNDING_FLIP          = 8
BONUS_FUNDING_EXTREME_ACCUM = 8
FUNDING_HISTORY_LIMIT       = 8
FUNDING_EXTREME_THRESHOLD   = 0.001

BONUS_CANDLE_1D_PIN_BAR     = 20
BONUS_CANDLE_1D_ENGULFING   = 18
BONUS_CANDLE_4H_PIN_BAR     = 14
BONUS_CANDLE_4H_ENGULFING   = 12

BONUS_MTF_MOMENTUM_FULL     = 15
BONUS_MTF_MOMENTUM_PARTIAL  = 7
MTF_MOMENTUM_RSI_SLOPE_MIN  = 2.0

BONUS_WEEKLY_KEY_LEVEL      = 8
WEEKLY_LEVEL_TOLERANCE      = 0.003

EMA_STRUCTURE_ALIGN_ADJ     = -5
EMA_STRUCTURE_AGAINST_ADJ   = +8
EMA_DISTANCE_EXTREME        = 0.15
EMA_DISTANCE_EXTREME_ADJ    = +5

# ══════════════════════════════════════════════════════════════════════
# 극단 과매도/과매수
# ══════════════════════════════════════════════════════════════════════
EXTREME_OVERSOLD_15M  = 32
EXTREME_OVERSOLD_1H   = 32
EXTREME_OVERSOLD_4H   = 32   # [I-3] 1D RSI기준 엄격화 (was 38)
EXTREME_OVERBOUGHT_15M = 68
EXTREME_OVERBOUGHT_1H  = 68
EXTREME_OVERBOUGHT_4H  = 68   # [I-3] (was 62)

BB_STREAK_SUPPRESS_RSI_EXEMPT = 28

# ══════════════════════════════════════════════════════════════════════
# 패널티
# ══════════════════════════════════════════════════════════════════════
MTF_RSI_OVERBOUGHT_1H         = 72
MTF_RSI_OVERBOUGHT_1H_MILD    = 68
MTF_RSI_OVERBOUGHT_4H         = 60   # [I-3] (was 65)
MTF_RSI_OVERSOLD_1H           = 28
MTF_RSI_OVERSOLD_1H_MILD      = 32
MTF_RSI_OVERSOLD_4H           = 40   # [I-3] (was 35)
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

LIQ_REVERSE_PENALTY = 0.80   # [v3.4 개선2] 0.92 → 0.80 (역방향 청산 패널티 강화)
HIDDEN_DIV_MIN_ADX  = 18

# ══════════════════════════════════════════════════════════════════════
# [v3.1] 불량신호 방지 — 기본 6개
# ══════════════════════════════════════════════════════════════════════
PRICE_BAND_COOLDOWN_PCT      = 0.010   # [v3.4] 0.005 → 0.010 (1% 이내 재진입 억제)

BEARISH_FVG_LONG_PENALTY     = -12
BEARISH_FVG_OVERHEAD_PENALTY = -6

MACD_BEARISH_LONG_PENALTY    = -8

CONSECUTIVE_SIGNAL_ADJ       = 3
CONSECUTIVE_SIGNAL_MAX_ADJ   = 9

# ══════════════════════════════════════════════════════════════════════
# [v3.2] 불량신호 방지 — 확장 (A/B/C/D/E)
# ══════════════════════════════════════════════════════════════════════
HEADWIND_PRESSURE_PER_FACTOR  = 3
HEADWIND_PRESSURE_MAX_ADJ     = 12

MOMENTUM_CONTEXT_ADJ          = 5

RANGING_SENTIMENT_MULT        = 0.50

RANGING_REVERSE_BONUS_CAP     = 20

EMA20_POSITION_ADJ            = 4

WEAK_BASE_SCORE_THRESHOLD     = 55.0
WEAK_BASE_BONUS_THRESHOLD     = 25
WEAK_BASE_BONUS_CAP           = 18

MAX_BONUS_TO_BASE_RATIO       = 0.55
MIN_BONUS_FLOOR               = 10

RANGING_DURATION_ADJ_MID      = 2
RANGING_DURATION_ADJ_LONG     = 4

# ══════════════════════════════════════════════════════════════════════
# [v3.3] 추세 포착 강화 — 양방향 대칭 (패밀리 A~E)
# ══════════════════════════════════════════════════════════════════════
EXTREME_EMA_MULT_FLOOR          = 0.92
EXTREME_THRESHOLD_CAP           = 68
EXTREME_BIAS_RELIEF             = 4
EXTREME_MICRO_CAP               = -8
EXTREME_BOS_RELIEF              = 0.08
EXTREME_CHOCH_RELIEF            = 0.06
EXTREME_FVG_PENALTY_MULT        = 0.5

MACD_HIST_TURN_BONUS            = 6

RSI_4H_EXTREME_OVERSOLD         = 20
RSI_4H_EXTREME_OVERBOUGHT       = 80
BONUS_4H_EXTREME_REVERSAL       = 12
BONUS_MTF_EXTREME_CONFIRM       = 6
RSI_4H_EXTREME_THRESHOLD_RELIEF = 5

TRENDING_RSI_SOFT_RELIEF        = 0.05

CONSECUTIVE_SIGNAL_ADJ_TREND    = 1

# ══════════════════════════════════════════════════════════════════════
# [v3.4] 신규 파라미터
# ══════════════════════════════════════════════════════════════════════

# [개선 2] SHORT/LONG 역풍필터 확장 — 청산/시장구조/주간레벨 pressure 반영
# A-2 역풍 체크에 추가된 요소들 (각 +1 pressure → ×HEADWIND_PRESSURE_PER_FACTOR)
# 별도 on/off 파라미터 (True=활성화)
HEADWIND_LIQ_REVERSE_ENABLE      = True   # 역방향 청산 감지 → pressure +1
HEADWIND_FAILED_STRUCT_ENABLE    = True   # 모순 시장구조(붕괴실패/돌파실패) → pressure +1
HEADWIND_WEEKLY_LEVEL_ENABLE     = True   # 역방향 주간레벨 근접 → pressure +1

# [개선 4] 모순 시장구조 보너스 상쇄
# LH + 붕괴실패 동시 발생 시 LH 보너스 무효화 (양방향 대칭)
CONFLICT_STRUCT_BONUS_CANCEL     = True

# [개선 5] SQUEEZE 구간 BOS 보너스 삭감 배율
SQUEEZE_BOS_BONUS_MULT           = 0.30   # 1h-BOS: 8→2pt, 4h-BOS: 12→4pt

# ──────────────────────────────────────────────────────────────────
# [v3.4.1] 롱 포착 강화 — 아이디어 1~6
# ──────────────────────────────────────────────────────────────────

# [아이디어 1] A-2 MACD 역풍 조건 정밀화
# MACD bearish이지만 histogram > 0 (골든크로스 진행 중)이면 역풍 아님
HEADWIND_MACD_HIST_EXEMPT        = True   # True=hist 양전환 시 MACD pressure 면제

# [아이디어 2] 역풍 카운터 전체 상한 축소
# A-2 + A-3 + C-1 합산 상한 (중복 측정 방지)
HEADWIND_PRESSURE_MAX_ADJ        = 9      # 12 → 9 (기존값 덮어씀)
HEADWIND_TOTAL_MAX_ADJ           = 15     # A-2+A-3+C-1 합산 절대 상한

# [아이디어 3] 숏청산 + BB 스퀴즈 조합 반전 보너스
BONUS_SHORT_LIQ_SQUEEZE_REVERSAL = 10    # 숏청산(sls≥0.6)+스퀴즈 롱 반전 보너스
LIQ_SQUEEZE_REVERSAL_MIN_PROXY   = 0.60  # sls/lls 최소 기준값

# [아이디어 4] SQUEEZE 구간 A-3/C-1 역풍필터 완화
# A-3(하락모멘텀), C-1(MA20위치) 는 SQUEEZE에서 적용 안 함
# A-2 상한도 절반으로 축소
SQUEEZE_HEADWIND_A3_C1_EXEMPT    = True   # True=SQUEEZE에서 A-3/C-1 면제
SQUEEZE_HEADWIND_MAX_DIVISOR     = 2      # SQUEEZE 시 A-2 상한 ÷2 (12→6, 9→4)

# [아이디어 5] SQUEEZE + 대량 청산 → 임계 직접 완화
SQUEEZE_LIQ_REVERSAL_THRESHOLD   = 0.60  # sls/lls 기준 (≥60%)
SQUEEZE_LIQ_REVERSAL_RELIEF      = 5     # 임계 완화 -5pt

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
SIGNAL_COOLDOWN_MINUTES_MIN = 60   # [v3.4] 어떤 경우에도 최소 1시간 쿨다운

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
# [v3.4 개선 3] SQUEEZE 메타레짐 완화 제거
# 근거: SQUEEZE는 방향 미결정 구간 → 임계 완화 근거 없음
#       Post-Squeeze 보너스(+10pt)가 이미 존재하므로 이중 완화 불필요
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
    # ↓ [v3.4 개선 3] SQUEEZE 행 전체 수정
    ("SQUEEZE",   "TRENDING"):   0,   # -2 → 0
    ("SQUEEZE",   "RANGING"):    0,   #  0 유지
    ("SQUEEZE",   "SQUEEZE"):    0,   # -5 → 0  ★핵심 수정
    ("SQUEEZE",   "EXPLOSIVE"): -2,   # -3 → -2 (스퀴즈→폭발만 소폭 완화 유지)
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

# ══════════════════════════════════════════════════════════════════════
# [v3.5] 스윙 전략 개선 파라미터 (I-2, I-4, I-7, I-8)
# ══════════════════════════════════════════════════════════════════════
MTF_TREND_PULLBACK_MULT      = 1.4   # I-2: 4H추세+1H조정 눌림목 보너스 배율
MTF_TREND_COUNTER_MULT       = 0.6   # I-2: 4H추세+1H조정 역추세 보너스 배율
MTF_RANGE_FAKE_BREAK_MULT    = 0.5   # I-2: 4H레인징+1H추세 BOS 페이크브레이크 배율
MTF_RANGE_FAKE_BREAK_THR_ADJ = 6     # I-2: 4H레인징+1H추세 임계 상향폭

BONUS_SUBCAP_MOMENTUM  = 20   # I-4: 모멘텀 카테고리 보너스 상한
BONUS_SUBCAP_STRUCTURE = 18   # I-4: 구조 카테고리 보너스 상한
BONUS_SUBCAP_CANDLE    = 12   # I-4: 캔들 카테고리 보너스 상한
BONUS_SUBCAP_SENTIMENT = 15   # I-4: 심리 카테고리 보너스 상한
BONUS_SUBCAP_LEVEL     = 14   # I-4: 레벨 카테고리 보너스 상한

RSI_1D_SLOPE_THRESHOLD = 2.0  # I-7: 1D RSI 기울기 유효 판정 임계
RSI_1D_SLOPE_ADJ       = 5    # I-7: 기울기 역방향 시 임계 상향폭
RSI_1D_SLOPE_RELIEF    = 3    # I-7: 기울기 순방향 시 임계 완화폭

DOUBLE_RANGING_ADJ     = 8    # I-8: 4H·1H 이중레인징 임계 상향폭
