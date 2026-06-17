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
# [v4.0] 극단 반전(추세전환) 포착 임계 완화 — 반전 세팅 더 자주 인식
EXTREME_OVERSOLD_15M  = 34   # was 32
EXTREME_OVERSOLD_1H   = 34   # was 32
EXTREME_OVERSOLD_4H   = 36   # was 32
EXTREME_OVERBOUGHT_15M = 66  # was 68
EXTREME_OVERBOUGHT_1H  = 66  # was 68
EXTREME_OVERBOUGHT_4H  = 64  # was 68

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

MAX_BONUS_TO_BASE_RATIO       = 0.65   # [v4.0] 0.55 → 0.65 (보너스 흡수폭 확대)
MIN_BONUS_FLOOR               = 12     # [v4.0] 10 → 12

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
    # [v4.0] 보수성 완화 — 기본 임계 하향 (스윙 신호 빈도 ↑)
    "SQUEEZE":   63,   # was 66
    "TRENDING":  59,   # was 64  (추세추종 신호 적극 포착)
    "RANGING":   61,   # was 63
    "EXPLOSIVE": 60,   # was 66  (변동성 폭발 구간 진입 강화)
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

# [v4.0] 세션 조정 완화 — 크립토는 24/7, 비주력 세션 과도 억제 제거
SESSION_ADJ_OVERLAP = -3
SESSION_ADJ_NY      = -2
SESSION_ADJ_LONDON  =  0
SESSION_ADJ_ASIA    = +2   # was +4
SESSION_ADJ_WEEKEND = +2   # was +6

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
BONUS_SUBCAP_LEVEL     = 16   # I-4: 레벨 카테고리 보너스 상한 (II-6 컨플루언스 수용 위해 14→16)

RSI_1D_SLOPE_THRESHOLD = 2.0  # I-7: 1D RSI 기울기 유효 판정 임계
RSI_1D_SLOPE_ADJ       = 5    # I-7: 기울기 역방향 시 임계 상향폭
RSI_1D_SLOPE_RELIEF    = 3    # I-7: 기울기 순방향 시 임계 완화폭

DOUBLE_RANGING_ADJ     = 8    # I-8: 4H·1H 이중레인징 임계 상향폭

# ══════════════════════════════════════════════════════════════════════
# [v3.6] 스윙 전략 신규 요소 (II-1,2,3,4,5,6,8,9)
# ══════════════════════════════════════════════════════════════════════

# ── [II-1] 되돌림 깊이 스코어링 (4H 스윙 기준) ──────────────────────
# 4H 추세에서 1H 진입 시 "충분히 눌린 자리"인지 정량 평가
RETRACE_MIN_SWING_PCT   = 0.02   # 유효 스윙 최소 폭 (스윙고가 대비 2%)
RETRACE_TOO_SHALLOW     = 0.15   # 15% 미만: 너무 얕음 (추세 초기 가속/노이즈)
RETRACE_OPTIMAL_LOW     = 0.35   # 35~65%: 적정 눌림 (황금구간)
RETRACE_OPTIMAL_HIGH    = 0.65
RETRACE_DEEP_HIGH       = 0.80   # 65~80%: 깊은 눌림 (반전 가능)
BONUS_RETRACE_OPTIMAL   = 8      # 적정 눌림 보너스
BONUS_RETRACE_DEEP      = 5      # 깊은 눌림 보너스
RETRACE_SHALLOW_THR_ADJ = 6      # 너무 얕음 → 임계 상향
RETRACE_BREAK_THR_ADJ   = 8      # 80%+ 추세붕괴 의심 → 임계 상향

# ── [II-2] ADX 기울기 필터 ──────────────────────────────────────────
ADX_SLOPE_LOOKBACK       = 4     # 현재 ADX vs N캔들 전
ADX_SLOPE_FALLING        = -3.0  # 추세 소진 판정 (ADX 하락)
ADX_SLOPE_RISING         = 5.0   # 추세 가속 판정 (ADX 급등)
ADX_SLOPE_FALLING_THR_ADJ = 5    # TRENDING+ADX하락+추세추종 → 임계 상향
BONUS_ADX_ACCELERATION   = 6     # TRENDING/EXPLOSIVE+ADX급등+추세정합 → 보너스

