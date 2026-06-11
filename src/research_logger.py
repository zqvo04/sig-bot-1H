"""
research_logger.py — 상태 중심 학습 데이터 적재 (1h Bot)
────────────────────────────────────────────────────────────────────
목적:
  신호 발생 여부와 **무관하게** 매시간을 1표본으로 보고
  (시장 상태 스냅샷, 이후 72h 차트 경로)를 JSONL에 적재한다.
  "이런 상황에서 N시간 뒤 차트가 어떻게 움직였나"를 어떤 정의로든
  사후(오프라인)에 분석/학습할 수 있게 하는 것이 목표.

2단계 파이프라인 (매 실행):
  ① record_snapshot()  — 마감/현재 봉 기준 상태 벡터를 1행 append (path=null)
  ② capture_paths()    — ts 이후 72개 캔들이 확보된 미캡처 행에 close/high/low
                         상대 경로를 채움 (라벨은 박제하지 않고 경로 자체를 저장)

설계 원칙:
  · 피처는 점수 산출 *이전*의 원시 지표만 (봇 점수/임계값은 참고 메타 L3로 격리)
  · 결과는 72h 전체 경로 → 임의 호라이즌·임의 TP/SL을 오프라인에서 무한 재정의
  · 멱등(snapshot_id = symbol+봉시각) · 상태파일 무의존 · 봇 본체와 try/except 격리

저장: data/research/{SYMBOL}/{YYYY-MM}.jsonl  (심볼별 파일 → 병렬 잡 충돌 차단)
상세: docs/LEARNING_DATA_DESIGN.md
"""
import os
import json
import logging
from datetime import timezone

import pandas as pd

import config

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# 활성화 / 경로
# ════════════════════════════════════════════════════════════════════

def enabled() -> bool:
    env = os.getenv("RESEARCH_LOGGER_ENABLED")
    if env is not None:
        return env not in ("0", "false", "False", "")
    return bool(getattr(config, "RESEARCH_LOGGER_ENABLED", False))


def _base_dir() -> str:
    # repo 루트 = src/ 의 부모
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(root, getattr(config, "RESEARCH_DATA_DIR", "data/research"))


def _sym_slug(symbol: str) -> str:
    return symbol.replace("/", "-")


def _month_file(symbol: str, ts: pd.Timestamp) -> str:
    d = os.path.join(_base_dir(), _sym_slug(symbol))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{ts.strftime('%Y-%m')}.jsonl")


# ════════════════════════════════════════════════════════════════════
# 인코딩 헬퍼
# ════════════════════════════════════════════════════════════════════

def _sign(bull, bear) -> int:
    """방향성 이벤트 → +1(롱방향)/−1(숏방향)/0(없음)."""
    if bull and not bear:
        return 1
    if bear and not bull:
        return -1
    return 0


def _ema_code(sig: str) -> int:
    return 1 if sig == "bullish" else -1 if sig == "bearish" else 0


def _f(v):
    """None/숫자 안전 변환 (JSON 직렬화용)."""
    if v is None:
        return None
    try:
        return round(float(v), 6)
    except (TypeError, ValueError):
        return None


def _rsi_zone(v) -> str:
    lo, hi = getattr(config, "RESEARCH_FP_RSI_ZONES", (35.0, 65.0))
    if v is None:
        return "NA"
    return "OS" if v < lo else "OB" if v > hi else "MID"


def _vol_zone(width, avg) -> str:
    if not width or not avg or avg <= 0:
        return "NA"
    r = width / avg
    if r < getattr(config, "RESEARCH_FP_VOL_SQUEEZE", 0.85):
        return "SQUEEZE"
    if r > getattr(config, "RESEARCH_FP_VOL_EXPAND", 1.20):
        return "EXPANDED"
    return "NORMAL"


# ════════════════════════════════════════════════════════════════════
# 상태 벡터 빌드 (L1 원시피처 + L2 지문 + L3 참고메타)
# ════════════════════════════════════════════════════════════════════

