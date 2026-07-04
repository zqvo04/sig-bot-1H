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

# [Phase 1] 유니버스 확장 (3 → 6): 빈도·데이터 누적속도를 동시에 끌어올린다.
# 셀(setup×regime×macro)당 표본 누적이 ×2배 → 보정 부활(Phase 2)을 앞당긴다.
# env SYMBOLS(쉼표구분)로 오버라이드 가능(되돌리기·A/B). 전부 OKX USDT-Swap 고유동.
_DEFAULT_SYMBOLS  = ["BTC/USDT", "ETH/USDT", "HYPE/USDT", "SOL/USDT", "SUI/USDT", "XRP/USDT"]
SYMBOLS: list     = ([s.strip() for s in os.getenv("SYMBOLS", "").split(",") if s.strip()]
                     or _DEFAULT_SYMBOLS)
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
# 라이브 봇은 절대 학습하지 않는다. 보정 학습은 중단됨(WRF_CALIB_DISABLED=true,
# 자격 게이트가 비현실적으로 높아 실효 ≈ 0) → 영구히 보수적 prior만 사용한다.

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
WRF_PCT_EXTREME_HI = _wrf_f("WRF_PCT_EXTREME_HI", 0.85)  # 상단 극단 컷(백분위) — MR RSI 극단(숏)
WRF_PCT_EXTREME_LO = _wrf_f("WRF_PCT_EXTREME_LO", 0.15)  # 하단 극단 컷(백분위) — MR RSI 극단(롱)
# [Pillar4-⑤] 극단컷 중앙화: 위 WRF_PCT_EXTREME_HI/LO는 README가 핵심 튜닝노브로 광고했으나
# 실제 코드 어디에도 배선되지 않은 死파라미터였다(디텍터가 0.1/0.9·0.12/0.88을 하드코딩).
# 이제 MR의 RSI 극단컷을 이 노브로 구동(배선)하고, 나머지 극단컷도 아래 명시 파라미터로 분리.
WRF_MR_BB_EXTREME_LO = _wrf_f("WRF_MR_BB_EXTREME_LO", 0.10)  # MR BB %b 극단(롱)
WRF_MR_BB_EXTREME_HI = _wrf_f("WRF_MR_BB_EXTREME_HI", 0.90)  # MR BB %b 극단(숏)
WRF_RV_RSI_EXTREME_LO = _wrf_f("WRF_RV_RSI_EXTREME_LO", 0.12)  # RV RSI 극단(롱·MR보다 타이트)
WRF_RV_RSI_EXTREME_HI = _wrf_f("WRF_RV_RSI_EXTREME_HI", 0.88)  # RV RSI 극단(숏)
WRF_RV_FUND_EXTREME_LO = _wrf_f("WRF_RV_FUND_EXTREME_LO", 0.10)  # RV 펀딩 극단(롱)
WRF_RV_FUND_EXTREME_HI = _wrf_f("WRF_RV_FUND_EXTREME_HI", 0.90)  # RV 펀딩 극단(숏)
# [Pillar4-①] pct_rank 동점/경계 편향 제거(midrank): (arr<=v).mean()은 추정 백분위를 +1/(2n)
# 상향 편향 → 상단 극단(숏 트리거)은 쉽고 하단 극단(롱 트리거)은 어려운 L/S 비대칭을 만든다.
# midrank=((arr<v)+(arr<=v))/2 로 대칭화(엄밀 정정). 기본 ON.
WRF_PCT_MIDRANK = os.getenv("WRF_PCT_MIDRANK", "true").lower() not in ("0", "false", "no", "")
# [Pillar4-②] TF 모멘텀 확인 대칭화: 구버전은 롱=macd_bull(엄격 강세)·숏=not macd_bull(중립0
# 포함)으로 숏에 관대(비대칭). 숏도 명시적 약세(히스토그램<0)를 요구해 대칭화.
WRF_TF_MACD_SYM = os.getenv("WRF_TF_MACD_SYM", "true").lower() not in ("0", "false", "no", "")
WRF_WIN_FLOOR      = _wrf_f("WRF_WIN_FLOOR", 0.58)    # 승률 플로어(발사 임계)

# ── near-miss 섀도 밴드 (콜드스타트 데이터 수집 · 발사 무영향) ──────────────
# 플로어 바로 아래 [floor-width, floor) 의 '문턱탈락' 후보(veto·RR은 통과, p_hat만
# 미달)를 shadow_band=True 로 태깅·기록한다. 발사하지 않으므로 라이브 손익 영향 0.
# 목적: 표본이 굶주린 클래스(특히 숏)의 near-miss를 모아 오프라인 보정·검증에 사용.
# 기본 ON(태깅·기록만). 토글 OFF 또는 width=0 이면 비활성(구동작 동일).
WRF_SHADOW_BAND       = os.getenv("WRF_SHADOW_BAND", "true").lower() not in ("0", "false", "no", "")
WRF_SHADOW_BAND_WIDTH = _wrf_f("WRF_SHADOW_BAND_WIDTH", 0.03)  # 플로어 아래 포착 폭

