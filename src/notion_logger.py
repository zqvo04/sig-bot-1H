"""
notion_logger.py — Notion 신호 기록 & 성공/실패 자동 평가 (1h Bot v4.0)
────────────────────────────────────────────────────────────────────
역할:
  ① log_signal()           — 신호 발생 시 Notion DB에 한 행(Row) 생성 (Result=OPEN)
  ② evaluate_open_signals() — 매 실행마다 OPEN 신호를 1H 캔들로 점검 → WIN/LOSS 자동 판정

판정 규칙 (스윙, 최대 EVAL_MAX_HOLD_HOURS 보유):
  · LONG  : 캔들 저가 ≤ SL → LOSS / 고가 ≥ TP → WIN
  · SHORT : 캔들 고가 ≥ SL → LOSS / 저가 ≤ TP → WIN
  · 한 캔들 내 동시 터치 → SL 우선(보수적, EVAL_SL_PRIORITY)
  · 미체결 + 보유시간 초과 → 시장가 청산 손익부호로 WIN/LOSS (EXPIRED_*)

연결:
  Notion 내부 통합(Integration) 토큰 + DB ID 필요.
  NOTION_TOKEN 미설정 시 전 기능 비활성(no-op) — 봇 본체는 정상 동작.

REST 직접 호출(requests) — GitHub Actions/헤드리스 환경에서 MCP 없이 동작.
"""
import logging
from datetime import datetime, timezone, timedelta

import requests

import config

logger = logging.getLogger(__name__)

_API = "https://api.notion.com/v1"
_TIMEOUT = 15
_db_id_cache = None   # 자동 생성/탐색된 DB ID 캐시 (런 내)


# ════════════════════════════════════════════════════════════════════
# 공통 HTTP
# ════════════════════════════════════════════════════════════════════

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.NOTION_TOKEN}",
        "Notion-Version": config.NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, payload: dict = None, retries: int = 3):
    url = f"{_API}{path}"
    for attempt in range(1, retries + 1):
        try:
            r = requests.request(method, url, json=payload, headers=_headers(), timeout=_TIMEOUT)
            if r.status_code in (200, 201):
                return r.json()
            if r.status_code == 429:
                import time as _t
                _t.sleep(int(r.headers.get("Retry-After", 3)))
                continue
            logger.warning(f"[Notion] {method} {path} → {r.status_code}: {r.text[:200]}")
            return None
        except Exception as e:
            logger.warning(f"[Notion] {method} {path} 오류({attempt}/{retries}): {e}")
            import time as _t
            _t.sleep(2 * attempt)
    return None


def enabled() -> bool:
    return bool(config.NOTION_ENABLED and config.NOTION_TOKEN)


# ════════════════════════════════════════════════════════════════════
# DB 확보 (ID 지정 우선 → 부모 페이지 하위 탐색/자동 생성)
# ════════════════════════════════════════════════════════════════════

_DB_PROPERTIES = {
    "Name":        {"title": {}},
    "Result":      {"select": {"options": [
        {"name": "OPEN", "color": "gray"}, {"name": "WIN", "color": "green"}, {"name": "LOSS", "color": "red"}]}},
    "Symbol":      {"select": {"options": [
        {"name": "BTC/USDT", "color": "orange"}, {"name": "ETH/USDT", "color": "blue"}, {"name": "HYPE/USDT", "color": "purple"}]}},
    "Direction":   {"select": {"options": [{"name": "LONG", "color": "green"}, {"name": "SHORT", "color": "red"}]}},
    "Grade":       {"select": {"options": [
        {"name": "STRONG", "color": "red"}, {"name": "GOOD", "color": "orange"}, {"name": "WATCH", "color": "yellow"}]}},
    "Score":       {"number": {}},
    "Threshold":   {"number": {}},
    "Regime 1H":   {"select": {"options": [
        {"name": n, "color": c} for n, c in [("TRENDING", "green"), ("EXPLOSIVE", "red"), ("RANGING", "gray"), ("SQUEEZE", "yellow"), ("UNKNOWN", "default")]]}},
    "Regime 4H":   {"select": {"options": [
        {"name": n, "color": c} for n, c in [("TRENDING", "green"), ("EXPLOSIVE", "red"), ("RANGING", "gray"), ("SQUEEZE", "yellow"), ("UNKNOWN", "default")]]}},
    "Entry":       {"number": {}},
    "Stop Loss":   {"number": {}},
    "Take Profit": {"number": {}},
    "Exit Price":  {"number": {}},
    "R Multiple":  {"number": {}},
    "ATR %":       {"number": {}},
    "Entry Time":    {"date": {}},
    "Resolved Time": {"date": {}},
    "Hold (h)":    {"number": {}},
    "Exit Reason": {"select": {"options": [
        {"name": n, "color": c} for n, c in [("TP_HIT", "green"), ("SL_HIT", "red"), ("EXPIRED_WIN", "blue"), ("EXPIRED_LOSS", "brown"), ("OPEN", "gray")]]}},
    "Reasons":     {"rich_text": {}},
    "Signal ID":   {"rich_text": {}},
}


