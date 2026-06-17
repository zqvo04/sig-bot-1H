#!/usr/bin/env python3
"""Notion WRF 양식 마이그레이션 — 기존 DB 재사용.

기존 DB("1H Signal Log" / "1H Research Snapshots")를 WRF 양식으로 개조해 재사용한다.
일회성 컬럼 리네임(Result→Status, Take Profit→TP, RSI 1H→RSI 등)은 Notion UI 또는
MCP로 이미 적용돼 있다고 가정하고, 이 스크립트는 REST로 **누락된 WRF 컬럼만 멱등 추가**한다
(데이터 보존). NOTION_TOKEN 미설정 시 자동 no-op.

사용:
  python scripts/migrate_notion_wrf.py             # 누락 WRF 컬럼 추가(스키마 동기화)
  python scripts/migrate_notion_wrf.py --purge     # 추가 + 기존 행 전부 아카이브(삭제)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
from notion_logger import _request  # noqa: E402
from wrf import notion_wrf  # noqa: E402


def _existing_props(db_id: str) -> set:
    res = _request("GET", f"/databases/{db_id}")
    if not res:
        return set()
    return set((res.get("properties") or {}).keys())


def sync_schema(db_id: str, props: dict, label: str) -> int:
    """누락된 WRF 프로퍼티만 멱등 추가(PATCH). 반환: 추가 컬럼 수."""
    if not db_id:
        print(f"  · {label}: DB ID 없음 — 건너뜀")
        return 0
    have = _existing_props(db_id)
    missing = {k: v for k, v in props.items() if k not in have}
    if not missing:
        print(f"  · {label} ({db_id}): 이미 최신 — 추가 없음")
        return 0
    r = _request("PATCH", f"/databases/{db_id}", {"properties": missing})
    if r:
        print(f"  · {label} ({db_id}): {len(missing)}개 컬럼 추가 → {sorted(missing)}")
        return len(missing)
    print(f"  · {label} ({db_id}): 추가 실패")
    return 0


def purge_db(db_id: str, label: str) -> int:
    """DB의 모든 페이지를 아카이브(삭제). 반환: 삭제 건수."""
    if not db_id:
        return 0
    total, cursor = 0, None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = _request("POST", f"/databases/{db_id}/query", payload)
        if not res:
            break
        for page in res.get("results", []):
            if _request("PATCH", f"/pages/{page['id']}", {"archived": True}):
                total += 1
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    print(f"  · {label} ({db_id}): {total}행 아카이브")
    return total


def main():
    ap = argparse.ArgumentParser(description="Notion WRF 양식 마이그레이션(기존 DB 재사용)")
    ap.add_argument("--purge", action="store_true", help="기존 행 전부 아카이브(삭제)")
    args = ap.parse_args()

    if not notion_wrf.enabled():
        print("NOTION_TOKEN 미설정 — no-op. (Secrets 등록 후 재실행)")
        return

    sig = notion_wrf.ensure_signals_db()
    snap = notion_wrf.ensure_snapshots_db()

    print("WRF 양식 스키마 동기화(누락 컬럼만 추가):")
    sync_schema(sig, notion_wrf.SIGNALS_PROPS, config.NOTION_SIGNALS_DB_TITLE)
    sync_schema(snap, notion_wrf._snapshots_props(), config.NOTION_SNAPSHOTS_DB_TITLE)

    if args.purge:
        print("\n⚠️  기존 행 전부 아카이브(삭제):")
        purge_db(sig, config.NOTION_SIGNALS_DB_TITLE)
        purge_db(snap, config.NOTION_SNAPSHOTS_DB_TITLE)

    print("\n완료. 사용 DB ID:")
    print(f"  NOTION_SIGNALS_DB_ID   = {sig}")
    print(f"  NOTION_SNAPSHOTS_DB_ID = {snap}")
    print("일회성 컬럼 리네임(Result→Status 등)은 Notion UI/MCP에서 적용(데이터 보존).")


if __name__ == "__main__":
    main()