# ── [밴드반전] BB 밴드복귀 반전 디텍터 (원트랙 · 라이브 발사) ──────────────────
# 기존 MR/RV precond(CHoCH·반전봉)가 놓치는 소진반전 후보를 'BB 밴드복귀'로 포착해
# 다른 디텍터와 동일하게 라이브 발사한다(원트랙). 방향적합성/칼받기 차단은 prior C/L/F +
# floor(min-axis 소프트게이트) + 레짐 라우팅 역추세 억제가 담당. 트리거 임계는 과적합 경계상
# 원칙적 밴드복귀(0.80/0.20)로 단순화. 기본 ON. (구 'D-shadow 투트랙'을 원트랙으로 일원화.)
WRF_D_SHADOW       = os.getenv("WRF_D_SHADOW", "true").lower() not in ("0", "false", "no", "")
WRF_D_BBPCTB_HI    = _wrf_f("WRF_D_BBPCTB_HI", 0.80)   # 숏: BB %b ≥ (상단 밴드터치)
WRF_D_BBPCTB_LO    = _wrf_f("WRF_D_BBPCTB_LO", 0.20)   # 롱: BB %b ≤ (하단 밴드터치)
# 밴드복귀 확증(Path2-① · 과적합 경계 · 양방향): 밴드 외곽 이탈 후 '밴드 안 복귀'(턴)에서만
# 무장 → 밴드를 타고 오르는 강추세(band-ride=칼받기 FP)와 진짜 소진반전을 분리. 신규
# 파라미터 0개(기존 bb_hi/lo 재사용). df 부족 시 밴드터치로 graceful 폴백. False=구동작.
WRF_D_REQUIRE_REENTRY = os.getenv("WRF_D_REQUIRE_REENTRY", "true").lower() not in ("0", "false", "no", "")

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
    # [Phase A] BR(밴드반전) — RV에서 셋업 분리. b0는 RV와 동일(분리=재분류, 피팅 아님).
    "BR": _wrf_f("WRF_PRIOR_B0_BR", -0.95),
}
WRF_PRIOR_WC = _wrf_f("WRF_PRIOR_WC", 1.10)   # 맥락(C) 가중
WRF_PRIOR_WL = _wrf_f("WRF_PRIOR_WL", 1.30)   # 위치(L) 가중
WRF_PRIOR_WF = _wrf_f("WRF_PRIOR_WF", 1.20)   # 흐름(F) 가중
WRF_PRIOR_CAP = _wrf_f("WRF_PRIOR_CAP", 0.65) # prior P̂ 상한(검증데이터 0 → 과신 금지·소사이즈)
# 콜드스타트 직교게이트: 세 축(C/L/F)이 모두 최소 동의해야 prior 발사 허용.
# 한 축이라도 ~중립/역행(< 이 값)이면 '광범위 동의' 불충족 → 발사 보류(플로어 미만).
# 한 축(특히 위치 L)만 강해서 발사되던 약발(약흐름 추세롱) 차단. 보정셀엔 미적용.
WRF_PRIOR_MIN_AXIS = _wrf_f("WRF_PRIOR_MIN_AXIS", 0.10)
# [Pillar3-①/②] min-axis 연속화: 구버전은 한 축이라도 <0.10이면 p를 floor-0.03(=0.55)로
# 고정 → 사실상 floor 통과 불가한 '위장 하드베토'(불연속 절벽). 대신 약한 축의 '부족분'에
# 비례하는 연속 페널티를 로그오즈에서 차감 — 0.10 근방은 매끄럽게(near-miss FN 회복),
# 음수(역추세 칼받기) 축은 강하게 차단(FP 보존). prior·보정 양 경로에 일관 적용(불연속 제거).
WRF_PRIOR_MIN_AXIS_SOFT   = os.getenv("WRF_PRIOR_MIN_AXIS_SOFT", "true").lower() not in ("0", "false", "no", "")
WRF_PRIOR_MIN_AXIS_LAMBDA = _wrf_f("WRF_PRIOR_MIN_AXIS_LAMBDA", 2.5)  # 로그오즈 페널티 기울기

# ── L0 VETO 하드캡 (≈4) ──────────────────────────────────────────────
WRF_VETO_SPREAD_BP    = _wrf_f("WRF_VETO_SPREAD_BP", 8.0)    # 스프레드 폭발(bp)
WRF_VETO_DATA_AGE_MIN = _wrf_f("WRF_VETO_DATA_AGE_MIN", 90)  # 데이터 신선도(분)
WRF_VETO_LIQ_CASCADE  = _wrf_i("WRF_VETO_LIQ_CASCADE", 5)    # 진입 정면 대량청산 캐스케이드 건수

# ── 셋업별 타임스톱(시간) — §4 사양. BR=RV 동일(분리 이관·동작 보존) ──────
WRF_TMAX = {"TF": 48, "BO": 36, "MR": 24, "RV": 48, "BR": 48}

# ── BO 리테스트 허용 근접도 (돌파봉 이후 현재봉이 경계로 되돌아온 정도) ────
WRF_BO_RETEST_TOL = _wrf_f("WRF_BO_RETEST_TOL", 0.002)

