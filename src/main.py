"""main.py — WRF-4 진입점 (페이퍼 전용·무상태).

모드:
  signal (기본, 매시 :05) — 수집 → 측정 → btc_macro → 엔진(L0~L4) → 발사(페이퍼)
                            → schema v3 스냅샷 적재 → Notion 미러. ALERT_ENABLED 시 알림.
  score  (매 :*/15)       — 성숙 경로 채움(JSONL) + triple-barrier 신호판정(Notion)
                            + 스냅샷 파생라벨 백필.

라이브 본체는 절대 학습하지 않는다(calibration_table.json만 읽음). 엔진 전체가
try/except로 격리되어, 분석/로깅 실패가 프로세스를 죽이지 않는다.
"""
import argparse
import logging
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(__file__))

import config
from data_pipeline import create_exchange, collect, collect_ohlcv
from analysis_engine import run_full_analysis
from notification import send_message, send_error_alert

from wrf import engine as wrf_engine
from wrf import schema as wrf_schema
from wrf import logger as wrf_logger
from wrf import notion_wrf
from wrf.btc_macro import classify_btc_macro

logger = logging.getLogger(__name__)


def setup_logging():
    fmt = logging.Formatter("%(asctime)s [%(levelname)-7s] %(name)s — %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(getattr(logging, getattr(config, "LOG_LEVEL", "INFO"), logging.INFO))
    if not root.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        root.addHandler(ch)
        try:
            log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
            os.makedirs(log_dir, exist_ok=True)
            fh = logging.FileHandler(os.path.join(log_dir, "bot.log"), encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except Exception:
            pass


def _btc_macro_for(symbol: str, exchange, own_ohlcv: dict) -> str:
    """심볼이 BTC면 자기 1D, 아니면 BTC/USDT 1D를 별도 수집해 거시방향 태깅."""
    try:
        if symbol == "BTC/USDT":
            return classify_btc_macro(own_ohlcv.get("1d"))
        btc = collect_ohlcv(exchange, "BTC/USDT")
        return classify_btc_macro(btc.get("1d"))
    except Exception as e:
        logger.warning(f"[main] btc_macro 수집 실패 → CHOP: {e}")
        return "CHOP"


def _alert(cand: dict, engine_out: dict):
    """ALERT_ENABLED일 때만 텔레그램 발송(학습기간엔 OFF·기록만)."""
    if not getattr(config, "ALERT_ENABLED", False):
        return
    ctx = engine_out["ctx"]
    arrow = "🟢 LONG" if cand["dir"] == "long" else "🔴 SHORT"
    msg = (
        f"<b>[WRF-4] {engine_out['symbol']} {cand['setup']} {arrow}</b>\n"
        f"P̂ = <b>{cand['p_hat']:.2f}</b> ({cand['p_source']}) ≥ floor {cand['win_floor']:.2f}\n"
        f"Regime {ctx.get('regime_1h')}/{ctx.get('regime_4h')} · Macro {ctx.get('btc_macro')}\n"
        f"Entry {cand['entry']} · TP {cand['tp']} · SL {cand['sl']} · RR {cand['rr']}\n"
        f"Size {cand['size']} · {cand.get('reason', '')}")
    try:
        send_message(msg)
    except Exception as e:
        logger.warning(f"[main] 알림 실패(격리): {e}")


def run_signal(symbol: str, exchange) -> None:
    """signal 모드: 한 심볼 전체 파이프라인. 엔진 본체는 try/except 격리."""
    collected = collect(exchange, symbol)
    ohlcv = collected.get("ohlcv", {})
    ticker = collected.get("ticker") or {}
    if not ticker.get("available"):
        # OKX 티커 단발 실패(타임아웃)로 전체 파이프라인을 버리지 않는다. 티커의 유일
        # 필수값은 현재가이고, OHLCV(1h) 마지막 종가로 대체 가능(features도 동일 폴백).
        # 진짜로 OHLCV조차 없을 때만 skip → 학습데이터 구멍 방지.
        df1h = (ohlcv or {}).get("1h")
        if df1h is not None and len(df1h) > 0:
            last = float(df1h["close"].iloc[-1])
            collected["ticker"] = {"last": last, "open": last, "change_pct": 0.0,
                                   "available": True, "synthesized": True}
            ticker = collected["ticker"]
            logger.warning(f"[main] {symbol} 티커 불가 → 1H 종가 {last}로 대체 진행")
        else:
            logger.warning(f"[main] {symbol} 티커·OHLCV 모두 불가 — skip")
            return

    try:
        measures = run_full_analysis(symbol, collected)
        # 펀딩 백분위 입력 주입(있으면)
        fh = (collected.get("funding_history") or {}).get("rates")
        if fh:
            measures["_funding_hist_rates"] = fh

        btc_macro = _btc_macro_for(symbol, exchange, ohlcv)
        out = wrf_engine.run_engine(symbol, measures, ohlcv, collected, btc_macro)

        logger.info(
            f"[WRF] {symbol} {out['ctx']['fp_key']} | 후보 {len(out['candidates'])} "
            f"발사 {len(out['fired'])} | 전역베토 {out['global_veto']}")

        # schema v3 스냅샷 적재(전량 기록) + 경로 캡처
        row = wrf_schema.build_row(out)
        wrf_logger.record_snapshot(row)
        wrf_logger.capture_paths(symbol, ohlcv.get("1h"))

        # Notion 미러 + OPEN 신호 판정
        notion_wrf.log_snapshot(out)
        notion_wrf.evaluate_open_signals(symbol, ohlcv.get("1h"))

        # 발사(페이퍼): Notion 기록 + (ALERT 시) 알림
        for cand in out["fired"]:
            notion_wrf.log_signal(cand, out)
            _alert(cand, out)
    except Exception as e:
        logger.error(f"[main] {symbol} 엔진 실패(격리): {e}\n{traceback.format_exc()}")


def run_score(symbol: str, exchange) -> None:
    """score 모드: 성숙 경로 채움 + 신호판정 + 스냅샷 라벨 백필."""
    ohlcv = collect_ohlcv(exchange, symbol)
    df_1h = ohlcv.get("1h")
    try:
        n = wrf_logger.capture_paths(symbol, df_1h)
        logger.info(f"[score] {symbol} 경로 캡처 {n}건")
        notion_wrf.evaluate_open_signals(symbol, df_1h)
        _backfill_snapshot_labels(symbol)
    except Exception as e:
        logger.error(f"[score] {symbol} 실패(격리): {e}\n{traceback.format_exc()}")


def _backfill_snapshot_labels(symbol: str) -> None:
    """JSONL(경로 포함) → 파생라벨 → Notion 스냅샷 백필."""
    if not notion_wrf.enabled():
        return
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "analysis"))
        import build_dataset as bd
        import labels as lab
        rows = bd.load_snapshots(getattr(config, "RESEARCH_DATA_DIR", "data/research"),
                                 symbols=[symbol])
        btc_rows = bd.load_snapshots(getattr(config, "RESEARCH_DATA_DIR", "data/research"))
        btc_map = lab.build_btc_ret_map(btc_rows)
        label_map = {}
        for r in rows:
            path = r.get("path")
            if not path or not path.get("c"):
                continue
            ts = r.get("ts")
            ld = {}
            for h in (4, 12, 24, 48, 72):
                ld[f"ret_{h}h"] = bd.fwd_ret(path, h)
            ld["exret_24h"] = lab.exret(path, ts, btc_map, 24)
            mfe, mae = bd.mfe_mae(path, k=72)
            ld["mfe"], ld["mae"] = mfe, mae
            ld["path_eff"] = bd.path_efficiency(path)
            ttp, ttt = bd.time_to_extreme(path)
            ld["tt_peak"], ld["tt_trough"] = ttp, ttt
            ld["class_24h"] = lab.classify(ld["exret_24h"])
            ex72 = lab.exret(path, ts, btc_map, 72)
            ld["class_72h"] = lab.classify(ex72)
            ld["outcome"] = ("DONE" if path.get("complete")
                             else "EXPIRED" if path.get("expired")
                             else "PENDING")  # 미완성·미유실 → PENDING 유지(후속 백필 대상)
            label_map[r.get("snapshot_id")] = ld
        notion_wrf.update_snapshots(symbol, label_map)
    except Exception as e:
        logger.warning(f"[score] 스냅샷 라벨 백필 실패(격리): {e}")


def main():
    setup_logging()
    ap = argparse.ArgumentParser(description="WRF-4 봇")
    ap.add_argument("--mode", choices=["signal", "score"], default="signal")
    ap.add_argument("--symbol", default=os.getenv("SINGLE_SYMBOL", ""))
    args = ap.parse_args()

    symbols = [args.symbol] if args.symbol else getattr(config, "SYMBOLS", ["BTC/USDT"])
    t0 = time.time()
    logger.info(f"{'─' * 50}\n🤖 WRF-4 [{args.mode}] 심볼={symbols} "
                f"ALERT={getattr(config, 'ALERT_ENABLED', False)}")
    try:
        exchange = create_exchange()
    except Exception as e:
        logger.error(f"[main] 거래소 초기화 실패: {e}")
        try:
            send_error_alert(str(e), "WRF create_exchange")
        except Exception:
            pass
        sys.exit(1)

    for sym in symbols:
        if args.mode == "signal":
            run_signal(sym, exchange)
        else:
            run_score(sym, exchange)

    logger.info(f"✅ WRF-4 [{args.mode}] 완료 — {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