def _ensure_database():
    """사용할 DB ID 반환. 없으면 부모 페이지 하위에 탐색/생성."""
    global _db_id_cache
    if _db_id_cache:
        return _db_id_cache
    if config.NOTION_DATABASE_ID:
        _db_id_cache = config.NOTION_DATABASE_ID
        return _db_id_cache

    parent = config.NOTION_PARENT_PAGE_ID
    if not parent:
        logger.warning("[Notion] NOTION_DATABASE_ID / NOTION_PARENT_PAGE_ID 둘 다 없음 → 비활성")
        return None

    # 부모 페이지 하위에 동일 제목 DB가 있으면 재사용
    res = _request("POST", "/search", {
        "query": config.NOTION_DB_TITLE,
        "filter": {"property": "object", "value": "database"},
    })
    if res:
        for obj in res.get("results", []):
            title = "".join(t.get("plain_text", "") for t in obj.get("title", []))
            if title.strip() == config.NOTION_DB_TITLE:
                _db_id_cache = obj["id"]
                logger.info(f"[Notion] 기존 DB 재사용: {_db_id_cache}")
                return _db_id_cache

    # 생성
    created = _request("POST", "/databases", {
        "parent": {"type": "page_id", "page_id": parent},
        "title": [{"type": "text", "text": {"content": config.NOTION_DB_TITLE}}],
        "properties": _DB_PROPERTIES,
    })
    if created and created.get("id"):
        _db_id_cache = created["id"]
        logger.info(f"[Notion] 신규 DB 생성: {_db_id_cache}")
        return _db_id_cache
    logger.warning("[Notion] DB 생성 실패")
    return None


# ════════════════════════════════════════════════════════════════════
# 프로퍼티 빌더 / 파서
# ════════════════════════════════════════════════════════════════════

def _p_num(v):    return {"number": (round(float(v), 6) if v is not None else None)}
def _p_sel(v):    return {"select": ({"name": str(v)} if v else None)}
def _p_txt(v):    return {"rich_text": [{"type": "text", "text": {"content": str(v)[:1900]}}]} if v else {"rich_text": []}
def _p_title(v):  return {"title": [{"type": "text", "text": {"content": str(v)[:1900]}}]}
def _p_date(iso): return {"date": ({"start": iso} if iso else None)}


def _get_num(props, key):
    try: return props.get(key, {}).get("number")
    except Exception: return None

def _get_sel(props, key):
    try:
        s = props.get(key, {}).get("select")
        return s.get("name") if s else None
    except Exception: return None

def _get_date(props, key):
    try:
        d = props.get(key, {}).get("date")
        return d.get("start") if d else None
    except Exception: return None

def _get_txt(props, key):
    try: return "".join(t.get("plain_text", "") for t in props.get(key, {}).get("rich_text", []))
    except Exception: return ""


# ════════════════════════════════════════════════════════════════════
# ① 신호 기록
# ════════════════════════════════════════════════════════════════════

def _has_open_signal(db_id: str, symbol: str, direction: str) -> bool:
    """같은 심볼·방향의 OPEN 신호가 이미 있으면 중복 기록 방지."""
    res = _request("POST", f"/databases/{db_id}/query", {
        "filter": {"and": [
            {"property": "Result", "select": {"equals": "OPEN"}},
            {"property": "Symbol", "select": {"equals": symbol}},
            {"property": "Direction", "select": {"equals": direction.upper()}},
        ]},
        "page_size": 1,
    })
    return bool(res and res.get("results"))