# ── 반전형(MR/RV/BR) 맥락축 베이스: CHOP(레인지)에서 페이드 허용 정도 ───────
# 레인지 톱/바텀 반전은 완만 통과(>min_axis), 신선한 동방향 거시레그면 차단.
WRF_REV_CTX_BASE = _wrf_f("WRF_REV_CTX_BASE", 0.25)
# [Phase C] 반전형 C축 v2(심볼-로컬 구조 주입 · 기본 OFF): 구버전은 btc_macro echo만
# 써서 DOWNLEG×숏이 코인 자기상태와 무관하게 C=1.0으로 포화(고유값 3개 → floor·사이징
# 변별력 상실, 알트 예측력 약함). v2는 _ctx_struct_align(4H추세·일봉EMA·바이어스)을
# 주입해 macro 유효가중 0.75→0.34로 낮추고 심볼 자체 구조로 채운다. 출력 envelope
# [-0.5,1.0]·극단은 구설계와 동일(중간 해상도만 추가), 롱/숏 부호 대칭.
# 검증(오프라인 47결판·독립재구현): 고유값 3→10, IC +0.13→+0.20(시간분할 양구간 일관),
# 의미론 비반전. 단 데이터가 DOWNLEG/CHOP 단일레짐 → fade 방향은 UPLEG 관측 후 재검증
# 전제로 기본 OFF(5-I 검증→점등). 되돌리기·점등: WRF_REV_CTX_V2=true.
WRF_REV_CTX_V2 = os.getenv("WRF_REV_CTX_V2", "false").lower() not in ("0", "false", "no", "")

# ── [Phase C-v4] 임펄스-페이드 킬 (반전형 C축 개혁 — FP 누수 봉합·양방향 대칭) ──
# 진단(2026-06~07 반사실 3종 + 킬 검증, analysis/audit/verify_rev_ctx_reform.py):
#   · 게이트 열기(C를 stretch/decel 복합으로 완화 — 바닥 롱 개방) 실험 3종은 실현 승률
#     33~36%로 전부 기각 — 1h 상태피처로는 캐피출레이션 내부 바닥 타이밍이 분해 불가
#     (decel류 전환확인은 구조적으로 후행 → 반등 후 추격 진입만 산다).
#   · 반면 현행의 실측 출혈원은 반대쪽: macro 태그가 전환을 수일 후행하는 동안
#     '이미 돌아선 시장'에 대한 페이드(랠리 숏)가 C=+0.25~+1.0 확신으로 발사(결판 전패).
# 처방: 페이드 대상 레그가 자기분포 극단 스트레치(loc_vwap 백분위)이면서 심볼 자기
# 단기구조(1h EMA·MACD부호·BOS/CHoCH)상 아직 살아있으면(≥2/3) C=−0.5 강제.
# 사전등록 검증: 발사집합 승률 47.6→53.8%·평균R +0.278→+0.333, 새 발사 0(출혈 0).
# 표본 소수(자기상관) — fire-rights 사후검정이 계속 감시. OFF면 구동작(되돌리기).
WRF_REV_IMPULSE_KILL = os.getenv("WRF_REV_IMPULSE_KILL", "true").lower() not in ("0", "false", "no", "")
WRF_REV_IK_STRETCH   = _wrf_f("WRF_REV_IK_STRETCH", 0.6)   # |to_axis(loc_vwap)| ≥ → 극단 스트레치
WRF_REV_IK_ALIVE     = _wrf_i("WRF_REV_IK_ALIVE", 2)       # 레그 생존 신호 ≥ n/3 → 아직 임펄스

# ── 최소 RR 품질필터: prior 발사는 RR 이 이 값 미만이면 제외(저RR 잡신호 컷). ──
# 보정셀(calibrated)은 학습된 승률을 존중해 이 필터를 우회한다.
WRF_MIN_RR = _wrf_f("WRF_MIN_RR", 1.5)
# [Pillar3-③] EV-결합 게이트: 고정 RR≥1.5는 P̂을 무시해 고확률·중RR 셋업(예: P̂=0.65·RR=1.0,
# EV=+0.30R)을 학살하고 win-rate-first(MR TP=mid)와 모순. 대신 기대값 EV(R)=P̂·RR−(1−P̂)이
# EV_MIN 이상이면 통과(고확률일수록 RR 요구 완화 = EV 정합). 저확률·저RR 잡신호는 여전히 컷.
WRF_EV_GATE  = os.getenv("WRF_EV_GATE", "true").lower() not in ("0", "false", "no", "")
WRF_EV_MIN   = _wrf_f("WRF_EV_MIN", 0.15)   # 발사 최소 기대R(리스크 1단위당)
# [검증·완화] RR 하한. 구 1.0은 EV-게이트 취지(고확률일수록 RR 요구 완화)와 모순 —
# P̂=0.65·EV=+0.24인 고확신 BO숏을 RR<1.0만으로 발사동결(누적데이터 5건, far-SL 실현 4/5 TP·+3.7R).
# 0.85로 완화 → 품질은 EV_MIN이 담당. 저확률·저RR 잡신호는 EV_MIN이 여전히 컷. 되돌리기: =1.0.
WRF_EV_RR_FLOOR = _wrf_f("WRF_EV_RR_FLOOR", 0.85)  # RR 하한(EV 통과해도 적용)

# ── [G3] 구조 SL + ATR 쿠션: SL = 직전 스윙 ∓ ATR×cushion (TF/RV) ───────
# 스윙 바로 밑 0.1% 버퍼는 노이즈 윅에 취약 → ATR 쿠션으로 구조적 여유 부여.
# 0.0 으로 두면 구조선 바로 밑(버퍼만) = 구동작 근사(되돌리기 토글).
WRF_SL_ATR_CUSHION = _wrf_f("WRF_SL_ATR_CUSHION", 1.5)