def build_state(symbol: str, analysis: dict, pipeline: dict, collected: dict) -> dict:
    a = analysis or {}
    p = pipeline or {}

    df_1h = (collected or {}).get("ohlcv", {}).get("1h")
    if df_1h is None or len(df_1h) == 0:
        raise ValueError("1h OHLCV 없음 — 스냅샷 불가")
    last_bar_ts = df_1h.index[-1].tz_convert(timezone.utc)
    p0 = _f(a.get("current_price")) or _f(df_1h["close"].iloc[-1])

    rsi   = a.get("rsi", {})
    bb    = a.get("bollinger", {})
    adx   = a.get("adx_1h", {})
    adx4  = a.get("adx_4h", {})
    atr   = a.get("atr", {})
    macd  = a.get("macd_1h", {})
    vol   = a.get("volume", {})
    ema_l = a.get("ema_long", {}).get("tf_signals", {})
    bos   = a.get("bos_choch", {})
    bos4  = a.get("bos_choch_4h", {})
    fvg   = a.get("fvg", {})
    ob    = a.get("order_blocks", {})
    fib   = a.get("fibonacci", {})
    wk    = a.get("weekly_levels", {})
    retr  = a.get("retracement", {})
    mat   = a.get("maturity", {})
    ms    = a.get("market_structure", {})
    c1h   = a.get("candle_pattern", {})
    c4h   = a.get("candle_pattern_4h", {})
    c1d   = a.get("candle_pattern_1d", {})
    vpd   = a.get("vol_price_div", {})
    fund  = a.get("funding_rate", {})
    ftr   = a.get("funding_trend", {})
    lsr   = a.get("ls_ratio", {})
    tak   = a.get("taker_volume", {})
    oim   = a.get("oi_matrix", {})
    sm    = a.get("smart_money", {})
    liq   = a.get("liquidations", {})
    regime   = a.get("regime", {})
    regime4  = a.get("regime_4h", {})
    dbias    = a.get("daily_bias", {})

    # ── L1: 원시 피처 (점수 이전 단계) ──────────────────────────────
    f = {
        # 가격/변동성
        "atr_pct":      _f(atr.get("pct")),
        "atr_ratio":    _f(atr.get("ratio")),
        "atr_expanding": bool(atr.get("expanding", False)),
        # 모멘텀/추세
        "rsi_1h":       _f(rsi.get("value_1h")),
        "rsi_4h":       _f(rsi.get("value_4h")),
        "rsi_1d":       _f(rsi.get("value_1d")),
        "rsi_1d_slope": _f(rsi.get("value_1d_slope")),
        "rsi_weighted": _f(rsi.get("value_weighted")),
        "bb_pos":       _f(bb.get("pct_b")),
        "bb_width":     _f(bb.get("band_width")),
        "bb_avg_width": _f(bb.get("avg_band_width")),
        "bb_squeeze":   bool(bb.get("squeeze", False)),
        "ma20_slope_sign": int(bb.get("ma20_slope_sign", 0) or 0),
        "adx":          _f(adx.get("adx")),
        "adx_slope":    _f(adx.get("adx_slope")),
        "plus_di":      _f(adx.get("plus_di")),
        "minus_di":     _f(adx.get("minus_di")),
        "adx_4h":       _f(adx4.get("adx")),
        "ema_1h":       _ema_code(ema_l.get("1h", "neutral")),
        "ema_4h":       _ema_code(ema_l.get("4h", "neutral")),
        "ema_1d":       _ema_code(ema_l.get("1d", "neutral")),
        "macd_hist":    _f(macd.get("histogram")),
        "macd_bull":    bool(macd.get("bullish", False)),
        "macd_bear":    bool(macd.get("bearish", False)),
        "macd_cross":   _sign(macd.get("cross_up"), macd.get("cross_down")),
        "volume_ratio": _f(vol.get("ratio")),
        # 구조 (SMC) — 부호 인코딩
        "bos":          _sign(bos.get("bos_bullish"), bos.get("bos_bearish")),
        "choch":        _sign(bos.get("choch_bullish"), bos.get("choch_bearish")),
        "bos_4h":       _sign(bos4.get("bos_bullish"), bos4.get("bos_bearish")),
        "choch_4h":     _sign(bos4.get("choch_bullish"), bos4.get("choch_bearish")),
        "fvg":          _sign(fvg.get("in_bullish_fvg"), fvg.get("in_bearish_fvg")),
        "order_block":  _sign(ob.get("in_bullish_ob"), ob.get("in_bearish_ob")),
        "ob_strength":  _f(ob.get("ob_strength")),
        "fib_gp":       _sign(fib.get("in_golden_pocket_long"), fib.get("in_golden_pocket_short")),
        "fib_key":      _sign(fib.get("near_key_level_long"), fib.get("near_key_level_short")),
        "weekly_lvl":   _sign(wk.get("near_level") and not wk.get("is_resistance"),
                              wk.get("near_level") and wk.get("is_resistance")),
        "retrace_long_zone":  retr.get("long_zone", "none"),
        "retrace_short_zone": retr.get("short_zone", "none"),
        "maturity":     mat.get("maturity", "none"),
        "maturity_net": int(mat.get("bull_count", 0) or 0) - int(mat.get("bear_count", 0) or 0),
        "struct":       _sign(ms.get("higher_low"), ms.get("lower_high")),
        "failed_break": _sign(ms.get("failed_breakdown"), ms.get("failed_breakout")),
        "candle_1h":    _sign(c1h.get("bullish_pin") or c1h.get("bullish_engulf"),
                              c1h.get("bearish_pin") or c1h.get("bearish_engulf")),
        "candle_4h":    _sign(c4h.get("bullish_pin") or c4h.get("bullish_engulf"),
                              c4h.get("bearish_pin") or c4h.get("bearish_engulf")),
        "candle_1d":    _sign(c1d.get("bullish_pin") or c1d.get("bullish_engulf"),
                              c1d.get("bearish_pin") or c1d.get("bearish_engulf")),
        "vol_div":      _sign(vpd.get("bullish_vol_div"), vpd.get("bearish_vol_div")),
        # 심리/포지셔닝
        "funding":      _f(fund.get("rate")),
        "funding_bias": fund.get("bias", "neutral"),
        "funding_signal": ftr.get("signal", "neutral"),
        "ls_long_pct":  _f(lsr.get("long_pct")),
        "ls_bias":      lsr.get("bias", "neutral"),
        "taker_buy":    _f(tak.get("buy_ratio")),
        "taker_bias":   tak.get("bias", "neutral"),
        "oi_change":    _f(oim.get("oi_change_pct")),
        "oi_slope":     _f(oim.get("oi_slope")),
        "oi_slope_sign": int(oim.get("oi_slope_sign", 0) or 0),
        "oi_quadrant":  oim.get("quadrant", "neutral"),
        "smart_div":    _f(sm.get("divergence")),
        "smart_dir":    sm.get("smart_direction", "neutral"),
        "liq_signal":   liq.get("signal", "none"),
        "liq_fav":      liq.get("favorable_direction"),
        # 시간
        "hour_utc":     int(last_bar_ts.hour),
        "dow":          int(last_bar_ts.weekday()),
    }

    # ── L2: 상황 지문 (group-by 편의 키) ────────────────────────────
    r1 = regime.get("regime", "UNKNOWN")
    r4 = regime4.get("regime", "UNKNOWN")
    bd = dbias.get("bias", "NEUTRAL")
    rz = _rsi_zone(f.get("rsi_1h"))
    vz = _vol_zone(f.get("bb_width"), f.get("bb_avg_width"))
    fp = {
        "regime_1h": r1, "regime_4h": r4, "bias_1d": bd,
        "rsi_zone": rz, "vol_zone": vz,
        "key": f"{r1}|{r4}|{bd}|{rz}|{vz}",
    }

    # ── L3: 참고 메타 (학습 입력 아님 — 봇 로직 대조용) ─────────────
    sig = p.get("signal_result", {})
    sl_ = sig.get("long", {})
    ss_ = sig.get("short", {})
    meta = {
        "score_long":  _f(sl_.get("final_score")),
        "score_short": _f(ss_.get("final_score")),
        "thr_long":    _f(sl_.get("regime_threshold")),
        "thr_short":   _f(ss_.get("regime_threshold")),
        "signal_fired": bool(p.get("should_notify", False)),
        "direction":   p.get("direction"),
        "cooldown_skip": bool(p.get("cooldown_skip", False)),
        "levels":      p.get("levels", {}),
    }

    return {
        "snapshot_id":     f"{symbol}_{last_bar_ts.isoformat()}",
        "ts":              last_bar_ts.isoformat(),
        "symbol":          symbol,
        "feature_version": getattr(config, "RESEARCH_FEATURE_VERSION", 1),
        "p0":              p0,
        "f":               f,
        "fp":              fp,
        "meta":            meta,
        "path":            None,
    }