def log_signal(pipeline: dict, analysis: dict, levels: dict) -> bool:
    """신호 발생 시 Notion에 OPEN 행 기록. 성공 시 True."""
    if not enabled():
        return False
    db_id = _ensure_database()
    if not db_id:
        return False

    symbol    = pipeline["symbol"]
    direction = (pipeline["direction"] or "").upper()
    score     = float(pipeline.get("score") or 0.0)
    side      = pipeline["signal_result"][pipeline["direction"]]
    thr       = float(side.get("regime_threshold") or 0.0)
    r1h       = pipeline.get("regime", {}).get("regime", "UNKNOWN")
    r4h       = pipeline.get("regime_4h", {}).get("regime", "UNKNOWN")

    if _has_open_signal(db_id, symbol, direction):
        logger.info(f"[Notion] {symbol} {direction} 이미 OPEN 신호 존재 → 기록 생략")
        return False

    now = datetime.now(timezone.utc)
    entry_iso = now.isoformat()
    signal_id = f"{symbol}|{direction}|{now.strftime('%Y%m%dT%H')}"

    # 판단 근거 요약 (보너스 상위 + 등급)
    bonuses = side.get("bonuses", []) or []
    top_b = sorted(bonuses, key=lambda x: -x[1])[:5]
    reason = f"{levels.get('grade','?')} · " + ", ".join(f"{n}+{v}" for n, v in top_b)

    name = (f"{symbol} {direction} · {now.astimezone(timezone(timedelta(hours=9))).strftime('%m-%d %H:%M')}KST "
            f"· {score:.0f}pt")

    props = {
        "Name":        _p_title(name),
        "Result":      _p_sel("OPEN"),
        "Symbol":      _p_sel(symbol),
        "Direction":   _p_sel(direction),
        "Grade":       _p_sel(levels.get("grade")),
        "Score":       _p_num(score),
        "Threshold":   _p_num(thr),
        "Regime 1H":   _p_sel(r1h),
        "Regime 4H":   _p_sel(r4h),
        "Entry":       _p_num(levels.get("entry")),
        "Stop Loss":   _p_num(levels.get("stop_loss")),
        "Take Profit": _p_num(levels.get("take_profit")),
        "ATR %":       _p_num(levels.get("atr_pct")),
        "Entry Time":  _p_date(entry_iso),
        "Exit Reason": _p_sel("OPEN"),
        "Reasons":     _p_txt(reason),
        "Signal ID":   _p_txt(signal_id),
    }
    created = _request("POST", "/pages", {
        "parent": {"database_id": db_id},
        "properties": props,
    })
    if created:
        logger.info(f"[Notion] ✅ 신호 기록: {name}")
        return True
    logger.warning(f"[Notion] ❌ 신호 기록 실패: {name}")
    return False


# ════════════════════════════════════════════════════════════════════
# ② 성공/실패 자동 평가
# ════════════════════════════════════════════════════════════════════

def _candles_after(df_1h, entry_dt):
    """entry_dt(UTC) 이후 마감된 1H 캔들 (시간오름차순 [(ts, high, low), ...])."""
    out = []
    if df_1h is None or len(df_1h) == 0:
        return out
    try:
        import pandas as pd
        et = pd.Timestamp(entry_dt)
        if et.tzinfo is None:
            et = et.tz_localize("UTC")
        for ts, row in df_1h.iterrows():
            t = ts if getattr(ts, "tzinfo", None) else pd.Timestamp(ts).tz_localize("UTC")
            if t > et:
                out.append((t.to_pydatetime(), float(row["high"]), float(row["low"]), float(row["close"])))
    except Exception as e:
        logger.warning(f"[Notion-Eval] 캔들 추출 오류: {e}")
    return out