# ── [G4] MR(횡보반전) 박스 기하학 TP/SL ──────────────────────────────────
# TP = 박스 중심선(mid, 승률우선) 또는 반대편 경계(opposite, RR우선).
# SL = 박스 경계 외곽 ∓ ATR×cushion. 진입이 경계에 가까울수록 RR↑(미달은 MIN_RR 컷).
WRF_MR_BOX_WINDOW  = _wrf_i("WRF_MR_BOX_WINDOW", 20)    # 박스 산정 윈도(1H 봉)
WRF_MR_ATR_CUSHION = _wrf_f("WRF_MR_ATR_CUSHION", 1.0)  # 박스 경계 외곽 ATR 쿠션
WRF_MR_TP_TARGET   = os.getenv("WRF_MR_TP_TARGET", "mid")  # "mid" | "opposite"

# ── [A4/G6] RV(전환) 게이트: CHoCH 필수 + 리테스트(스윕/키레벨거부) 필수 ──
# 전략 ④의 구조붕괴→리테스트→반전 시퀀스 강제. 첫 반전봉 나이프캐칭 방지.
# False 로 두면 구동작(느슨)으로 복귀(되돌리기 토글).
WRF_RV_REQUIRE_CHOCH  = os.getenv("WRF_RV_REQUIRE_CHOCH", "true").lower() not in ("0", "false", "no", "")
WRF_RV_REQUIRE_RETEST = os.getenv("WRF_RV_REQUIRE_RETEST", "true").lower() not in ("0", "false", "no", "")
WRF_RV_MIN_CONFIRMS   = _wrf_i("WRF_RV_MIN_CONFIRMS", 3)
# [Pillar2-①] RV precond 연성화(hard AND → soft score): 5중 동시 AND(n_exh·rev_candle·
# choch·retest·confirms≥3)는 grind에서 ∏pᵢ로 기하급수 소멸 → 숏 후보 자체가 생성 불가(FN의
# 핵심 발생지). 안전 최소치(n_exh≥1 ∧ rev_candle)만 게이트로 남기고 choch·retest·confirms는
# L에 가점/감점으로 흡수 → 부분정렬 반전도 후보화하되 약하면 P̂<floor로 자동 탈락(FP는 floor가 통제).
WRF_RV_SOFT_PRECOND   = os.getenv("WRF_RV_SOFT_PRECOND", "true").lower() not in ("0", "false", "no", "")
WRF_RV_SOFT_NO_CHOCH_MULT  = _wrf_f("WRF_RV_SOFT_NO_CHOCH_MULT", 0.82)  # CHoCH 부재 시 L 감쇠
WRF_RV_SOFT_NO_RETEST_MULT = _wrf_f("WRF_RV_SOFT_NO_RETEST_MULT", 0.90) # 리테스트 부재 시 L 감쇠
WRF_RV_SOFT_MIN_CONFIRMS   = _wrf_i("WRF_RV_SOFT_MIN_CONFIRMS", 2)      # 소프트모드 최소 확인수(완화)
# [Path1-②] 방향-사이드 신호(precision/FP): RV 청산·키레벨 거부를 진입방향에 맞는 쪽만
# 카운트(롱=숏청산·지지선거부 / 숏=롱청산·저항선거부). 감사결과 precond 임계는 이미
# 대칭이고 숏 FN은 시장(약세-과매도 편중)·엄격 precond 산물 — 본 토글은 '잘못된 쪽'
# 트리거 제거로 FP만 줄인다(양방향 대칭). [Pillar4-③] 기본 ON으로 승격(방향정합 — 하락장
# 롱청산이 칼받기 롱을 부추기던 비사이드 기본값 교정).
WRF_RV_SIDED_SIGNALS  = os.getenv("WRF_RV_SIDED_SIGNALS", "true").lower() not in ("0", "false", "no", "")
# [5-D 대칭성 감사] RV oi_flush 대칭성 수정 — analyze_oi_matrix가 생성 안 하는
# "reversal_short"(실측 0/1156)를 숏 조건에서 걸던 죽은 조건을 제거하고, weak_bounce
# (가격↑+OI↓=숏커버링 소진)를 숏 전용으로 교정(구동작은 롱·숏 양쪽에 걸어 롱이 2분면·
# 숏이 1분면으로 비대칭). false=구동작(되돌리기).
WRF_RV_OI_FLUSH_SYM   = os.getenv("WRF_RV_OI_FLUSH_SYM", "true").lower() not in ("0", "false", "no", "")
# [Path1-①] 레짐 조건부 라우팅(라이브 FP/FN 동시 — 가장 큰 레버·검증 후 ON): ema_4h·
# bias_1d·btc_macro 3중 정렬 강확정 추세에서만 작동(횡보 93%는 무변경 → idea B 함정 회피).
#   추세확정 시: ① 역추세 반전(MR/RV 추세반대 방향) 억제(칼받기 FP↓)
#               ② TF(추세추종) 활성화 — 1h-ADX 지연으로 RANGING이어도 추종 라우팅 복원(FN↓).
# [Pillar1] 기본 ON으로 승격. 역추세 억제는 밴드반전 원트랙 발사의 FP 통제와도 짝을 이룬다.
WRF_REGIME_ROUTING    = os.getenv("WRF_REGIME_ROUTING", "true").lower() not in ("0", "false", "no", "")
# [Pillar1-③] 라우팅 BTC-종속성 분리: 트리거를 btc_macro==DOWNLEG(=BTC 종속·지연) 대신
# 심볼 자신의 구조(ema_4h·bias_1d·ema_1d_struct)로 판정. BTC가 횡보해도 홀로 흘러내리는
# 알트가 TF 라우팅을 받는다(FN↓). btc_macro는 OR-가산(여전히 도움)·veto는 별도 유지.
WRF_ROUTING_SELF_STRUCT = os.getenv("WRF_ROUTING_SELF_STRUCT", "true").lower() not in ("0", "false", "no", "")

