"""WRF Notion 로거 — 2 DB(REST 직접). NOTION_TOKEN 미설정 시 자동 no-op.

  DB1 WRF Signals   : 발사된 페이퍼 트레이드 (OPEN→WIN/LOSS/TIMEOUT 자동판정)
  DB2 WRF Snapshots : 매시간 학습 미러(사람뷰) — 핵심 L1 + 파생라벨(필터·그룹용)

원시 72h 경로 전체는 git JSONL이 보관. Notion은 필터·그룹용 핵심만 둔다.
라이브 본체와 격리되도록 모든 함수가 enabled() 가드 + 예외 흡수한다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

try:
    import config
    from notion_logger import (_request, _p_num, _p_sel, _p_txt, _p_title,
                               _p_date, _get_num, _get_sel, _get_date, _get_txt)
except ImportError:  # pragma: no cover
    from src import config
    from src.notion_logger import (_request, _p_num, _p_sel, _p_txt, _p_title,
                                   _p_date, _get_num, _get_sel, _get_date, _get_txt)

logger = logging.getLogger(__name__)

_SIG_CACHE = None
_SNAP_CACHE = None

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
    "Exit Reason": {"select": {"options": [{"name": n} for n in ("TP_HIT", "SL_HIT", "TIMEOUT", "OPEN")]}},
    "Signaled At": {"date": {}}, "Resolved At": {"date": {}},
    "Reason": {"rich_text": {}}, "Signal ID": {"rich_text": {}},
}

SNAP_NUM = ["RSI", "RSI 4H", "RSI 1D", "BB %b", "Dist VWAP ATR", "Dist EMA20 ATR",
            "ATR %", "ADX", "MACD", "Funding", "OI Chg", "LS Long", "Taker Buy",
            "Smart Div", "Vol Ratio", "Confluence L", "Confluence S",
            "Ret 4h", "Ret 12h", "Ret 24h", "Ret 48h", "Ret 72h", "exRet 24h",
            "MFE", "MAE", "Path Eff", "TT Peak", "TT Trough", "Candidates", "Fired"]
SNAP_SEL = {
    "Symbol": [{"name": n} for n in ("BTC/USDT", "ETH/USDT", "HYPE/USDT", "SOL/USDT", "SUI/USDT", "XRP/USDT")],
    "Outcome": [{"name": "PENDING", "color": "gray"}, {"name": "DONE", "color": "green"}, {"name": "EXPIRED", "color": "brown"}],
    "BTC Macro": _MACRO_OPTS, "Regime 1H": _REGIME_OPTS, "Regime 4H": _REGIME_OPTS,
    "Bias 1D": [{"name": n} for n in ("BULL", "BEAR", "NEUTRAL")],
    "RSI Zone": [{"name": n} for n in ("OS", "MID", "OB")],
    "Vol Zone": [{"name": n} for n in ("SQUEEZE", "NORMAL", "EXPANDED")],
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
            "Exit Reason": _p_sel("OPEN"), "Signaled At": _p_date(engine_out["ts"]),
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
    """실제 캔들로 OPEN 신호 판정. 반환 (status, exit_reason, mfe_r, mae_r, bars, resolved_dt)."""
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
        if sl_hit and tp_hit:
            return ("LOSS", "SL_HIT", mfe, mae, i + 1, rdt)
        if sl_hit:
            return ("LOSS", "SL_HIT", mfe, mae, i + 1, rdt)
        if tp_hit:
            return ("WIN", "TP_HIT", mfe, mae, i + 1, rdt)
    # 타임스톱 도달 → TIMEOUT으로 두지 않고 진입가 대비 손익부호로 WIN/LOSS 판별.
    # (TP/SL 미터치라도 t_max 경과 시 시장가 청산 가정. 청산 사유는 EXPIRED_*.)
    if len(fut) >= int(t_max):
        last = fut.iloc[int(t_max) - 1]
        realized = (float(last["close"]) - entry) if long else (entry - float(last["close"]))
        win = realized >= 0
        return ("WIN" if win else "LOSS",
                "EXPIRED_WIN" if win else "EXPIRED_LOSS",
                mfe, mae, int(t_max), last.name.isoformat())
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
            status, reason, mfe, mae, bars, rdt = out
            _request("PATCH", f"/pages/{page['id']}", {"properties": {
                "Status": _p_sel(status), "Exit Reason": _p_sel(reason),
                "MFE R": _p_num(round(mfe, 3)), "MAE R": _p_num(round(mae, 3)),
                "Bars To Exit": _p_num(bars), "Resolved At": _p_date(rdt)}})
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
            "Name": _p_title(f"{sym} {engine_out['ts'][:16]}"),
            "TS": _p_date(engine_out["ts"]), "Symbol": _p_sel(sym),
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
            "MACD": _p_num(raw.get("macd")), "Funding": _p_num(raw.get("funding")),
            "OI Chg": _p_num(raw.get("oi_chg")), "LS Long": _p_num(raw.get("ls_long")),
            "Taker Buy": _p_num(raw.get("taker_buy")), "Smart Div": _p_num(raw.get("smart_div")),
            "Vol Ratio": _p_num(raw.get("vol_ratio")),
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
