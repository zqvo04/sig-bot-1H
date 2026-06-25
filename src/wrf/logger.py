"""schema v3 학습데이터 로거 — 무상태·멱등·git 친화.

매시간 1행을 data/research/{SYM}/{YYYY-MM}.jsonl 에 append(멱등키=snapshot_id).
경로 캡처(증분·72h 완성)는 research_logger의 스키마 무관 머신을 재사용한다.
라벨은 박제하지 않는다 — 경로에서 오프라인 파생(analysis/build_dataset).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import timezone

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import config
    import research_logger
except ImportError:  # pragma: no cover
    from src import config, research_logger  # type: ignore


def enabled() -> bool:
    if not getattr(config, "RESEARCH_LOGGER_ENABLED", True):
        return False
    return os.getenv("RESEARCH_LOGGER_ENABLED", "1") not in ("0", "false", "False")


def _existing_ids(path: str) -> set:
    ids = set()
    if not os.path.exists(path):
        return ids
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        ids.add(json.loads(line).get("snapshot_id"))
                    except json.JSONDecodeError:
                        continue
    except Exception as e:  # pragma: no cover
        logger.warning(f"[wrf.logger] 기존 id 스캔 실패: {e}")
    return ids


def record_snapshot(row: dict) -> bool:
    """schema v3 행을 월별 JSONL에 멱등 append."""
    if not enabled():
        return False
    ts = pd.Timestamp(row["ts"])
    path = research_logger._month_file(row["symbol"], ts)
    if row["snapshot_id"] in _existing_ids(path):
        logger.debug(f"[wrf.logger] 중복 스냅샷 skip: {row['snapshot_id']}")
        return False
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    n_fire = sum(1 for c in row.get("candidates", []) if c.get("fire"))
    logger.info(
        f"[wrf.logger] 📸 v3 스냅샷 {row['symbol']} @ {row['ts']} "
        f"({row['ctx']['fp_key']}) 후보 {len(row.get('candidates', []))}개 발사 {n_fire}개")
    return True


def recent_shadow_dirs(symbol: str, ts, cooldown_h: float) -> set:
    """직전 cooldown_h 시간 내 '로그된'(shadow_logged=True) D-shadow 신호의 방향 집합.

    심볼+방향 쿨다운(중복 억제)의 상태원(state)이다 — JSONL이 이 봇의 유일한 영속
    상태이므로 별도 파일 없이 여기서 읽는다. JSONL 미존재/비활성이면 빈 집합(쿨다운
    무효=degrade gracefully). 월경계는 현재월+직전월 파일을 함께 본다."""
    dirs: set = set()
    try:
        if cooldown_h is None or float(cooldown_h) <= 0:
            return dirs
        t = pd.Timestamp(ts)
        cutoff = t - pd.Timedelta(hours=float(cooldown_h))
        paths = {research_logger._month_file(symbol, t),
                 research_logger._month_file(symbol, cutoff)}  # 월경계 대비
        for path in paths:
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                        rts = pd.Timestamp(r.get("ts"))
                    except Exception:
                        continue
                    if rts < cutoff or rts >= t:
                        continue
                    for c in r.get("candidates", []):
                        if c.get("shadow_logged"):
                            dirs.add(c.get("dir"))
    except Exception as e:  # pragma: no cover
        logger.warning(f"[wrf.logger] recent_shadow_dirs 실패(격리): {e}")
    return dirs


def capture_paths(symbol: str, df_1h: "pd.DataFrame") -> int:
    """성숙 행의 72h 경로 증분 캡처(스키마 무관 머신 재사용)."""
    if not enabled():
        return 0
    try:
        return research_logger.capture_paths(symbol, df_1h)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[wrf.logger] 경로 캡처 실패: {e}")
        return 0