def _evaluate_one(direction, entry, sl, tp, candles, current_price, entry_dt, now):
    """단일 신호 판정 → (result, exit_reason, exit_price, resolved_dt) 또는 None(미체결).

    [P3] 만기(EXPIRED) 판정을 결정적으로: 봇 실행 시점의 실시간가(current_price)가 아니라
         entry+EVAL_MAX_HOLD_HOURS 시점 봉의 종가로 청산한다. 72h 정각 실행을 놓쳐도
         라벨이 실행 타이밍에 흔들리지 않는다. (만기 봉 미도달 시 None → OPEN 유지)
    """
    d = direction.lower()
    expire_at = entry_dt + timedelta(hours=config.EVAL_MAX_HOLD_HOURS)
    for ts, hi, lo, cl in candles:
        sl_hit = (lo <= sl) if d == "long" else (hi >= sl)
        tp_hit = (hi >= tp) if d == "long" else (lo <= tp)
        if sl_hit and tp_hit:
            # 동시 터치 → SL 우선(보수적)
            if config.EVAL_SL_PRIORITY:
                return ("LOSS", "SL_HIT", sl, ts)
            return ("WIN", "TP_HIT", tp, ts)
        if sl_hit:
            return ("LOSS", "SL_HIT", sl, ts)
        if tp_hit:
            return ("WIN", "TP_HIT", tp, ts)
        # SL/TP 미터치 상태로 만기 봉에 도달 → 그 봉 종가로 결정적 청산
        if ts >= expire_at:
            pnl = (cl - entry) if d == "long" else (entry - cl)
            return ("WIN" if pnl >= 0 else "LOSS",
                    "EXPIRED_WIN" if pnl >= 0 else "EXPIRED_LOSS", cl, ts)

    # 폴백: 만기 봉이 아직 캔들에 없지만 벽시계상 크게 초과(데이터 지연 등) → 실시간가로 청산
    held_h = (now - entry_dt).total_seconds() / 3600.0
    if held_h >= config.EVAL_MAX_HOLD_HOURS + 6 and current_price > 0:
        pnl = (current_price - entry) if d == "long" else (entry - current_price)
        if pnl >= 0:
            return ("WIN", "EXPIRED_WIN", current_price, now)
        return ("LOSS", "EXPIRED_LOSS", current_price, now)
    return None


def evaluate_open_signals(symbol: str, df_1h, current_price: float) -> int:
    """심볼의 OPEN 신호를 점검·갱신. 갱신된 건수 반환."""
    if not enabled():
        return 0
    db_id = _ensure_database()
    if not db_id:
        return 0

    res = _request("POST", f"/databases/{db_id}/query", {
        "filter": {"and": [
            {"property": "Result", "select": {"equals": "OPEN"}},
            {"property": "Symbol", "select": {"equals": symbol}},
        ]},
        "page_size": 100,
    })
    if not res:
        return 0

    now = datetime.now(timezone.utc)
    updated = 0
    for page in res.get("results", []):
        props = page.get("properties", {})
        direction = (_get_sel(props, "Direction") or "long").lower()
        entry = _get_num(props, "Entry")
        sl    = _get_num(props, "Stop Loss")
        tp    = _get_num(props, "Take Profit")
        e_iso = _get_date(props, "Entry Time")
        if entry is None or sl is None or tp is None or not e_iso:
            continue
        try:
            entry_dt = datetime.fromisoformat(e_iso.replace("Z", "+00:00"))
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        candles = _candles_after(df_1h, entry_dt)
        verdict = _evaluate_one(direction, entry, sl, tp, candles, current_price, entry_dt, now)
        if not verdict:
            continue

        result, exit_reason, exit_price, resolved_dt = verdict
        risk = abs(entry - sl) or (entry * 0.01)
        r_mult = ((exit_price - entry) if direction == "long" else (entry - exit_price)) / risk
        hold_h = (resolved_dt - entry_dt).total_seconds() / 3600.0

        ok = _request("PATCH", f"/pages/{page['id']}", {"properties": {
            "Result":        _p_sel(result),
            "Exit Price":    _p_num(exit_price),
            "R Multiple":    _p_num(round(r_mult, 3)),
            "Resolved Time": _p_date(resolved_dt.isoformat()),
            "Hold (h)":      _p_num(round(hold_h, 1)),
            "Exit Reason":   _p_sel(exit_reason),
        }})
        if ok:
            updated += 1
            logger.info(f"[Notion-Eval] {symbol} {direction.upper()} → {result} ({exit_reason}, "
                        f"R={r_mult:+.2f}, {hold_h:.1f}h)")
    if updated:
        logger.info(f"[Notion-Eval] {symbol} 신호 {updated}건 판정 갱신")
    return updated