# ── [II-3] 오더블록 감지 ────────────────────────────────────────────
OB_LOOKBACK         = 30    # 탐색 캔들 수
OB_IMPULSE_ATR_MULT = 2.0   # 임펄스 캔들 판정 (ATR 배수)
OB_SCAN_BACK        = 6     # 임펄스 직전 역방향 캔들 탐색 범위
BONUS_ORDER_BLOCK   = 8     # OB 내부 진입 보너스 (방향 정합 시)

# ── [II-4] 레짐 전환 직후 신호 강화 ─────────────────────────────────
BONUS_REGIME_TRANSITION_RELEASE  = 12   # SQUEEZE→TRENDING/EXPLOSIVE (압축 해제)
BONUS_REGIME_TRANSITION_BREAKOUT = 8    # RANGING→TRENDING (박스 돌파, 4H非레인징 한정)
REGIME_EXHAUSTION_THR_ADJ        = 10   # TRENDING/EXPLOSIVE→RANGING 추세추종 억제

# ── [II-5] 추세 성숙도 지수 (4H 스윙 구조) ──────────────────────────
MATURITY_LOOKBACK     = 100  # 4H 스윙 탐색 범위
MATURITY_EARLY_MAX    = 2    # 1~2: 초기 추세
MATURITY_MID_MAX      = 4    # 3~4: 중기 추세 / 5+: 성숙 추세
MATURITY_LATE_THR_ADJ = 3    # [v4.0] 6 → 3 (추세추종 과잉 억제 완화)
MATURITY_EARLY_RELIEF = 2    # 초기 추세 추세추종 → 임계 완화

# ── [II-6] 레벨 컨플루언스 스코어 ───────────────────────────────────
# 피보황금포켓·FVG·주간레벨·오더블록 중첩 시 개별 보너스를 흡수·대체
BONUS_CONFLUENCE_2  = 8    # 2개 중첩
BONUS_CONFLUENCE_3  = 15   # 3개 이상 중첩

# ── [II-8] 펀딩비 극단누적 후 반전(쿨링) 신호 ──────────────────────
BONUS_FUNDING_COOLING   = 6   # 과열 해소 시작 → 역방향 진입 타이밍 보너스
FUNDING_COOLING_MIN_CONSEC = 3  # 직전 연속 극단 최소 횟수

# ── [II-9] OI 추세 강화 (방향성 기울기) ─────────────────────────────
OI_TREND_MIN_POINTS     = 4      # 기울기 계산 최소 포인트
OI_TREND_SLOPE_THRESHOLD = 0.015 # OI 추세 유효 변화율 (윈도우 누적 1.5%)
BONUS_OI_TREND_SLOPE    = 5      # OI 추세+가격 정합 → 보너스

# ══════════════════════════════════════════════════════════════════════
# [v4.0] 대대적 개선 — 보수성 완화 · 추세추종/전환 강화 · TP/SL · Notion
# ══════════════════════════════════════════════════════════════════════

# ── [v4.0-1] 임계값 순(純) 인플레이션 캡 ──────────────────────────────
# 수많은 가산 필터가 누적되어 임계값이 80~90까지 치솟아 신호가 질식되던 문제.
# 비극단·비역추세(EMA 3역방향 아님) 신호는 기본임계 + 캡 이내로 제한한다.
THRESHOLD_NET_INFLATION_CAP   = 10   # 기본임계 대비 최대 +10pt까지만 상승 허용
THRESHOLD_NET_INFLATION_FLOOR = 12   # 기본임계 대비 최대 -12pt까지 완화 허용

# ── [v4.0-2] 추세정합 진입 임계 완화 ─────────────────────────────────
# 레짐 TRENDING/EXPLOSIVE + EMA 순방향 + MACD 정합(_trend_aligned)인
# "확정 추세추종" 진입은 적극 포착한다.
TREND_ALIGNED_THR_RELIEF      = 5    # _trend_aligned → 임계 -5pt
TREND_ALIGNED_EARLY_EXTRA     = 2    # + 초기/중기 추세면 추가 -2pt

# ── [v4.0-3] 추세전환(CHoCH/극단반전) 포착 강화 ──────────────────────
# 1h/4h CHoCH(전환)가 진입 방향과 "정합"일 때 보너스 부여(기존엔 역방향 패널티만 존재).
BONUS_CHOCH_ALIGN_1H          = 8    # 진입방향과 같은 CHoCH(전환) → 보너스
BONUS_CHOCH_ALIGN_4H          = 12

