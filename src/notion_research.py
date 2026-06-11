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
# 주의: DB가 존재해도 봇 통합(Integration)에 공유되지 않았으면 Notion API는
# 404를 반환한다. 그 경우 토큰이 접근 가능한 동명 DB를 검색하고, 없으면
# 기존 신호 DB(1H Signal Log)의 부모 페이지 아래에 자동 생성한다.
# (신호 DB가 동작 중이라면 그 부모에는 반드시 쓰기 권한이 있다)

_RESEARCH_DB_TITLE = "1H Research Snapshots"
_db_cache = None          # 검증 완료된 DB ID (런 내 캐시)
_db_failed = False        # 확보 실패 시 런 내 재시도 방지

_NUM_PROPS = [
    "FV", "P0",
    "RSI 1H", "RSI 4H", "RSI 1D", "RSI 1D Slope", "RSI Wtd",
    "BB Pos", "BB Width Ratio", "MA20 Slope",
    "ADX", "ADX Slope", "ADX 4H", "DI Diff",
    "EMA 1H", "EMA 4H", "EMA 1D", "MACD Hist Pct", "MACD Cross",
    "Vol Ratio", "ATR Pct", "ATR Ratio",
    "BOS", "CHoCH", "BOS 4H", "CHoCH 4H", "FVG", "OB Sign", "OB Strength",
    "Fib GP", "Fib Key", "Weekly Lvl", "Maturity Net", "Struct", "Failed Break",
    "Candle 1H", "Candle 4H", "Candle 1D", "Vol Div",
    "Funding Pct", "LS Long", "Taker Buy", "OI Chg", "OI Slope", "Smart Div",
    "Hour UTC", "DOW",
    "Score L", "Score S", "Thr L", "Thr S",
    "Ret 4h", "Ret 12h", "Ret 24h", "Ret 48h", "Ret 72h",
    "MFE 72h", "MAE 72h", "Ret 24h ATR", "Ret 72h ATR",
    "TT Peak", "TT Trough", "Path Eff",
]

_SEL_PROPS = {
    "Symbol":  [("BTC/USDT", "orange"), ("ETH/USDT", "blue"), ("HYPE/USDT", "purple")],
    "Outcome": [("PENDING", "gray"), ("DONE", "green"), ("EXPIRED", "red")],
    "FP Key":  [],
    "Regime 1H": [("TRENDING", "green"), ("RANGING", "gray"),
                  ("EXPLOSIVE", "red"), ("SQUEEZE", "yellow"), ("UNKNOWN", "default")],
    "Regime 4H": [("TRENDING", "green"), ("RANGING", "gray"),
                  ("EXPLOSIVE", "red"), ("SQUEEZE", "yellow"), ("UNKNOWN", "default")],
    "Bias 1D":  [("BULL", "green"), ("BEAR", "red"), ("NEUTRAL", "gray")],
    "RSI Zone": [("OS", "blue"), ("MID", "gray"), ("OB", "orange"), ("NA", "default")],
    "Vol Zone": [("SQUEEZE", "yellow"), ("NORMAL", "gray"),
                 ("EXPANDED", "red"), ("NA", "default")],
    "Retrace L": [("none", "default"), ("too_shallow", "gray"), ("shallow", "yellow"),
                  ("optimal", "green"), ("deep", "orange"), ("broken", "red")],
    "Retrace S": [("none", "default"), ("too_shallow", "gray"), ("shallow", "yellow"),
                  ("optimal", "green"), ("deep", "orange"), ("broken", "red")],
    "Funding Bias": [], "Funding Signal": [], "LS Bias": [], "Taker Bias": [],
    "OI Quadrant": [], "Smart Dir": [], "Liq Signal": [], "Liq Fav": [],
    "Direction": [("long", "green"), ("short", "red")],
    "Class 24h": [("UP", "green"), ("DOWN", "red"), ("FLAT", "gray")],
    "Class 72h": [("UP", "green"), ("DOWN", "red"), ("FLAT", "gray")],
}