# ── [A1] TF 되돌림(피보) 배선: 4H 피보 zone(optimal/deep) 눌림 경로 ──────
# 얕은 눌림(1H EMA 정렬 유지 + loc 밴드) 외에, 깊은 눌림(피보 50~61.8%)도
# 4H 추세 정렬을 게이트로 포착. 1H EMA는 깊은 눌림에서 추세 반대로 튀므로
# 깊은 눌림 경로는 1H 정렬을 요구하지 않는다(4H 정렬로 대체).
WRF_TF_FIB_PULLBACK = os.getenv("WRF_TF_FIB_PULLBACK", "true").lower() not in ("0", "false", "no", "")

# ── [A5/G7] 반전캔들 거래량 게이트: 반전봉 거래량 > 직전 N봉 평균 × mult ──
# TF(눌림종료)·MR/RV(반전캔들)에 적용. 0.0 으로 두면 게이트 OFF(되돌리기 토글).
WRF_REV_VOL_MULT     = _wrf_f("WRF_REV_VOL_MULT", 1.0)
WRF_REV_VOL_LOOKBACK = _wrf_i("WRF_REV_VOL_LOOKBACK", 5)  # 직전 N봉 평균(전략=5)

# ── [G7] BO 돌파 펀딩 컨트래리언 확증(하드게이트 아님, L 가점) ────────────
# 군중이 돌파 반대로 쏠림(롱돌파+군중숏=펀딩 저백분위) → 스퀴즈 연료 → L 가점.
WRF_BO_FUND_LO    = _wrf_f("WRF_BO_FUND_LO", 0.20)   # 롱돌파: 펀딩 백분위 ≤ → 컨트래리언
WRF_BO_FUND_HI    = _wrf_f("WRF_BO_FUND_HI", 0.80)   # 숏돌파: 펀딩 백분위 ≥ → 컨트래리언
WRF_BO_FUND_BONUS = _wrf_f("WRF_BO_FUND_BONUS", 0.15)  # 컨트래리언 시 L 가점

# ── [연결결함#1] BO 도달성: 박스권 돌파는 RANGING에서 출발 → RANGING에도 BO 허용 ──
# BO precond(돌파종가+거래량스파이크+리테스트유지★ 2봉패턴)가 이미 강게이트라
# 노이즈 위험 낮음. False 로 두면 구동작(SQUEEZE/EXPLOSIVE에서만 BO).
WRF_BO_IN_RANGING = os.getenv("WRF_BO_IN_RANGING", "true").lower() not in ("0", "false", "no", "")

# ── [연결결함#2] RV(전환) 거시 베토 면제: RV는 CHoCH+리테스트+소진을 이미 강제 ──
# (=구조붕괴 증거). 거시 정면충돌 하드베토가 전환셋업 본분을 무력화 → RV만 면제하고
# 역추세 위험은 C축(_ctx_exhaustion)·min-axis 소프트게이트로 통제(역할 분담).
WRF_RV_MACRO_EXEMPT = os.getenv("WRF_RV_MACRO_EXEMPT", "true").lower() not in ("0", "false", "no", "")

# ── [연결결함#5] TF 성숙도 배선: 성숙(late) 추세는 반전위험↑ → TF 확신 감쇠 ──
# 측정만 되고 미사용이던 maturity(연속 HH/HL)를 TF L에 연결. 1.0=감쇠없음(토글).
WRF_TF_LATE_MATURITY_MULT = _wrf_f("WRF_TF_LATE_MATURITY_MULT", 0.85)

# ── [완결성#1] 컨플루언스(FVG/OB/피보/주간 중첩) → L 가점 ──────────────────
# 측정·기록만 되고 발사엔 미반영이던 confluence를 전 셋업 L에 소폭 반영(전략의
# 다중 SMC 중첩 = 강한 진입 근거). 중첩수(0~3) × bonus. 0.0 이면 OFF(구동작).
WRF_CONFLUENCE_L_BONUS = _wrf_f("WRF_CONFLUENCE_L_BONUS", 0.05)