# ── [v4.0-4] TP/SL 산출 (성공/실패 자동 판정 기준) ───────────────────
# 스윙(1h, 최대 3일 보유) 기준 ATR·구조 결합 손절/익절.
TPSL_ATR_SL_MULT      = 2.0     # 손절 거리 = ATR × 배수
TPSL_MIN_SL_PCT       = 0.012   # 손절 최소 1.2%
TPSL_MAX_SL_PCT       = 0.050   # 손절 최대 5.0%
TPSL_TP_R_MULTIPLE    = 2.0     # 익절 = 손절거리 × R배수 (기본 2R)
TPSL_USE_STRUCTURE    = True    # 직전 스윙 고/저점을 손절에 우선 반영
TPSL_STRUCTURE_BUFFER = 0.001   # 구조 손절 버퍼 0.1%

# 신호 등급별 익절 R 배수 (강한 신호일수록 더 멀리)
TPSL_TP_R_BY_GRADE = {"STRONG": 2.5, "GOOD": 2.0, "WATCH": 1.8}

# ── [v4.0-5] 성공/실패 자동 평가 ─────────────────────────────────────
EVAL_MAX_HOLD_HOURS   = 72      # 최대 보유 72h(3일) 경과 → 시장가 청산 판정
EVAL_SL_PRIORITY      = True    # 한 캔들 내 TP·SL 동시 터치 시 SL 우선(보수적)

# ── [v4.0-6] Notion 연동 ─────────────────────────────────────────────
# Secrets(GitHub Actions) 또는 환경변수로 주입.
#   NOTION_TOKEN          : Notion 내부 통합(Integration) 시크릿 토큰
#   NOTION_DATABASE_ID    : 신호 로그 DB ID (없으면 NOTION_PARENT_PAGE_ID 하위에 자동 생성)
#   NOTION_PARENT_PAGE_ID : (선택) DB 자동 생성용 부모 페이지 ID
NOTION_TOKEN          = os.getenv("NOTION_TOKEN", "")
NOTION_DATABASE_ID    = os.getenv("NOTION_DATABASE_ID", "")
NOTION_PARENT_PAGE_ID = os.getenv("NOTION_PARENT_PAGE_ID", "")
NOTION_DB_TITLE       = "1H Signal Log"
NOTION_API_VERSION    = "2022-06-28"
NOTION_ENABLED        = bool(NOTION_TOKEN)

# ══════════════════════════════════════════════════════════════════════
# [v5.0] Trend-First, Reversal-Gated 대대적 개편
# ══════════════════════════════════════════════════════════════════════
# 진단: 봇이 "추세추종"이 아니라 "역추세 바닥잡기" 기계였다.
#   ① 멀티TF 과매도(is_extreme)가 만능 면죄부 → 하락추세에서 떨어지는 칼 매수
#   ② 반전을 RSI 과매도만으로 정의(구조 확인 게이트 부재)
#   ③ 추세 재진입(피라미딩)을 오히려 처벌(연속/성숙도/ADX 패널티)
#   ④ 임계 인플레캡이 방향성을 모름(direction-blind)
#   ⑤ 1H 레짐 깜빡임으로 가중치·임계 출렁
# 해법: Daily+4H 거시추세 앵커 → 추세추종/역추세 두 트랙 분기.

# ── [A] 거시 추세 앵커 가중치 (directional_bias.py) ──────────────────
MACRO_W_EMA4          = 1.0    # 4H EMA(9/21) 방향
MACRO_W_EMA1D         = 1.0    # 1D EMA(9/21) 방향
MACRO_W_DAILY         = 1.0    # 일봉 바이어스(BULL/BEAR)
MACRO_W_ESTRUCT       = 1.0    # 1D EMA 정배열/역배열 구조
MACRO_W_MATURITY      = 0.5    # 4H HH/HL vs LH/LL 우세
MACRO_W_BOS4          = 0.5    # 4H 시장구조 돌파(BOS)
MACRO_TREND_THRESHOLD = 1.5    # |score| ≥ 1.5 → UP/DOWN, 그 외 NEUTRAL
MACRO_STRENGTH_DIVISOR = 1.5   # 강도 = |score| / divisor (0~3)

# ── [B] 반전 확인 게이트 (역추세 진입 면죄부 조건) ───────────────────
# 역추세 방향 극단 진입은 아래 확인요소 중 최소 N개 충족해야 면죄부(패널티 면제).
# 미충족 시 단순 과매도는 추세 패널티를 그대로 받아 사실상 발사되지 않는다.
#   요소: CHoCH정합 / MACD히스토그램 전환 / 반전 캔들(핀바·인걸핑) / 대량 역청산
REVERSAL_GATE_MIN_CONFIRMS = 2