def _db_schema() -> dict:
    props = {"Name": {"title": {}},
             "TS": {"date": {}}, "Resolved At": {"date": {}},
             "Snapshot ID": {"rich_text": {}},
             "BB Squeeze": {"checkbox": {}}, "Signal": {"checkbox": {}}}
    for n in _NUM_PROPS:
        props[n] = {"number": {}}
    for n, opts in _SEL_PROPS.items():
        props[n] = {"select": {"options": [{"name": o, "color": c} for o, c in opts]}}
    return props


def _db_accessible(db_id: str) -> bool:
    return bool(db_id and _request("GET", f"/databases/{db_id}"))


def _find_db_by_title() -> str:
    res = _request("POST", "/search", {
        "query": _RESEARCH_DB_TITLE,
        "filter": {"property": "object", "value": "database"},
    })
    for obj in (res or {}).get("results", []):
        title = "".join(t.get("plain_text", "") for t in obj.get("title", []))
        if title.strip() == _RESEARCH_DB_TITLE:
            return obj.get("id")
    return None


def _signal_db_parent_page() -> str:
    """기존 신호 DB의 부모 페이지 ID — 봇 토큰이 확실히 접근 가능한 위치."""
    if config.NOTION_PARENT_PAGE_ID:
        return config.NOTION_PARENT_PAGE_ID
    if not config.NOTION_DATABASE_ID:
        return None
    db = _request("GET", f"/databases/{config.NOTION_DATABASE_ID}")
    parent = (db or {}).get("parent", {})
    return parent.get("page_id")


def _create_db() -> str:
    parent = _signal_db_parent_page()
    if not parent:
        logger.warning("[Notion/Research] DB 자동 생성 불가 — 접근 가능한 부모 페이지 없음")
        return None
    created = _request("POST", "/databases", {
        "parent": {"type": "page_id", "page_id": parent},
        "title": [{"type": "text", "text": {"content": _RESEARCH_DB_TITLE}}],
        "properties": _db_schema(),
    })
    if created and created.get("id"):
        logger.info(f"[Notion/Research] 신규 DB 자동 생성: {created['id']} (부모: {parent})")
        return created["id"]
    logger.warning("[Notion/Research] DB 자동 생성 실패")
    return None


def _ensure_db() -> str:
    """사용할 DB ID 반환. 지정 ID 검증 → 동명 DB 검색 → 자동 생성 순."""
    global _db_cache, _db_failed
    if _db_cache:
        return _db_cache
    if _db_failed:
        return None

    cand = config.NOTION_RESEARCH_DB_ID
    if _db_accessible(cand):
        _db_cache = cand
        return _db_cache
    if cand:
        logger.warning(
            f"[Notion/Research] 지정 DB({cand}) 접근 불가 — 봇 통합에 공유되지 않았을 가능성. "
            f"Notion에서 해당 DB(또는 상위 페이지) ··· → 연결 에 봇 통합을 추가하면 그대로 사용됩니다. "
            f"우선 토큰이 접근 가능한 동명 DB를 탐색/생성합니다."
        )

    found = _find_db_by_title()
    if found:
        logger.info(f"[Notion/Research] 접근 가능한 기존 DB 재사용: {found}")
        _db_cache = found
        return _db_cache

    created = _create_db()
    if created:
        _db_cache = created
        return _db_cache

    _db_failed = True
    return None


# ════════════════════════════════════════════════════════════════════
# ① 스냅샷 기록 (L1 + L2 + L3)
# ════════════════════════════════════════════════════════════════════