# ══ [grind-fix 2026-06] 느린 단일방향 추세 포착 보강 (토글 기본 OFF · 롱/숏 대칭) ══
# 진단(BTC/ETH/HYPE 06-22~23 하락): ADX 지연으로 grind-down이 내내 RANGING으로
# 고착 → 추세추종 TF가 라우팅에서 배제되고, 막판 BO 숏은 SL이 박스 반대편이라
# RR≈1 로 고착 → 전 구간 숏 신호 전무. 두 토글 모두 기본 OFF(구동작 완전 보존),
# 백테스트 대칭검증(상승 grind=롱 / 하락 grind=숏 동시 개선, 기존 발사 무악화) 후
# env(WRF_REGIME_ER_TREND / WRF_BO_SL_NEAR)로 ON. 과적합 방지: 이 사건이 통과하게
# 임계(플로어·RR)를 낮추지 않고, 측정(추세정의)·기하학(손절배치) 결함만 교정.
#
# (A) ER 추세 승격: classify_market_regime 가 효율비(ER=순이동/경로길이)로 ADX가
#     놓친 방향성 추세를 TRENDING 승격(스퀴즈·레인지 판정 이후 = 노이즈 미승격).
#     ER은 방향무관 → 상승·하락 grind를 동일하게 포착(대칭). 셀키 차원 불변.
WRF_REGIME_ER_TREND     = os.getenv("WRF_REGIME_ER_TREND", "true").lower() not in ("0", "false", "no", "")
WRF_REGIME_ER_TREND_MIN = _wrf_f("WRF_REGIME_ER_TREND_MIN", 0.50)  # 순이동/경로 ≥ → 방향성(절대모드 폴백)
# [Pillar1-①] ER 백분위화: 절대임계 0.50(전 코인 공통·알트 변동성 편향·시스템 철학 위반)
# 대신 코인 자기 ER 분포의 백분위로 승격(>=ER_PCTL_MIN). 시스템의 "절대임계 없음" 원칙과 정합.
WRF_REGIME_ER_PCTL      = os.getenv("WRF_REGIME_ER_PCTL", "true").lower() not in ("0", "false", "no", "")
WRF_REGIME_ER_PCTL_MIN  = _wrf_f("WRF_REGIME_ER_PCTL_MIN", 0.90)   # ER 자기분포 상위 10% (실데이터 튜닝: FP 통제)
WRF_REGIME_ER_PCTL_WIN  = _wrf_i("WRF_REGIME_ER_PCTL_WIN", 150)    # ER 백분위 표본 윈도(봉)
WRF_REGIME_ER_DRIFT_MIN = _wrf_f("WRF_REGIME_ER_DRIFT_MIN", 0.015) # ER 승격에도 순드리프트 동반 요구
# [Pillar1-②] 방향지속(slope persistence) 승격 — 느린 grind 포착 시도. ★실데이터 진단(2026-06,
# 323스냅샷): MA20 기울기 부호 일관성만으로는 하락 grind(sp=0.74)와 chop(sp=0.79)이 분리 안 됨
# (slow grind는 본질상 backward 통계가 chop과 닮음). → 순드리프트 magnitude 게이트를 AND로
# 추가하고 임계를 높여(0.70→0.85·drift≥0.02) FP를 통제. is_ranging '앞'에서 평가하되 보수적.
WRF_REGIME_SLOPE_PERSIST  = os.getenv("WRF_REGIME_SLOPE_PERSIST", "true").lower() not in ("0", "false", "no", "")
WRF_REGIME_SLOPE_WIN      = _wrf_i("WRF_REGIME_SLOPE_WIN", 20)     # 기울기 일관성·드리프트 윈도(봉)
WRF_REGIME_SLOPE_MIN_FRAC = _wrf_f("WRF_REGIME_SLOPE_MIN_FRAC", 0.85)  # 동방향 기울기 비율 ≥
WRF_REGIME_SLOPE_MIN_DRIFT = _wrf_f("WRF_REGIME_SLOPE_MIN_DRIFT", 0.02)  # |순드리프트|/price ≥ (chop 차단)
# [강등] ADX 단독트리거: 분기 ⑤(ADX≥REGIME_TREND_ADX 단독으로 TRENDING 승격)는 후행 EWM인 ADX가
# 움직임 끝물(소진)에 정점을 찍어 '추세' 라벨을 '반전 직전'으로 만드는 결함. 누적데이터: 그 라벨의
# 추종이 돈 비율 15%(기준 37%)·R_추종 −0.59 vs 페이드 −0.09, 특히 ADX 상승 하위는 추종 0%·페이드
# +0.76. ★기본 강등(False): 분기 ⑤ 비활성 → 효율(er_sig)이 최종판정, 미충족 시 RANGING. 확인된
# 추세(slope_sig·er_sig)는 먼저 잡혀 불변(인버전 아님·제거). 복귀(구동작): WRF_REGIME_ADX_SOLE=true.
WRF_REGIME_ADX_SOLE = os.getenv("WRF_REGIME_ADX_SOLE", "false").lower() not in ("0", "false", "no", "")
# (B) BO 손절 재배치: 박스 반대편(far, 손절=박스높이 → RR≈1 고착) → 돌파된 경계
#     (near) ∓ ATR쿠션(돌파-리테스트 무효화). RR이 박스높이/쿠션으로 정상화(>>1.5).
#     min_sl/max_sl 클램프가 과도한 타이트/와이드를 방지. TF/RV 구조SL 철학과 동일.
WRF_BO_SL_NEAR          = os.getenv("WRF_BO_SL_NEAR", "true").lower() not in ("0", "false", "no", "")
WRF_BO_SL_ATR_CUSHION   = _wrf_f("WRF_BO_SL_ATR_CUSHION", 1.0)  # 돌파경계 외곽 ATR 쿠션
# [Pillar2-③] BO near-SL의 P̂ 보정: prior P̂은 C/L/F만의 함수라 SL 거리를 모른다 → SL을
# 박스높이에서 ~1ATR로 당기면 실제 승률은 떨어지는데 P̂은 불변(win-rate floor 무력화 위험).
# r_dist/박스높이 = '타이트니스'가 REF보다 작을수록 p_hat을 소폭 깎아 기하-확률 결합을 복원.
WRF_BO_SL_TIGHT_PEN     = _wrf_f("WRF_BO_SL_TIGHT_PEN", 0.15)   # 타이트니스 p_hat 페널티 계수
WRF_BO_SL_TIGHT_REF     = _wrf_f("WRF_BO_SL_TIGHT_REF", 0.60)   # 이 비율 이상이면 무페널티