# ── [C] 추세 재진입(피라미딩) — 연속신호 처벌을 완화로 반전 ──────────
# 추세추종 트랙에서는 같은 방향 연속 신호 = 추세 확정 → 임계 완화.
# (과밀 방지는 기존 동적 쿨다운/가격밴드가 담당)
REENTRY_RELIEF_PER  = 2    # 연속 1회당 임계 완화폭
REENTRY_MAX_RELIEF  = 6    # 재진입 완화 상한

# ── [D] 방향성 임계 (트랙별 비대칭) ──────────────────────────────────
THR_WITH_TREND_RELIEF   = 4    # 추세추종 트랙 추가 임계 완화
THR_COUNTER_NOGATE_ADJ  = 14   # 역추세 + 게이트 미충족 → 임계 대폭 상향(차단)
# 트랙별 순(純) 인플레이션 캡 (기본임계 대비 허용 변동폭)
TRACK_WITH_TREND_HI   = 4      # 추세추종: 최대 base+4 까지만 상승
TRACK_WITH_TREND_LO   = 14     # 추세추종: 최대 base-14 까지 완화
TRACK_COUNTER_HI      = 16     # 역추세: 최대 base+16 까지 상승(게이트 미충족 차단 수용)
TRACK_COUNTER_LO      = 6      # 역추세(게이트 통과): 최대 base-6 까지만 완화
TRACK_NEUTRAL_HI      = 10     # 중립 추세: 기존 v4.0 캡 유지
TRACK_NEUTRAL_LO      = 12

# ── [E] 레짐 히스테리시스 (1H 레짐 깜빡임 제거) ──────────────────────
# 새 레짐이 N회 연속 관측돼야 전환 인정. 그 전까지는 확정 레짐 유지.
REGIME_HYSTERESIS_CONFIRM = 2

# ── [F] 등급 산정 (트랙·게이트 반영) ─────────────────────────────────
# 추세추종+확정정합 = 등급 상향(STRONG 더 자주), 역추세 게이트 최소충족 = WATCH 유지.
GRADE_WITH_TREND_BONUS    = 8   # 추세추종(_trend_aligned)·게이트2+ 시 등급용 점수 가산
GRADE_STRONG_SCORE        = 80
GRADE_GOOD_SCORE          = 70

# ══════════════════════════════════════════════════════════════════════
# [v5.0.1] 감사(self-audit) 후속 — 기존 로직과의 충돌 해소 (C1/C2/C3)
# ══════════════════════════════════════════════════════════════════════
# [C1] 추세추종 풀백 재진입의 진입조건(역EMA·price<MA20)이 그대로 역풍필터
#   (A-2/A-3/C-1)에 걸려 v5.0 완화를 자기상쇄하던 문제 → with-trend 트랙에서
#   SQUEEZE와 동일하게 역풍필터 완화/면제.
WITH_TREND_HEADWIND_EXEMPT = True

# [C2] 동적 쿨다운이 "유리한 이동 후" 재진입을 480/300분 봉쇄해 피라미딩을
#   막던 문제 → 추세추종 재진입은 짧은 고정 쿨다운만 적용(과밀은 가격밴드 1%가 차단).
REENTRY_COOLDOWN_MINUTES   = 180   # 추세추종 재진입 최소 간격(3h ≈ 3캔들)

# [C3] EXPLOSIVE(변동성 폭발)는 즉시 포착해야 하므로 레짐 히스테리시스 평활 면제.
REGIME_HYSTERESIS_BYPASS   = ("EXPLOSIVE",)

