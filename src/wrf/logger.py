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


def _find_row(path: str, sid: str) -> dict | None:
    """snapshot_id로 기존 행 조회(회계 누수 수리 판정용). 없으면 None."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("snapshot_id") == sid:
                    return r
    except Exception as e:  # pragma: no cover
        logger.warning(f"[wrf.logger] 행 조회 실패: {e}")
    return None


def _replace_row(path: str, sid: str, new_row: dict) -> None:
    """snapshot_id 행을 new_row로 교체하고 파일을 원자적 재기록(temp+rename)."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            try:
                r = json.loads(s)
            except json.JSONDecodeError:
                out.append(s)
                continue
            out.append(json.dumps(new_row, ensure_ascii=False)
                       if r.get("snapshot_id") == sid else s)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    os.replace(tmp, path)


def record_snapshot(row: dict) -> bool:
    """schema v3 행을 월별 JSONL에 멱등 append.

    [회계 누수 수리] 멱등키(snapshot_id) 선점 시 무조건 skip하던 규칙이, 같은 봉의
    이른 실행이 후보 0으로 행을 먼저 쓰면(데이터 미정착) 후보를 생성한 재실행을
    영구 skip시켜 '발사했는데 JSONL만 빈 행'을 남겼다(라이브 26건 중 5건 — fire-rights·
    보정이 읽는 원장이 현실보다 관대해짐). 수리: 기존 행의 path가 아직 null(=같은 시각
    재실행 창)이고 새 행이 후보가 더 많으면 교체한다(결정적·전략무관). path가 형성된
    행은 절대 훼손하지 않는다(성숙 데이터 보호)."""
    if not enabled():
        return False
    ts = pd.Timestamp(row["ts"])
    path = research_logger._month_file(row["symbol"], ts)
    existing = _find_row(path, row["snapshot_id"])
    if existing is not None:
        if (existing.get("path") is None
                and len(row.get("candidates", [])) > len(existing.get("candidates", []))):
            _replace_row(path, row["snapshot_id"], row)
            logger.info(f"[wrf.logger] 🔧 빈-후보 행 교체(회계 누수 수리) {row['snapshot_id']}: "
                        f"{len(existing.get('candidates', []))}→{len(row.get('candidates', []))}후보")
            return True
        logger.debug(f"[wrf.logger] 중복 스냅샷 skip: {row['snapshot_id']}")
        return False
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    n_fire = sum(1 for c in row.get("candidates", []) if c.get("fire"))
    logger.info(
        f"[wrf.logger] 📸 스냅샷 v{getattr(config, 'WRF_SCHEMA_VERSION', 3)} {row['symbol']} @ {row['ts']} "
        f"({row['ctx']['fp_key']}) 후보 {len(row.get('candidates', []))}개 발사 {n_fire}개")
    return True


_DECISION_STATES = {"ENGINE_APPROVED", "ENGINE_REJECTED", "SUPPRESSED_OPEN", "LEDGER_CREATED", "LEDGER_WRITE_FAILED", "CLOSED"}


def _decision_ledger_file(symbol: str, ts: str) -> str:
    """Monthly, symbol-partitioned append-only decision state ledger."""
    stamp = pd.Timestamp(ts)
    base = getattr(config, "WRF_DECISION_LEDGER_DIR", "data/decision_ledger")
    slug = symbol.replace("/", "-").replace(":", "-")
    out_dir = os.path.join(base, slug)
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{stamp.strftime('%Y-%m')}.jsonl")


def _event_exists(path: str, decision_id: str, state: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("decision_id") == decision_id and row.get("state") == state:
                    return True
    except OSError:
        return False
    return False


def record_decision_event(plan: dict, state: str, reason: str = "", extra: dict | None = None) -> bool:
    """Record one idempotent state transition for a canonical execution plan.

    This ledger is intentionally independent of Notion. A Notion outage can no
    longer erase whether engine approval was suppressed, written, or closed.
    """
    if state not in _DECISION_STATES or not isinstance(plan, dict):
        return False
    decision_id = plan.get("decision_id")
    ts = plan.get("decision_ts")
    symbol = plan.get("symbol")
    if not decision_id or not ts or not symbol:
        return False
    try:
        path = _decision_ledger_file(str(symbol), str(ts))
        if _event_exists(path, str(decision_id), state):
            return False
        event = {
            "decision_id": decision_id,
            "state": state,
            "event_ts": pd.Timestamp.now(tz=timezone.utc).isoformat(),
            "reason": reason,
            "execution_plan": plan,
        }
        if extra:
            event["extra"] = extra
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return True
    except Exception as e:  # pragma: no cover
        logger.warning(f"[wrf.logger] decision event 기록 실패 {state}: {e}")
        return False


def capture_paths(symbol: str, df_1h: "pd.DataFrame") -> int:
    """성숙 행의 72h 경로 증분 캡처(스키마 무관 머신 재사용)."""
    if not enabled():
        return 0
    try:
        return research_logger.capture_paths(symbol, df_1h)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[wrf.logger] 경로 캡처 실패: {e}")
        return 0


def capture_execution_paths(symbol: str, df_5m: "pd.DataFrame") -> int:
    """Capture candidate-specific 5m paths from the immutable entry timestamp."""
    if not enabled():
        return 0
    try:
        return research_logger.capture_execution_paths(symbol, df_5m)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[wrf.logger] canonical execution path 캡처 실패: {e}")
        return 0


def load_decision_plan(symbol: str, decision_ts: str, decision_id: str) -> dict | None:
    """Load the immutable plan from its original append-only decision event."""
    try:
        path = _decision_ledger_file(symbol, decision_ts)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("decision_id") == decision_id:
                    plan = event.get("execution_plan")
                    if isinstance(plan, dict):
                        return plan
    except Exception as e:  # pragma: no cover
        logger.warning(f"[wrf.logger] decision plan 조회 실패: {e}")
    return None