def _build_properties(state: dict) -> dict:
    f, fp, meta = state["f"], state["fp"], state["meta"]
    p0 = state.get("p0") or 0.0
    ts = pd.Timestamp(state["ts"])

    # 절대가 단위 → % 변환 (표현 규약: 절대가격 금지)
    macd_pct = None
    if f.get("macd_hist") is not None and p0 > 0:
        macd_pct = round(f["macd_hist"] / p0 * 100.0, 6)
    bb_wr = None
    if f.get("bb_width") and f.get("bb_avg_width"):
        bb_wr = round(f["bb_width"] / f["bb_avg_width"], 4) if f["bb_avg_width"] > 0 else None
    di_diff = None
    if f.get("plus_di") is not None and f.get("minus_di") is not None:
        di_diff = round(f["plus_di"] - f["minus_di"], 2)
    fund_pct = None
    if f.get("funding") is not None:
        fund_pct = round(f["funding"] * 100.0, 6)

    title = f"{state['symbol']} {ts.strftime('%m-%d %H:00')} · {fp['regime_1h']}/{fp['regime_4h']}"

    return {
        # ── 메타 ──
        "Name":        _p_title(title),
        "TS":          _p_date(ts.isoformat()),
        "Symbol":      _p_sel(state["symbol"]),
        "Snapshot ID": _p_txt(state["snapshot_id"]),
        "FV":          _p_num(state.get("feature_version", 1)),
        "Outcome":     _p_sel("PENDING"),
        "P0":          _p_num(p0),
        # ── L2 지문 ──
        "FP Key":      _p_sel(fp["key"]),
        "Regime 1H":   _p_sel(fp["regime_1h"]),
        "Regime 4H":   _p_sel(fp["regime_4h"]),
        "Bias 1D":     _p_sel(fp["bias_1d"]),
        "RSI Zone":    _p_sel(fp["rsi_zone"]),
        "Vol Zone":    _p_sel(fp["vol_zone"]),
        # ── L1: 모멘텀/추세 ──
        "RSI 1H":        _p_num(f.get("rsi_1h")),
        "RSI 4H":        _p_num(f.get("rsi_4h")),
        "RSI 1D":        _p_num(f.get("rsi_1d")),
        "RSI 1D Slope":  _p_num(f.get("rsi_1d_slope")),
        "RSI Wtd":       _p_num(f.get("rsi_weighted")),
        "BB Pos":        _p_num(f.get("bb_pos")),
        "BB Width Ratio": _p_num(bb_wr),
        "BB Squeeze":    _p_chk(f.get("bb_squeeze")),
        "MA20 Slope":    _p_num(f.get("ma20_slope_sign")),
        "ADX":           _p_num(f.get("adx")),
        "ADX Slope":     _p_num(f.get("adx_slope")),
        "ADX 4H":        _p_num(f.get("adx_4h")),
        "DI Diff":       _p_num(di_diff),
        "EMA 1H":        _p_num(f.get("ema_1h")),
        "EMA 4H":        _p_num(f.get("ema_4h")),
        "EMA 1D":        _p_num(f.get("ema_1d")),
        "MACD Hist Pct": _p_num(macd_pct),
        "MACD Cross":    _p_num(f.get("macd_cross")),
        "Vol Ratio":     _p_num(f.get("volume_ratio")),
        "ATR Pct":       _p_num(f.get("atr_pct")),
        "ATR Ratio":     _p_num(f.get("atr_ratio")),
        # ── L1: 구조(SMC) — 부호화 ──
        "BOS":           _p_num(f.get("bos")),
        "CHoCH":         _p_num(f.get("choch")),
        "BOS 4H":        _p_num(f.get("bos_4h")),
        "CHoCH 4H":      _p_num(f.get("choch_4h")),
        "FVG":           _p_num(f.get("fvg")),
        "OB Sign":       _p_num(f.get("order_block")),
        "OB Strength":   _p_num(f.get("ob_strength")),
        "Fib GP":        _p_num(f.get("fib_gp")),
        "Fib Key":       _p_num(f.get("fib_key")),
        "Weekly Lvl":    _p_num(f.get("weekly_lvl")),
        "Retrace L":     _p_sel(f.get("retrace_long_zone")),
        "Retrace S":     _p_sel(f.get("retrace_short_zone")),
        "Maturity Net":  _p_num(f.get("maturity_net")),
        "Struct":        _p_num(f.get("struct")),
        "Failed Break":  _p_num(f.get("failed_break")),
        "Candle 1H":     _p_num(f.get("candle_1h")),
        "Candle 4H":     _p_num(f.get("candle_4h")),
        "Candle 1D":     _p_num(f.get("candle_1d")),
        "Vol Div":       _p_num(f.get("vol_div")),
        # ── L1: 심리/포지셔닝 ──
        "Funding Pct":    _p_num(fund_pct),
        "Funding Bias":   _p_sel(f.get("funding_bias")),
        "Funding Signal": _p_sel(f.get("funding_signal")),
        "LS Long":        _p_num(f.get("ls_long_pct")),
        "LS Bias":        _p_sel(f.get("ls_bias")),
        "Taker Buy":      _p_num(f.get("taker_buy")),
        "Taker Bias":     _p_sel(f.get("taker_bias")),
        "OI Chg":         _p_num(f.get("oi_change")),
        "OI Slope":       _p_num(f.get("oi_slope")),
        "OI Quadrant":    _p_sel(f.get("oi_quadrant")),
        "Smart Div":      _p_num(f.get("smart_div")),
        "Smart Dir":      _p_sel(f.get("smart_dir")),
        "Liq Signal":     _p_sel(f.get("liq_signal")),
        "Liq Fav":        _p_sel(f.get("liq_fav")),
        "Hour UTC":       _p_num(f.get("hour_utc")),
        "DOW":            _p_num(f.get("dow")),
        # ── L3 참고 메타 (학습 입력 아님) ──
        "Score L":   _p_num(meta.get("score_long")),
        "Score S":   _p_num(meta.get("score_short")),
        "Thr L":     _p_num(meta.get("thr_long")),
        "Thr S":     _p_num(meta.get("thr_short")),
        "Signal":    _p_chk(meta.get("signal_fired")),
        "Direction": _p_sel(meta.get("direction")),
    }


