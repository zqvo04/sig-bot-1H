"""WRF Notion 로거 — 2 DB(REST 직접). NOTION_TOKEN 미설정 시 자동 no-op.

  DB1 WRF Signals   : 발사된 페이퍼 트레이드 (OPEN→WIN/LOSS/TIMEOUT 자동판정)
  DB2 WRF Snapshots : 매시간 학습 미러(사람뷰) — 핵심 L1 + 파생라벨(필터·그룹용)

원시 72h 경로 전체는 git JSONL이 보관. Notion은 필터·그룹용 핵심만 둔다.
라이브 본체와 격리되도록 모든 함수가 enabled() 가드 + 예외 흡수한다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

try:
    import config
    from notion_logger import (_request, _p_num, _p_sel, _p_txt, _p_title,
                               _p_date, _get_num, _get_sel, _get_date, _get_txt)
except ImportError:  # pragma: no cover
    from src import config
    from src.notion_logger import (_request, _p_num, _p_sel, _p_txt, _p_title,
                                   _p_date, _get_num, _get_sel, _get_date, _get_txt)

logger = logging.getLogger(__name__)

# Notion 표시는 한국시간(KST, UTC+9) 기준. JSONL의 ts/snapshot_id는 UTC 그대로 유지
# (멱등키·경로캡처·라벨 정합성 보존) — 변환은 Notion 날짜/제목 표시 계층에만 적용.
_KST = timezone(timedelta(hours=9))


def _kst(iso: str) -> str:
    """UTC ISO 문자열 → KST(+09:00) ISO 문자열. 실패 시 원본 반환."""
    if not iso:
        return iso
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_KST).isoformat()
    except Exception:
        return iso


def _p_date_kst(iso: str) -> dict:
    """Notion date 속성을 KST로 표시. time_zone='Asia/Seoul' + 오프셋 없는 로컬시각
    → 뷰어 타임존과 무관하게 모두 KST로 표시(Notion 규칙: time_zone 지정 시 start는
    오프셋 미포함)."""
    if not iso:
        return {"date": None}
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(_KST).replace(tzinfo=None).isoformat()
        return {"date": {"start": local, "time_zone": "Asia/Seoul"}}
    except Exception:
        return _p_date(_kst(iso))

_SIG_CACHE = None
_SNAP_CACHE = None
_SYNCED = set()   # 스키마 동기화 완료한 db_id (프로세스당 1회만)

_REGIME_OPTS = [{"name": n} for n in ("TRENDING", "EXPLOSIVE", "RANGING", "SQUEEZE", "UNKNOWN")]
_MACRO_OPTS = [{"name": n} for n in ("UPLEG", "DOWNLEG", "CHOP")]
_SETUP_OPTS = [{"name": n} for n in ("TF", "BO", "MR", "RV")]


def enabled() -> bool:
    return bool(getattr(config, "NOTION_ENABLED", False) and getattr(config, "NOTION_TOKEN", ""))


# ── DB 스키마 ────────────────────────────────────────────────────────
SIGNALS_PROPS = {
    "Name": {"title": {}},
    "Status": {"select": {"options": [{"name": "OPEN", "color": "gray"},
        {"name": "WIN", "color": "green"}, {"name": "LOSS", "color": "red"},
        {"name": "TIMEOUT", "color": "yellow"}]}},
    "Setup": {"select": {"options": _SETUP_OPTS}},
    "Direction": {"select": {"options": [{"name": "LONG", "color": "green"}, {"name": "SHORT", "color": "red"}]}},
    "Symbol": {"select": {"options": [{"name": n} for n in ("BTC/USDT", "ETH/USDT", "HYPE/USDT", "SOL/USDT", "SUI/USDT", "XRP/USDT")]}},
    "Regime 1H": {"select": {"options": _REGIME_OPTS}},
    "Regime 4H": {"select": {"options": _REGIME_OPTS}},
    "BTC Macro": {"select": {"options": _MACRO_OPTS}},
    "Entry": {"number": {}}, "TP": {"number": {}}, "SL": {"number": {}},
    "R Dist": {"number": {}}, "RR": {"number": {}}, "T_max": {"number": {}},
    "P_hat": {"number": {}},
    "P Source": {"select": {"options": [{"name": "prior", "color": "gray"}, {"name": "calibrated", "color": "blue"}]}},
    "Win Floor": {"number": {}}, "Size": {"number": {}},
    "C": {"number": {}}, "L": {"number": {}}, "F": {"number": {}},
    "MFE R": {"number": {}}, "MAE R": {"number": {}}, "Bars To Exit": {"number": {}},
    "Exit Price": {"number": {}}, "R Multiple": {"number": {}},
    "Exit Reason": {"select": {"options": [{"name": n} for n in ("TP_HIT", "SL_HIT", "TIMEOUT", "EXPIRED_WIN", "EXPIRED_LOSS", "OPEN")]}},
    "Signaled At": {"date": {}}, "Resolved At": {"date": {}},
    "Reason": {"rich_text": {}}, "Signal ID": {"rich_text": {}},
}

SNAP_NUM = ["RSI", "RSI 4H", "RSI 1D", "BB %b", "Dist VWAP ATR", "Dist EMA20 ATR",
            "ATR %", "ADX", "ADX Slope", "MACD", "Funding", "Funding Slope",
            "OI Chg", "OI Slope", "LS Long", "Taker Buy", "Smart Div", "Vol Ratio",
            "Rev Vol Ratio",
            "EMA 1H", "EMA 4H", "EMA 1D", "EMA 1D Struct", "BOS", "CHoCH", "BOS 4H",
            "CHoCH 4H", "Failed Break",
            "FVG", "OB Sign", "Fib GP", "Weekly Lvl", "Maturity Net", "Hour UTC", "DOW",
            "Confluence L", "Confluence S",
            "Ret 4h", "Ret 12h", "Ret 24h", "Ret 48h", "Ret 72h", "exRet 24h",
            "MFE", "MAE", "Path Eff", "TT Peak", "TT Trough", "Candidates", "Fired"]
_ZONE_OPTS = [{"name": n} for n in ("none", "too_shallow", "shallow", "optimal", "deep", "broken")]
_MATURITY_OPTS = [{"name": n} for n in ("none", "early", "mid", "late")]
_OI_QUAD_OPTS = [{"name": n} for n in ("neutral", "trend_long", "trend_short",
    "reversal_long", "reversal_short", "weak_bounce", "expanding_long", "expanding_short")]
_LIQ_OPTS = [{"name": n} for n in ("none", "long_liq_detected", "short_liq_detected")]
SNAP_SEL = {
    "Symbol": [{"name": n} for n in ("BTC/USDT", "ETH/USDT", "HYPE/USDT", "SOL/USDT", "SUI/USDT", "XRP/USDT")],
    "Outcome": [{"name": "PENDING", "color": "gray"}, {"name": "DONE", "color": "green"}, {"name": "EXPIRED", "color": "brown"}],
    "BTC Macro": _MACRO_OPTS, "Regime 1H": _REGIME_OPTS, "Regime 4H": _REGIME_OPTS,
    "Bias 1D": [{"name": n} for n in ("BULL", "BEAR", "NEUTRAL")],
    "RSI Zone": [{"name": n} for n in ("OS", "MID", "OB")],
    "Vol Zone": [{"name": n} for n in ("SQUEEZE", "NORMAL", "EXPANDED")],
    "OI Quadrant": _OI_QUAD_OPTS, "Liq Signal": _LIQ_OPTS,
    "Retrace L": _ZONE_OPTS, "Retrace S": _ZONE_OPTS, "Maturity": _MATURITY_OPTS,
    "Class 24h": [{"name": n} for n in ("UP", "FLAT", "DOWN")],
    "Class 72h": [{"name": n} for n in ("UP", "FLAT", "DOWN")],
}


def _snapshots_props() -> dict:
    # FP Key는 기존 DB와 동일하게 select(옵션은 기록 시 자동 생성). Snapshot ID는 text.
    props = {"Name": {"title": {}}, "TS": {"date": {}}, "FP Key": {"select": {"options": []}},
             "Snapshot ID": {"rich_text": {}}}
    for k in SNAP_NUM:
        props[k] = {"number": {}}
    for k, opts in SNAP_SEL.items():
        props[k] = {"select": {"options": opts}}
    return props


def _sync_missing_props(db_id: str, props: dict) -> None:
    """기존 DB에 누락된 컬럼만 멱등 PATCH 추가(self-heal). 프로세스당 db_id 1회.

    [버그수정] _ensure_db는 신규 생성 시에만 전체 컬럼을 넣어, 기존 DB에 새 컬럼이
    추가되지 않았다. 그 상태로 log_*가 미존재 프로퍼티를 POST하면 Notion이 페이지
    생성 전체를 거부(400) → 기록 자체가 실패. 라이브가 스스로 스키마를 맞춘다."""
    if not db_id or db_id in _SYNCED:
        return
    try:
        res = _request("GET", f"/databases/{db_id}")
        have = set((res.get("properties") or {}).keys()) if res else set()
        if not have:
            return  # 조회 실패 — 다음 기회에 재시도(_SYNCED 미표시)
        missing = {k: v for k, v in props.items() if k not in have}
        if missing:
            r = _request("PATCH", f"/databases/{db_id}", {"properties": missing})
            if r:
                logger.info(f"[NotionWRF] 스키마 자동동기화 +{len(missing)}컬럼 → {sorted(missing)}")
            else:
                logger.warning("[NotionWRF] 스키마 동기화 PATCH 실패 — 통합 권한(DB 편집) 확인 필요")
                return  # 미표시 → 다음 실행에서 재시도
        _SYNCED.add(db_id)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[NotionWRF] 스키마 동기화 예외(격리): {e}")


def _ensure_db(cache_attr: str, db_id_cfg: str, title: str, props: dict):
    global _SIG_CACHE, _SNAP_CACHE
    cached = _SIG_CACHE if cache_attr == "sig" else _SNAP_CACHE
    if cached:
        return cached
    db_id = getattr(config, db_id_cfg, "")
    result = db_id or _find_db_by_title(title)   # ID 우선, 없으면 제목 검색(부모 불필요)
    if not result:
        # ID·제목검색 모두 실패 → 부모 페이지가 있으면 신규 생성
        parent = getattr(config, "NOTION_PARENT_PAGE_ID", "")
        if not parent:
            logger.warning(f"[NotionWRF] {title}: DB ID·제목검색·부모페이지 모두 없음 → 비활성")
            return None
        created = _request("POST", "/databases", {
            "parent": {"type": "page_id", "page_id": parent},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": props})
        result = created.get("id") if created else None
        if result:
            logger.info(f"[NotionWRF] {title} 신규 생성: {result}")
    if result:
        _sync_missing_props(result, props)   # 기존 DB 누락 컬럼 self-heal
    if cache_attr == "sig":
        _SIG_CACHE = result
    else:
        _SNAP_CACHE = result
    return result


def _find_db_by_title(title: str):
    """통합에 공유된 DB를 제목으로 검색(부모 페이지 불필요). 없으면 None."""
    res = _request("POST", "/search", {"query": title,
        "filter": {"property": "object", "value": "database"}})
    if not res:
        return None
    for obj in res.get("results", []):
        t = "".join(x.get("plain_text", "") for x in obj.get("title", []))
        if t.strip() == title:
            return obj["id"]
    return None


def ensure_signals_db():
    return _ensure_db("sig", "NOTION_SIGNALS_DB_ID", config.NOTION_SIGNALS_DB_TITLE, SIGNALS_PROPS)


def ensure_snapshots_db():
    return _ensure_db("snap", "NOTION_SNAPSHOTS_DB_ID", config.NOTION_SNAPSHOTS_DB_TITLE, _snapshots_props())


# ── 신호 기록 (발사 후보 1건 = 1행) ────────────────────────────────────
def log_signal(cand: dict, engine_out: dict) -> bool:
    if not enabled():
        return False
    try:
        db = ensure_signals_db()
        if not db:
            return False
        ctx = engine_out["ctx"]
        sym = engine_out["symbol"]
        sid = f"{sym}_{engine_out['ts']}_{cand['setup']}_{cand['dir']}"
        # 멱등: 동일 Signal ID 존재 시 skip
        q = _request("POST", f"/databases/{db}/query", {
            "filter": {"property": "Signal ID", "rich_text": {"equals": sid}}, "page_size": 1})
        if q and q.get("results"):
            return False
        name = f"{sym} {cand['setup']}/{cand['dir'].upper()} P{cand['p_hat']:.2f}"
        props = {
            "Name": _p_title(name), "Status": _p_sel("OPEN"),
            "Setup": _p_sel(cand["setup"]), "Direction": _p_sel(cand["dir"].upper()),
            "Symbol": _p_sel(sym), "Regime 1H": _p_sel(ctx.get("regime_1h")),
            "Regime 4H": _p_sel(ctx.get("regime_4h")), "BTC Macro": _p_sel(ctx.get("btc_macro")),
            "Entry": _p_num(cand["entry"]), "TP": _p_num(cand["tp"]), "SL": _p_num(cand["sl"]),
            "R Dist": _p_num(cand["r_dist"]), "RR": _p_num(cand["rr"]), "T_max": _p_num(cand["t_max"]),
            "P_hat": _p_num(cand["p_hat"]), "P Source": _p_sel(cand["p_source"]),
            "Win Floor": _p_num(cand["win_floor"]), "Size": _p_num(cand["size"]),
            "C": _p_num(cand["C"]), "L": _p_num(cand["L"]), "F": _p_num(cand["F"]),
            "Exit Reason": _p_sel("OPEN"), "Signaled At": _p_date_kst(engine_out["ts"]),
            "Reason": _p_txt(cand.get("reason", "")), "Signal ID": _p_txt(sid),
        }
        r = _request("POST", "/pages", {"parent": {"database_id": db}, "properties": props})
        if r:
            logger.info(f"[NotionWRF] 🔔 신호 기록 {name}")
        return bool(r)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[NotionWRF] log_signal 실패(격리): {e}")
        return False


def _eval_signal(direction, entry, tp, sl, t_max, candles, signaled_dt, now):
    """실제 캔들로 OPEN 신호 판정. 반환 dict(status·reason·mfe·mae·bars·rdt·exit_price·r_mult) 또는 None(미성숙)."""
    long = direction.upper() == "LONG"
    r_dist = abs(entry - sl)
    if r_dist <= 0:
        return None
    fut = candles[candles.index > signaled_dt]
    if len(fut) == 0:
        return None
    mfe = mae = 0.0
    for i, (_, row) in enumerate(fut.iterrows()):
        if i >= int(t_max):
            break
        hi, lo = float(row["high"]), float(row["low"])
        fav = (hi - entry) if long else (entry - lo)
        adv = (entry - lo) if long else (hi - entry)
        mfe = max(mfe, fav / r_dist)
        mae = max(mae, adv / r_dist)
        sl_hit = (lo <= sl) if long else (hi >= sl)
        tp_hit = (hi >= tp) if long else (lo <= tp)
        rdt = row.name.isoformat()
        rr = abs(tp - entry) / r_dist if r_dist else 0.0
        if sl_hit:  # 동시터치 포함 SL 우선(보수적)
            return {"status": "LOSS", "reason": "SL_HIT", "mfe": mfe, "mae": mae,
                    "bars": i + 1, "rdt": rdt, "exit_price": sl, "r_mult": -1.0}
        if tp_hit:
            return {"status": "WIN", "reason": "TP_HIT", "mfe": mfe, "mae": mae,
                    "bars": i + 1, "rdt": rdt, "exit_price": tp, "r_mult": rr}
    # 타임스톱 도달 → TIMEOUT으로 두지 않고 진입가 대비 손익부호로 WIN/LOSS 판별.
    # (TP/SL 미터치라도 t_max 경과 시 시장가 청산 가정. 청산 사유는 EXPIRED_*.)
    if len(fut) >= int(t_max):
        last = fut.iloc[int(t_max) - 1]
        px = float(last["close"])
        realized = (px - entry) if long else (entry - px)
        win = realized >= 0
        return {"status": "WIN" if win else "LOSS",
                "reason": "EXPIRED_WIN" if win else "EXPIRED_LOSS",
                "mfe": mfe, "mae": mae, "bars": int(t_max),
                "rdt": last.name.isoformat(), "exit_price": round(px, 8),
                "r_mult": round(realized / r_dist, 4) if r_dist else 0.0}
    return None  # 미성숙


def evaluate_open_signals(symbol: str, df_1h) -> int:
    """OPEN 신호를 캔들로 판정 → Status/Exit Reason/MFE/MAE/Bars/Resolved 갱신."""
    if not enabled():
        return 0
    try:
        db = ensure_signals_db()
        if not db or df_1h is None or len(df_1h) == 0:
            return 0
        res = _request("POST", f"/databases/{db}/query", {
            "filter": {"and": [
                {"property": "Status", "select": {"equals": "OPEN"}},
                {"property": "Symbol", "select": {"equals": symbol}}]}, "page_size": 50})
        if not res:
            return 0
        now = datetime.now(timezone.utc)
        updated = 0
        for page in res.get("results", []):
            p = page.get("properties", {})
            direction = _get_sel(p, "Direction")
            entry, tp, sl = _get_num(p, "Entry"), _get_num(p, "TP"), _get_num(p, "SL")
            t_max = _get_num(p, "T_max") or 48
            sig_at = _get_date(p, "Signaled At")
            if not all([direction, entry, tp, sl, sig_at]):
                continue
            import pandas as pd
            sdt = pd.Timestamp(sig_at)
            if sdt.tzinfo is None:
                sdt = sdt.tz_localize(timezone.utc)
            out = _eval_signal(direction, entry, tp, sl, t_max, df_1h, sdt, now)
            if not out:
                continue
            _request("PATCH", f"/pages/{page['id']}", {"properties": {
                "Status": _p_sel(out["status"]), "Exit Reason": _p_sel(out["reason"]),
                "MFE R": _p_num(round(out["mfe"], 3)), "MAE R": _p_num(round(out["mae"], 3)),
                "Bars To Exit": _p_num(out["bars"]), "Resolved At": _p_date_kst(out["rdt"]),
                "Exit Price": _p_num(out["exit_price"]), "R Multiple": _p_num(out["r_mult"])}})
            updated += 1
        if updated:
            logger.info(f"[NotionWRF] ✅ 신호 판정 {symbol}: {updated}건")
        return updated
    except Exception as e:  # pragma: no cover
        logger.warning(f"[NotionWRF] evaluate 실패(격리): {e}")
        return 0


# ── 스냅샷 미러 (매시간 1행) ─────────────────────────────────────────────
def _rsi_zone(rsi):
    if rsi is None:
        return "MID"
    return "OS" if rsi < 35 else ("OB" if rsi > 65 else "MID")


def _vol_zone(raw):
    return "NORMAL"


def log_snapshot(engine_out: dict) -> bool:
    if not enabled():
        return False
    try:
        db = ensure_snapshots_db()
        if not db:
            return False
        sym = engine_out["symbol"]
        sid = f"{sym}_{engine_out['ts']}"
        q = _request("POST", f"/databases/{db}/query", {
            "filter": {"property": "Snapshot ID", "rich_text": {"equals": sid}}, "page_size": 1})
        if q and q.get("results"):
            return False
        raw = engine_out["raw"]
        ctx = engine_out["ctx"]
        cands = engine_out.get("candidates", [])
        props = {
            "Name": _p_title(f"{sym} {_kst(engine_out['ts'])[:16]} KST"),
            "TS": _p_date_kst(engine_out["ts"]), "Symbol": _p_sel(sym),
            "Snapshot ID": _p_txt(sid), "Outcome": _p_sel("PENDING"),
            "FP Key": _p_sel(ctx.get("fp_key")), "BTC Macro": _p_sel(ctx.get("btc_macro")),
            "Regime 1H": _p_sel(ctx.get("regime_1h")), "Regime 4H": _p_sel(ctx.get("regime_4h")),
            "Bias 1D": _p_sel(ctx.get("bias_1d")),
            "RSI Zone": _p_sel(_rsi_zone(raw.get("rsi"))), "Vol Zone": _p_sel(_vol_zone(raw)),
            "RSI": _p_num(raw.get("rsi")), "RSI 4H": _p_num(raw.get("rsi_4h")),
            "RSI 1D": _p_num(raw.get("rsi_1d")), "BB %b": _p_num(raw.get("bb_pctb")),
            "Dist VWAP ATR": _p_num(raw.get("dist_vwap_atr")),
            "Dist EMA20 ATR": _p_num(raw.get("dist_ema20_atr")),
            "ATR %": _p_num(raw.get("atr_pct")), "ADX": _p_num(raw.get("adx")),
            "ADX Slope": _p_num(raw.get("adx_slope")),
            "MACD": _p_num(raw.get("macd")), "Funding": _p_num(raw.get("funding")),
            "Funding Slope": _p_num(raw.get("funding_slope")),
            "OI Chg": _p_num(raw.get("oi_chg")), "OI Slope": _p_num(raw.get("oi_slope")),
            "OI Quadrant": _p_sel(raw.get("oi_quadrant")),
            "LS Long": _p_num(raw.get("ls_long")),
            "Taker Buy": _p_num(raw.get("taker_buy")), "Smart Div": _p_num(raw.get("smart_div")),
            "Vol Ratio": _p_num(raw.get("vol_ratio")),
            "Rev Vol Ratio": _p_num(raw.get("rev_vol_ratio")),
            "EMA 1H": _p_num(raw.get("ema")), "EMA 4H": _p_num(raw.get("ema_4h")),
            "EMA 1D": _p_num(raw.get("ema_1d")), "EMA 1D Struct": _p_num(raw.get("ema_1d_struct")),
            "BOS": _p_num(raw.get("bos")), "CHoCH": _p_num(raw.get("choch")),
            "BOS 4H": _p_num(raw.get("bos_4h")), "CHoCH 4H": _p_num(raw.get("choch_4h")),
            "Failed Break": _p_num(raw.get("failed_break")),
            "FVG": _p_num(raw.get("fvg")), "OB Sign": _p_num(raw.get("ob")),
            "Fib GP": _p_num(raw.get("fib_gp")), "Weekly Lvl": _p_num(raw.get("weekly")),
            "Retrace L": _p_sel(raw.get("retrace_long_zone")),
            "Retrace S": _p_sel(raw.get("retrace_short_zone")),
            "Maturity": _p_sel(raw.get("maturity")),
            "Maturity Net": _p_num(raw.get("maturity_net")),
            "Liq Signal": _p_sel(raw.get("liq_signal")),
            "Hour UTC": _p_num(raw.get("hour_utc")), "DOW": _p_num(raw.get("dow")),
            "Confluence L": _p_num(raw.get("confluence_long")),
            "Confluence S": _p_num(raw.get("confluence_short")),
            "Candidates": _p_num(len(cands)),
            "Fired": _p_num(sum(1 for c in cands if c.get("fire"))),
        }
        r = _request("POST", "/pages", {"parent": {"database_id": db}, "properties": props})
        return bool(r)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[NotionWRF] log_snapshot 실패(격리): {e}")
        return False


def update_snapshots(symbol: str, label_map: dict) -> int:
    """PENDING 스냅샷 행에 파생라벨 백필. label_map: {snapshot_id: {라벨...}}.

    라벨 dict 키: ret_4h/12h/24h/48h/72h, exret_24h, mfe, mae, path_eff,
    tt_peak, tt_trough, class_24h, class_72h, outcome(DONE/EXPIRED).
    main(score 모드)이 analysis.labels로 파생해 넘긴다. (Notion은 핵심만 보관)
    """
    if not enabled() or not label_map:
        return 0
    try:
        db = ensure_snapshots_db()
        if not db:
            return 0
        res = _request("POST", f"/databases/{db}/query", {
            "filter": {"and": [
                {"property": "Symbol", "select": {"equals": symbol}},
                {"property": "Outcome", "select": {"equals": "PENDING"}}]}, "page_size": 100})
        if not res:
            return 0
        updated = 0
        for page in res.get("results", []):
            sid = _get_txt(page.get("properties", {}), "Snapshot ID")
            lab = label_map.get(sid)
            if not lab:
                continue
            props = {"Outcome": _p_sel(lab.get("outcome", "DONE"))}
            for h in (4, 12, 24, 48, 72):
                if lab.get(f"ret_{h}h") is not None:
                    props[f"Ret {h}h"] = _p_num(lab[f"ret_{h}h"])
            for k, col in [("exret_24h", "exRet 24h"), ("mfe", "MFE"), ("mae", "MAE"),
                           ("path_eff", "Path Eff"), ("tt_peak", "TT Peak"),
                           ("tt_trough", "TT Trough")]:
                if lab.get(k) is not None:
                    props[col] = _p_num(lab[k])
            if lab.get("class_24h"):
                props["Class 24h"] = _p_sel(lab["class_24h"])
            if lab.get("class_72h"):
                props["Class 72h"] = _p_sel(lab["class_72h"])
            if _request("PATCH", f"/pages/{page['id']}", {"properties": props}):
                updated += 1
        if updated:
            logger.info(f"[NotionWRF] 🏷️ 스냅샷 라벨 백필 {symbol}: {updated}건")
        return updated
    except Exception as e:  # pragma: no cover
        logger.warning(f"[NotionWRF] update_snapshots 실패(격리): {e}")
        return 0