# ════════════════════════════════════════════════════════════════════
# Phase A — 스냅샷 기록 (멱등 append)
# ════════════════════════════════════════════════════════════════════

def _existing_ids(path: str) -> set:
    ids = set()
    if not os.path.exists(path):
        return ids
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ids.add(json.loads(line).get("snapshot_id"))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning(f"[Research] 기존 id 스캔 실패: {e}")
    return ids


def record_snapshot(state: dict) -> bool:
    """상태 1행을 월별 JSONL에 append. 같은 snapshot_id 존재 시 skip(멱등)."""
    ts = pd.Timestamp(state["ts"])
    path = _month_file(state["symbol"], ts)
    if state["snapshot_id"] in _existing_ids(path):
        logger.debug(f"[Research] 중복 스냅샷 skip: {state['snapshot_id']}")
        return False
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(state, ensure_ascii=False) + "\n")
    logger.info(f"[Research] 📸 스냅샷 기록 {state['symbol']} @ {state['ts']} ({state['fp']['key']})")
    return True


# ════════════════════════════════════════════════════════════════════
# Phase B — 경로 캡처 (성숙한 미캡처 행에 72h close/high/low 경로 기록)
# ════════════════════════════════════════════════════════════════════

def _compute_path(p0: float, seg: pd.DataFrame) -> dict:
    if not p0 or p0 <= 0:
        return None
    rnd = getattr(config, "RESEARCH_PATH_ROUND", 6)
    c = [round(float(x) / p0 - 1.0, rnd) for x in seg["close"].values]
    h = [round(float(x) / p0 - 1.0, rnd) for x in seg["high"].values]
    l = [round(float(x) / p0 - 1.0, rnd) for x in seg["low"].values]
    return {"n": len(c), "c": c, "h": h, "l": l}