def _snapshot_exists(db_id: str, snapshot_id: str) -> bool:
    res = _request("POST", f"/databases/{db_id}/query", {
        "filter": {"property": "Snapshot ID", "rich_text": {"equals": snapshot_id}},
        "page_size": 1,
    })
    return bool(res and res.get("results"))


def log_snapshot(state: dict) -> bool:
    """상태 스냅샷 1행 생성 (Outcome=PENDING). 동일 snapshot_id 존재 시 skip(멱등)."""
    db_id = _ensure_db()
    if not db_id:
        logger.warning("[Notion/Research] 사용 가능한 DB 없음 — 스냅샷 기록 skip")
        return False
    if _snapshot_exists(db_id, state["snapshot_id"]):
        logger.debug(f"[Notion/Research] 중복 스냅샷 skip: {state['snapshot_id']}")
        return False
    res = _request("POST", "/pages", {
        "parent": {"database_id": db_id},
        "properties": _build_properties(state),
    })
    ok = bool(res and res.get("id"))
    if ok:
        logger.info(f"[Notion/Research] 📸 스냅샷 기록 {state['symbol']} @ {state['ts']}")
    else:
        logger.warning(f"[Notion/Research] 스냅샷 기록 실패: {state['snapshot_id']}")
    return ok


# ════════════════════════════════════════════════════════════════════
# ② 사후 결과 기입 — 72h 성숙한 PENDING 행에 차트 움직임 라벨
# ════════════════════════════════════════════════════════════════════

