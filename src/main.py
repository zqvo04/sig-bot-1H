"""
main.py — 1h Bot v2.0  (Matrix 전략 연동)
각 Job은 단일 심볼만 처리 (GitHub Actions가 병렬화)

[1h Bot 변경]
  - 로그/알림에 "1H봇" 명시 → 15m봇과 구분
  - run_scoring_pipeline에 market_data 전달 (마이크로구조 계산)
  - regime_4h, daily_bias 로그 표시

[Cron: 매시 5분]
  5 * * * *
  1h 봉 마감(:00) → 5분 대기 → GHA 실행 (~:06-08)
  캔들 마감 후 총 지연: ~6-10분 (봉 길이 대비 10~17%)
"""

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import config
from data_pipeline   import create_exchange, collect_all_data
from analysis_engine import run_full_analysis
from scoring_system  import run_scoring_pipeline
from notification    import notify_signal, send_error_alert
import notion_logger
import research_logger
import notion_research


# ══════════════════════════════════════════════
# 로깅 초기화
# ══════════════════════════════════════════════

def setup_logging() -> logging.Logger:
    log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
    os.makedirs(log_dir, exist_ok=True)