# ── btc_macro 태깅 임계 (BTC 7D/30D 추세·EMA구조) ───────────────────────
WRF_MACRO_UP_PCT   = _wrf_f("WRF_MACRO_UP_PCT", 0.03)   # 7D 변화 ±3% 이상 → leg
WRF_MACRO_CHOP_PCT = _wrf_f("WRF_MACRO_CHOP_PCT", 0.015) # |7D| < 1.5% → CHOP 후보

# ── 사이징 (페이퍼) — size ∝ P̂ ──────────────────────────────────────
WRF_SIZE_BASE = _wrf_f("WRF_SIZE_BASE", 1.0)    # P̂=floor 기준 사이즈 단위
WRF_SIZE_MAX  = _wrf_f("WRF_SIZE_MAX", 2.0)     # 사이즈 상한 단위

# ── 산출물/경로 ──────────────────────────────────────────────────────
WRF_CALIB_TABLE = os.getenv("WRF_CALIB_TABLE", "data/calibration_table.json")
WRF_SCHEMA_VERSION = 3

# ── [테제B 검증 인프라] 진입직전 캔들 윈도 저장 (precond 재실행 백테스트 가능화) ──
# 기존 오프라인 하니스는 '저장된 후보(candidates)'만 리플레이 → C/L/F·임계 재채점은
# 가능하나 precond(무장조건) 변경은 검증 불가(스냅샷에 진입시점 캔들이 없음). 이 블록은
# 백워드 1H 캔들 윈도(+ 그 시점 pct 백분위)를 스냅샷에 박아 오프라인 디텍터 재실행을
# 가능케 한다. ohlc는 p0(마지막 종가) 상대비, v는 윈도 평균 상대비(비율연산 불변·컴팩트,
# path가 빠뜨린 거래량을 보존 → 거래량 게이트까지 재현). schema_version은 불변(필드 추가·
# 하위호환). 기본 ON·env 되돌리기.
WRF_RESEARCH_BARS   = os.getenv("WRF_RESEARCH_BARS", "true").lower() not in ("0", "false", "no", "")
# 60봉이면 현재봉 지표 warmup(ATR/EMA/RSI/MACD)·box(20~26)·bb_prev(22)·rev_vol(5)를 모두
# 덮는다. 장윈도 비율(vol baseline 120)·백분위(200)는 raw·pct에 이미 저장 → 굳이 봉으로
# 복원할 필요 없음. 커밋되는 데이터라 기본은 컴팩트하게, 필요 시 env로 확장(예: 200).
WRF_RESEARCH_BARS_N = _wrf_i("WRF_RESEARCH_BARS_N", 60)   # 백워드 1H 봉 수

# 단일 버전 식별자 — 수집·측정·스냅샷 로그 배너의 유일한 출처(레거시 v3.0/v3.6 표기 폐기).
# 아키텍처는 WRF-4(Win-Rate-First, 4-Setup), 적재 스키마는 v{WRF_SCHEMA_VERSION}.
BOT_VERSION = "WRF-4"