def _label_file(path: str, df_1h: pd.DataFrame, horizon: int) -> int:
    """한 월별 파일의 미캡처 행을 검사해 경로를 채운다. 갱신 행 수 반환."""
    if not os.path.exists(path):
        return 0
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except Exception as e:
        logger.warning(f"[Research] 파일 읽기 실패 {path}: {e}")
        return 0

    updated = 0
    for row in rows:
        if row.get("path") is not None:
            continue
        ts = pd.Timestamp(row["ts"])
        later = df_1h[df_1h.index > ts]          # 스냅샷 봉 이후(미래) 캔들만
        if len(later) < horizon:
            continue                              # 아직 미성숙
        # 정합성 가드: 첫 미래봉이 스냅샷 직후(약 1h)여야 함.
        # 윈도가 슬라이드해 초기 경로가 유실된 고아 행은 경로 기록 불가로 표기.
        gap_h = (later.index[0] - ts).total_seconds() / 3600.0
        if gap_h > horizon:
            row["path"] = {"n": 0, "c": [], "h": [], "l": [], "expired": True}
            updated += 1
            continue
        seg = later.iloc[:horizon]
        pth = _compute_path(row.get("p0"), seg)
        if pth is None:
            continue
        pth["captured_at"] = pd.Timestamp.now(tz=timezone.utc).isoformat()
        row["path"] = pth
        updated += 1

    if updated:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        logger.info(f"[Research] 🏷️ 경로 캡처 {updated}건 — {os.path.basename(path)}")
    return updated


def capture_paths(symbol: str, df_1h: pd.DataFrame) -> int:
    """심볼의 최근 월별 파일(당월+전월)에서 성숙한 행의 경로를 채운다."""
    if df_1h is None or len(df_1h) == 0:
        return 0
    horizon = getattr(config, "RESEARCH_PATH_HOURS", 72)
    sym_dir = os.path.join(_base_dir(), _sym_slug(symbol))
    if not os.path.isdir(sym_dir):
        return 0
    files = sorted(f for f in os.listdir(sym_dir) if f.endswith(".jsonl"))
    total = 0
    for fname in files[-2:]:                      # 당월+전월이면 충분(72h≪한달)
        total += _label_file(os.path.join(sym_dir, fname), df_1h, horizon)
    return total
