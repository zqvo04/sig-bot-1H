#!/usr/bin/env python3
"""Notion 전면 초기화 + WRF 2-DB 생성/마이그레이션.

기존 DB(신호로그·리서치 스냅샷)의 모든 행을 아카이브(삭제)하고, WRF Signals /
WRF Snapshots 2개 DB를 새로 생성(또는 기존 동명 DB 재사용)한다. 생성된 DB ID를
출력하니 NOTION_SIGNALS_DB_ID / NOTION_SNAPSHOTS_DB_ID 시크릿으로 등록하면 된다.

NOTION_TOKEN 미설정 시 자동 no-op. 파괴적 작업이므로 --purge 플래그 필수.

사용:
  python scripts/migrate_notion_wrf.py            # 새 2-DB 생성/확인만
  python scripts/migrate_notion_wrf.py --purge    # 기존 DB 데이터까지 전부 삭제
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
from notion_logger import _request  # noqa: E402
from wrf import notion_wrf  # noqa: E402


def purge_db(db_id: str, label: str) -> int:
    """DB의 모든 페이지를 아카이브(삭제). 반환: 삭제 건수."""
    if not db_id:
        print(f"  · {label}: DB ID 없음 — 건너뜀")
        return 0
    total = 0
    cursor = None
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
    ap = argparse.ArgumentParser(description="Notion 전면 초기화 + WRF 2-DB")
    ap.add_argument("--purge", action="store_true", help="기존 DB 데이터 전부 삭제")
    args = ap.parse_args()

    if not notion_wrf.enabled():
        print("NOTION_TOKEN 미설정 — no-op. (Secrets 등록 후 재실행)")
        return

    if args.purge:
        print("⚠️  기존 Notion DB 데이터 전부 삭제(아카이브):")
        purge_db(getattr(config, "NOTION_DATABASE_ID", ""), "레거시 1H Signal Log")
        purge_db(getattr(config, "NOTION_RESEARCH_DB_ID", ""), "레거시 Research Snapshots")
        purge_db(getattr(config, "NOTION_SIGNALS_DB_ID", ""), "WRF Signals(기존)")
        purge_db(getattr(config, "NOTION_SNAPSHOTS_DB_ID", ""), "WRF Snapshots(기존)")
    else:
        print("ℹ️  --purge 미지정 → 기존 데이터는 보존. 새 DB만 확인/생성.")

    print("\nWRF 2-DB 생성/확인:")
    sig = notion_wrf.ensure_signals_db()
    snap = notion_wrf.ensure_snapshots_db()
    print(f"  · WRF Signals    DB ID = {sig}")
    print(f"  · WRF Snapshots  DB ID = {snap}")
    print("\n다음 값을 GitHub Secrets에 등록:")
    print(f"  NOTION_SIGNALS_DB_ID   = {sig}")
    print(f"  NOTION_SNAPSHOTS_DB_ID = {snap}")


if __name__ == "__main__":
    main()