# ══════════════════════════════════════════════════════════════════════
# [학습] Research Logger — 상태 중심 학습 데이터 적재 (신호와 독립)
# ══════════════════════════════════════════════════════════════════════
# 매시간을 1표본으로, (시장 상태, 이후 72h 차트 경로)를 JSONL로 적재한다.
# 신호 발생 여부와 무관. 라벨은 저장된 경로에서 오프라인 파생(수집 시 박제 안 함).
# 상세 설계: docs/LEARNING_DATA_DESIGN.md
RESEARCH_LOGGER_ENABLED = True                  # False(또는 env=0) 시 완전 no-op
RESEARCH_DATA_DIR       = "data/research"        # repo 루트 기준 상대경로
RESEARCH_PATH_HOURS     = 72                      # 경로 캡처 길이(=완성 기준 캔들 수)
RESEARCH_PATH_MIN_HOURS = 4                       # [P1] 이 시간 이상 경과 시부터 부분 경로 증분 저장
# [P4] 스키마 버전. L1 피처 화이트리스트(research_logger.build_state)·경로 포맷을
#      바꿀 때마다 +1 한다. v2 = 상태 중심(LEARNING_DATA_DESIGN.md) + 경로에 open(o) 포함.
RESEARCH_FEATURE_VERSION = 2
RESEARCH_FP_RSI_ZONES   = (35.0, 65.0)           # 지문 RSI존 경계 OS/MID/OB
RESEARCH_FP_VOL_SQUEEZE = 0.85                    # bb_width/avg < 이값 → SQUEEZE
RESEARCH_FP_VOL_EXPAND  = 1.20                    # bb_width/avg > 이값 → EXPANDED
RESEARCH_PATH_ROUND     = 6                       # 경로 상대변화율 반올림 자리수

# ── Notion 미러 (1H Research Snapshots DB) ──────────────────────────
# 매시 L1/L2/L3 1행 기록 + 72h 후 차트 움직임 결과 라벨 자동 기입.
# 원시 72h 경로 전체는 git JSONL이 보관, Notion은 필터·그룹 분석용 핵심 라벨만.
NOTION_RESEARCH_DB_ID   = (os.getenv("NOTION_RESEARCH_DB_ID")
                           or "530210d9989a43f39dcd89cc8a72eb07")
NOTION_RESEARCH_ENABLED = os.getenv("NOTION_RESEARCH_ENABLED", "1") not in ("0", "false", "False")


# ══════════════════════════════════════════════════════════════════════
# [WRF-4] Win-Rate-First, 4-Setup 아키텍처 (전면 개편)
# ══════════════════════════════════════════════════════════════════════
# 목적함수: max N_signals  s.t.  WinRate >= W_floor
#   → 보정된 승률확률 P̂(win) >= W_floor  AND  not VETO  일 때만 발사(페이퍼).
#   승률은 "보정+임계"가 보장, 빈도는 넓은 유니버스×4셋업×양방향, 비정상성은
#   거시방향(btc_macro) 층화 + 신뢰게이트가 차단한다.
# 라이브 봇은 절대 학습하지 않는다 — calibration_table.json만 읽는다.

def _wrf_f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)

def _wrf_i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return int(default)

# ── 알림 게이트 (학습기간엔 OFF·기록만; 커버리지 충족 후 true) ──────────
ALERT_ENABLED = os.getenv("ALERT_ENABLED", "false").lower() not in ("0", "false", "no", "")

# ── 실질 튜닝 파라미터 (하드캡 최소화: 백분위 윈도·극단컷·플로어) ────────
WRF_PCT_WINDOW     = _wrf_i("WRF_PCT_WINDOW", 200)    # 자기분포 백분위 윈도(1H 봉 수)
WRF_VWAP_WINDOW    = _wrf_i("WRF_VWAP_WINDOW", 48)    # 롤링 VWAP 윈도(1H 봉 수)
WRF_PCT_EXTREME_HI = _wrf_f("WRF_PCT_EXTREME_HI", 0.85)  # 상단 극단 컷(백분위)
WRF_PCT_EXTREME_LO = _wrf_f("WRF_PCT_EXTREME_LO", 0.15)  # 하단 극단 컷(백분위)
WRF_WIN_FLOOR      = _wrf_f("WRF_WIN_FLOOR", 0.58)    # 승률 플로어(발사 임계)

# ── 신뢰게이트(보정 자격) — 미충족 셀은 전부 보수적 prior로 동작 ────────
WRF_CELL_N_MIN        = _wrf_i("WRF_CELL_N_MIN", 100)   # 셀 탈중첩 독립표본 최소치
WRF_CELL_MACRO_MIN    = _wrf_i("WRF_CELL_MACRO_MIN", 2) # 셀이 커버해야 할 거시방향 종수
WRF_EMBARGO_HOURS     = _wrf_i("WRF_EMBARGO_HOURS", 72) # purged-CV embargo(자기상관 차단)
WRF_INDEP_STRIDE_H    = _wrf_i("WRF_INDEP_STRIDE_H", 24)# 탈중첩 독립표본 간격(시간)