def _compute_outcome(p0: float, atr_pct, ts: pd.Timestamp, df_1h: pd.DataFrame):
    """(properties dict | None, status) — status: 'done'/'expired'/'immature'."""
    H = config.RESEARCH_PATH_HOURS
    later = df_1h[df_1h.index > ts]
    if len(later) < H:
        # 윈도가 슬라이드해 초기 캔들이 유실된 고아 행 → EXPIRED
        if len(later) == 0 or (later.index[0] - ts).total_seconds() / 3600.0 > H:
            return None, "expired"
        return None, "immature"
    if (later.index[0] - ts).total_seconds() / 3600.0 > H:
        return None, "expired"
    if not p0 or p0 <= 0:
        return None, "expired"

    seg = later.iloc[:H]
    c = [float(x) / p0 - 1.0 for x in seg["close"].values]
    h = [float(x) / p0 - 1.0 for x in seg["high"].values]
    l = [float(x) / p0 - 1.0 for x in seg["low"].values]

    def _pct(v):
        return round(v * 100.0, 4)

    ret = {hh: _pct(c[hh - 1]) for hh in (4, 12, 24, 48, 72) if hh <= len(c)}
    mfe = _pct(max(h)); mae = _pct(min(l))
    tt_peak = h.index(max(h)) + 1
    tt_trough = l.index(min(l)) + 1
    travel = sum(abs(c[i] - c[i - 1]) for i in range(1, len(c))) + abs(c[0])
    path_eff = round(abs(c[-1]) / travel, 4) if travel > 0 else None

    atr = float(atr_pct) if atr_pct else None
    dead = 0.25 * atr if atr else None

    def _cls(r_pct):
        if r_pct is None:
            return None
        if dead is not None and abs(r_pct) < dead:
            return "FLAT"
        return "UP" if r_pct > 0 else "DOWN"

    props = {
        "Outcome":     _p_sel("DONE"),
        "Ret 4h":      _p_num(ret.get(4)),
        "Ret 12h":     _p_num(ret.get(12)),
        "Ret 24h":     _p_num(ret.get(24)),
        "Ret 48h":     _p_num(ret.get(48)),
        "Ret 72h":     _p_num(ret.get(72)),
        "MFE 72h":     _p_num(mfe),
        "MAE 72h":     _p_num(mae),
        "Ret 24h ATR": _p_num(round(ret[24] / atr, 4) if (atr and 24 in ret) else None),
        "Ret 72h ATR": _p_num(round(ret[72] / atr, 4) if (atr and 72 in ret) else None),
        "Class 24h":   _p_sel(_cls(ret.get(24))),
        "Class 72h":   _p_sel(_cls(ret.get(72))),
        "TT Peak":     _p_num(tt_peak),
        "TT Trough":   _p_num(tt_trough),
        "Path Eff":    _p_num(path_eff),
        "Resolved At": _p_date(datetime.now(timezone.utc).isoformat()),
    }
    return props, "done"


def update_outcomes(symbol: str, df_1h: pd.DataFrame) -> int:
    """봉시각+72h 지난 PENDING 행에 결과 라벨 기입. 갱신 행 수 반환."""
    if df_1h is None or len(df_1h) == 0:
        return 0
    db_id = _ensure_db()
    if not db_id:
        return 0
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=config.RESEARCH_PATH_HOURS)).isoformat()
    res = _request("POST", f"/databases/{db_id}/query", {
        "filter": {"and": [
            {"property": "Symbol",  "select": {"equals": symbol}},
            {"property": "Outcome", "select": {"equals": "PENDING"}},
            {"property": "TS",      "date":   {"before": cutoff}},
        ]},
        "page_size": 50,
    })
    if not res:
        return 0

    updated = 0
    for page in res.get("results", []):
        props = page.get("properties", {})
        try:
            ts_raw = props.get("TS", {}).get("date", {}).get("start")
            if not ts_raw:
                continue
            ts = pd.Timestamp(ts_raw)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            p0 = _get_num(props, "P0")
            atr_pct = _get_num(props, "ATR Pct")
            out_props, status = _compute_outcome(p0, atr_pct, ts, df_1h)
            if status == "immature":
                continue
            if status == "expired":
                out_props = {"Outcome": _p_sel("EXPIRED"),
                             "Resolved At": _p_date(datetime.now(timezone.utc).isoformat())}
            r = _request("PATCH", f"/pages/{page['id']}", {"properties": out_props})
            if r:
                updated += 1
        except Exception as e:
            logger.warning(f"[Notion/Research] 결과 기입 오류({page.get('id','?')}): {e}")
    if updated:
        logger.info(f"[Notion/Research] 🏷️ 결과 기입 {updated}건 — {symbol}")
    return updated