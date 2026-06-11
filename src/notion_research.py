"""
notion_research.py — 학습 스냅샷 Notion DB 기록 + 사후 결과(차트 움직임) 자동 기입
────────────────────────────────────────────────────────────────────
research_logger(상태 중심 학습 데이터)의 Notion 미러.
매시 실행마다:
  ① log_snapshot(state)      — L1 원시피처 + L2 지문 + L3 참고메타를 1행 생성 (Outcome=PENDING)
  ② update_outcomes(sym,df)  — 봉시각+72h 지난 PENDING 행에 차트 움직임 라벨 기입 (Outcome=DONE)
       · Ret 4/12/24/48/72h (%) · MFE/MAE 72h (%) · ATR 정규화 수익률
       · Class 24/72h (UP/DOWN/FLAT, 데드존 0.25×ATR%) · 고점/저점 도달시간 · 경로효율

원시 72h 경로 전체는 git JSONL(research_logger)이 보관하고,
Notion에는 사람이 필터·그룹으로 바로 보는 핵심 라벨만 기입한다.

DB: "1H Research Snapshots" (🧪 1H 학습 데이터 페이지 하위)
NOTION_TOKEN 미설정 시 전 기능 비활성(no-op).
"""
import logging
from datetime import datetime, timezone, timedelta

import pandas as pd
import config
from notion_logger import (
    _request, _p_num, _p_sel, _p_txt, _p_title, _p_date,
    _get_num, _get_sel,
)

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(config.NOTION_ENABLED and config.NOTION_TOKEN
                and getattr(config, "NOTION_RESEARCH_ENABLED", True))


def _p_chk(v):
    return {"checkbox": bool(v)}


# ════════════════════════════════════════════════════════════════════
# DB 확보 — 접근 검증 → 검색 → 자동 생성 (셀프 힐링)
# ════════════════════════════════════════════════════════════════════