# ══════════════════════════════════════════════════════════════════════
# [Phase 2] 계층적 부분풀링(partial pooling) 보정 — "심장을 다시 뛰게"
# ══════════════════════════════════════════════════════════════════════
# 구(舊) 보정의 자격 게이트(indep≥100 × 거시≥2종)는 데이터 누적 속도 대비
# 비현실적으로 높아 어떤 셀도 영구히 보정되지 못했다(실효≈0). 이를 폐기하고
# 계층적 random-intercept 로지스틱 + Beta-Binomial 수축으로 교체한다:
#
#   계층 GLOBAL → SETUP → BASE(setup×regime) → CELL(setup×regime×macro)
#   · prior의 기울기(wC/wL/wF)는 고정(소표본 과적합 차단) — 절편 오프셋 δ만 학습.
#   · 셀 승률을 부모로 수축(데이터 적으면 부모로 회귀, 쌓이면 자기 셀로 수렴).
#   · 수축·신뢰도 산정에 '독립표본 n'(72h 중첩 탈상관, stride=24h) 사용 — 정직.
#   · 라이브:  z = prior_logodds + δ_eff ;  P̂ = min(calib_cap, sigmoid(z)).
#             셀 없으면 prior 폴백(콜드스타트 안전·항상).
#
# 과적합 가드 5중: ①기울기 고정 ②부모 수축 ③신뢰도 가중 δ ④δ 하드캡
#                 ⑤그림자(shadow) 운영 — OOS Brier 우위 입증 전까지 발사 미반영.
WRF_CALIB_METHOD      = os.getenv("WRF_CALIB_METHOD", "partial_pooling")
WRF_CALIB_K_SETUP     = _wrf_f("WRF_CALIB_K_SETUP", 40.0)  # SETUP 수축 의사관측수
WRF_CALIB_K_BASE      = _wrf_f("WRF_CALIB_K_BASE", 30.0)   # BASE 수축 의사관측수
WRF_CALIB_K_CELL      = _wrf_f("WRF_CALIB_K_CELL", 25.0)   # CELL 수축 의사관측수
WRF_CALIB_K_CONF      = _wrf_f("WRF_CALIB_K_CONF", 20.0)   # δ 신뢰도 가중 의사관측수
WRF_CALIB_MIN_DECIDED = _wrf_i("WRF_CALIB_MIN_DECIDED", 3) # 보정셀 생성 최소 결판수
WRF_CALIB_DELTA_CAP   = _wrf_f("WRF_CALIB_DELTA_CAP", 1.2) # |δ_eff| 로그오즈 하드캡
WRF_CALIB_CAP         = _wrf_f("WRF_CALIB_CAP", 0.72)      # 보정 P̂ 상한(근거기반, prior 0.65↑)

# ══════════════════════════════════════════════════════════════════════
# [Phase A] 발사권(fire-rights) 게이트 + 섀도 셋업 — ex-post 플로어 폐루프
# ══════════════════════════════════════════════════════════════════════
# 목적함수 max N s.t. WR≥floor 의 제약이 ex-ante(P̂)로만 존재하고 실현 승률로
# 강제되지 않던 결함(폐루프 부재)을 메운다. 주간 오프라인 잡(calibrate.py)이
# 셀별 '발사 ∪ 격리-미발사' 결판(WIN/LOSS — 제약은 발사분 승률에 대한 것이라
# floor가 거부한 후보는 제외)의 Beta-Binomial 사후분포로 P(WR ≥ floor)를 계산해
# fire_rights ∈ {live, shadow} 를 테이블에 발행 — 라이브는 읽기만(5-B 무손상).
#   · 강등: P(WR≥floor) < DEMOTE_P ∧ 결판 ≥ MIN_DECIDED (셀이 플로어 미달로 판명)
#   · 복권: 강등 셀은 P(WR≥floor) ≥ PROMOTE_P 회복 시 live (히스테리시스 —
#     비대칭 손실 반영: 오발사=실손 R 영구, 오강등=기회비용 일시+섀도로 데이터
#     계속 쌓여 자동 복권). 예측 파라미터 학습 없음(발사권 박탈/복권만) — 과적합 무관.
# 강등 후보는 quarantine 태그로 기록만 되고 발사 안 됨(전량 기록·채점은 계속).
WRF_FIRE_RIGHTS_ENABLED = os.getenv("WRF_FIRE_RIGHTS_ENABLED", "true").lower() not in ("0", "false", "no", "")
WRF_FR_PRIOR_N     = _wrf_f("WRF_FR_PRIOR_N", 10.0)     # floor 중심 중립 prior 의사관측수
WRF_FR_DEMOTE_P    = _wrf_f("WRF_FR_DEMOTE_P", 0.15)    # 강등: P(WR≥floor) < 이 값
WRF_FR_PROMOTE_P   = _wrf_f("WRF_FR_PROMOTE_P", 0.50)   # 복권: P(WR≥floor) ≥ 이 값
WRF_FR_MIN_DECIDED = _wrf_i("WRF_FR_MIN_DECIDED", 8)    # 강등 최소 결판수(소표본 오강등 방지)

# ── 섀도 셋업: 라이브 발사권이 없는 셋업(기록·채점만) ─────────────────────
# [Phase A] BR(밴드반전)은 검증 없는 점등(5-I 위반)으로 라이브에 승격됐다가 실측 승률
# 미달(결판 15건 승률 40% < floor 0.58)로 섀도 원상복귀. 재점등은 발사권 게이트 통과 +
# 사람 심사 후 이 목록에서 제거(env WRF_SHADOW_SETUPS=""=전부 라이브 → 구동작 복귀).
WRF_SHADOW_SETUPS = {s.strip() for s in os.getenv("WRF_SHADOW_SETUPS", "BR").split(",") if s.strip()}

# ── 보정 발사 스위치(그림자 운영) ────────────────────────────────────────
# true(기본): 라이브는 prior로 '발사', 보정 P̂은 계산·기록만(A/B 그림자).
#   → backtest.py --ab 로 OOS(시간분할+72h embargo) Brier/승률 우위가 입증되면
# false 로 전환 → 보정 P̂으로 '발사'(셀 없으면 prior 폴백). 이것이 Phase 2 Gate-Out.
# (보정 계산·기록은 스위치와 무관하게 항상 수행 — 그림자 평가용.)
WRF_CALIB_DISABLED = os.getenv("WRF_CALIB_DISABLED", "true").lower() not in ("0", "false", "no", "")

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
