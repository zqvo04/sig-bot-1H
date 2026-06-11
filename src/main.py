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

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    try:
        log_path = os.path.join(log_dir, 'bot.log')
        fh = logging.FileHandler(log_path, encoding='utf-8')
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass

    return logging.getLogger("main")


# ══════════════════════════════════════════════
# 실행 카운터
# ══════════════════════════════════════════════

_COUNTER_FILE = "/tmp/bot_state/bot_run_counter.json"

def _load_counter() -> dict:
    try:
        if os.path.exists(_COUNTER_FILE):
            with open(_COUNTER_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {"runs": 0, "signals": 0}


def _save_counter(data: dict) -> None:
    try:
        with open(_COUNTER_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


# ══════════════════════════════════════════════
# 메인 실행
# ══════════════════════════════════════════════

def main():
    logger = setup_logging()
    start_time = datetime.now(timezone.utc)

    single_symbol = os.getenv("SINGLE_SYMBOL")
    if not single_symbol:
        logger.error("❌ SINGLE_SYMBOL 환경변수 없음")
        sys.exit(1)

    logger.info("=" * 55)
    logger.info(f"🕐 1H봇 실행 시작 — {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    logger.info(f"   심볼: {single_symbol} (Matrix Job)")
    logger.info(f"   봉 주기: 1h | 타임프레임: 1h/4h/1d")
    logger.info("=" * 55)

    counter = _load_counter()
    counter["runs"] += 1
    run_num = counter["runs"]

    try:
        exchange = create_exchange()
    except Exception as e:
        msg = f"[1H봇] OKX 클라이언트 생성 실패: {e}"
        logger.critical(msg)
        send_error_alert(msg, context="create_exchange()")
        sys.exit(1)

    result = {
        "symbol":    single_symbol,
        "success":   False,
        "notified":  False,
        "direction": None,
        "score":     0.0,
        "error":     None,
    }

    try:
        logger.info(f"\n{'─'*50}")
        logger.info(f"🔄 처리 중: {single_symbol}")
        logger.info(f"{'─'*50}\n")

        # 1. 데이터 수집
        collected = collect_all_data(exchange, single_symbol)

        if not collected.get("ticker", {}).get("available", False):
            logger.warning(f"[{single_symbol}] 티커 수집 실패 (available=False) — 스킵")
            result["error"] = "티커 수집 실패"
        else:
            # 2. 기술적 분석
            analysis = run_full_analysis(single_symbol, collected)

            # 3. 점수 산출 (market_data 전달 → 마이크로구조 계산 활성화)
            pipeline = run_scoring_pipeline(
                single_symbol, analysis,
                market_data=collected   # ← 마이크로구조 패널티 계산용
            )
            result["score"]     = pipeline["score"]
            result["direction"] = pipeline["direction"]
            result["success"]   = True

            # [v2.0] 컨텍스트 로그
            regime_4h   = pipeline.get("regime_4h",   {})
            daily_bias  = pipeline.get("daily_bias",   {})
            regime_1h   = pipeline.get("regime",       {})
            logger.info(
                f"[{single_symbol}] 컨텍스트: "
                f"4h={regime_4h.get('regime','?')} × 1h={regime_1h.get('regime','?')} | "
                f"일봉바이어스={daily_bias.get('bias','?')}"
            )

            # 3.4 [학습] Research Logger — 상태 스냅샷 + 사후 결과 (신호와 독립)
            #   · git JSONL: 풀 피처 + 72h 전체 경로 (research_logger)
            #   · Notion DB: 같은 스냅샷 + 핵심 결과 라벨 미러 (notion_research)
            if research_logger.enabled() or notion_research.enabled():
                _df_1h_r = collected.get("ohlcv", {}).get("1h")
                _state = None
                try:
                    _state = research_logger.build_state(
                        single_symbol, analysis, pipeline, collected
                    )
                except Exception as e:
                    logger.warning(f"[{single_symbol}] Research 상태 빌드 오류: {e}")
                if _state is not None and research_logger.enabled():
                    try:
                        research_logger.record_snapshot(_state)
                        research_logger.capture_paths(single_symbol, _df_1h_r)
                    except Exception as e:
                        logger.warning(f"[{single_symbol}] Research 로거 오류: {e}")
                if notion_research.enabled():
                    try:
                        if _state is not None:
                            notion_research.log_snapshot(_state)
                        notion_research.update_outcomes(single_symbol, _df_1h_r)
                    except Exception as e:
                        logger.warning(f"[{single_symbol}] Notion Research 오류: {e}")

            # 3.5 [v4.0] Notion — 기존