# ── 콜드스타트 prior (보수적 고정 직교게이트) ────────────────────────────
# P̂_prior = logistic( b0[setup] + wC*C + wL*L + wF*F )  (C/L/F ∈ [-1,1] 방향정렬치)
# b0를 셋업별로 비대칭 설정: TF/MR은 레짐정합이라 base 높고, BO/RV는 base-rate가
# 낮아 강확증된 소수만 통과(자동 서열화). 중립 컨플루언스는 플로어 미만에 앉힌다.
WRF_PRIOR_B0 = {
    "TF": _wrf_f("WRF_PRIOR_B0_TF", -0.15),
    "BO": _wrf_f("WRF_PRIOR_B0_BO", -0.75),
    "MR": _wrf_f("WRF_PRIOR_B0_MR", -0.25),
    "RV": _wrf_f("WRF_PRIOR_B0_RV", -0.95),
}
WRF_PRIOR_WC = _wrf_f("WRF_PRIOR_WC", 1.10)   # 맥락(C) 가중
WRF_PRIOR_WL = _wrf_f("WRF_PRIOR_WL", 1.30)   # 위치(L) 가중
WRF_PRIOR_WF = _wrf_f("WRF_PRIOR_WF", 1.20)   # 흐름(F) 가중
WRF_PRIOR_CAP = _wrf_f("WRF_PRIOR_CAP", 0.72) # prior P̂ 상한(과신 방지)

# ── L0 VETO 하드캡 (≈4) ──────────────────────────────────────────────
WRF_VETO_SPREAD_BP    = _wrf_f("WRF_VETO_SPREAD_BP", 8.0)    # 스프레드 폭발(bp)
WRF_VETO_DATA_AGE_MIN = _wrf_f("WRF_VETO_DATA_AGE_MIN", 90)  # 데이터 신선도(분)
WRF_VETO_LIQ_CASCADE  = _wrf_i("WRF_VETO_LIQ_CASCADE", 5)    # 진입 정면 대량청산 캐스케이드 건수

# ── 셋업별 타임스톱(시간) — §4 사양 ──────────────────────────────────
WRF_TMAX = {"TF": 48, "BO": 36, "MR": 24, "RV": 48}

# ── BO 리테스트 허용 근접도 (돌파봉 이후 현재봉이 경계로 되돌아온 정도) ────
WRF_BO_RETEST_TOL = _wrf_f("WRF_BO_RETEST_TOL", 0.002)

# ── btc_macro 태깅 임계 (BTC 7D/30D 추세·EMA구조) ───────────────────────
WRF_MACRO_UP_PCT   = _wrf_f("WRF_MACRO_UP_PCT", 0.03)   # 7D 변화 ±3% 이상 → leg
WRF_MACRO_CHOP_PCT = _wrf_f("WRF_MACRO_CHOP_PCT", 0.015) # |7D| < 1.5% → CHOP 후보

# ── 사이징 (페이퍼) — size ∝ P̂ ──────────────────────────────────────
WRF_SIZE_BASE = _wrf_f("WRF_SIZE_BASE", 1.0)    # P̂=floor 기준 사이즈 단위
WRF_SIZE_MAX  = _wrf_f("WRF_SIZE_MAX", 2.0)     # 사이즈 상한 단위

# ── 산출물/경로 ──────────────────────────────────────────────────────
WRF_CALIB_TABLE = os.getenv("WRF_CALIB_TABLE", "data/calibration_table.json")
WRF_SCHEMA_VERSION = 3

# ── Notion WRF 2-DB ───────────────────────────────────────────────────
# 기존 DB("1H Signal Log" / "1H Research Snapshots")를 WRF 양식으로 개조해 재사용한다.
#   · 발사신호  → 1H Signal Log       (id 기본값 = 레거시 NOTION_DATABASE_ID)
#   · 스냅샷미러 → 1H Research Snapshots (id 기본값 = NOTION_RESEARCH_DB_ID)
# env로 다른 DB ID를 주면 그쪽을 쓴다(부모페이지 자동생성 폴백 유지).
NOTION_SIGNALS_DB_ID = (os.getenv("NOTION_SIGNALS_DB_ID")
                        or os.getenv("NOTION_DATABASE_ID")
                        or "aff12b160ec941ada0ce13b01b689e7c")
NOTION_SNAPSHOTS_DB_ID = (os.getenv("NOTION_SNAPSHOTS_DB_ID")
                          or os.getenv("NOTION_RESEARCH_DB_ID")
                          or "530210d9989a43f39dcd89cc8a72eb07")
NOTION_SIGNALS_DB_TITLE = "1H Signal Log"
NOTION_SNAPSHOTS_DB_TITLE = "1H Research Snapshots"
