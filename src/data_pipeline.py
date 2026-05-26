"""
data_pipeline.py — OKX 선물 데이터 수집 파이프라인 (1h Bot v2.0)
──────────────────────────────────────────────────────────────────────
[1h Bot 변경]

★ CANDLE_LIMITS 자동 반영
  config.CANDLE_LIMITS = {"1h": 250, "4h": 210, "1d": 100}
  collect_ohlcv()는 이 dict를 그대로 순회 → 1d 캔들 자동 수집

★ collect_ls_ratio: period "1h" → "4h"
  1h 봇의 mid TF = 4h이므로 롱숏 비율도 4h 기간으로 수집
  (더 안정적인 포지션 비율 반영)

★ collect_taker_volume: period "5m" 유지
  미시구조 분석용, TF 변경 불필요

★ collect_all_data: SINGLE_SYMBOL flat dict 반환 유지
  main.py 호환성 유지

★ 마이크로구조: fetch_all_microstructure() 무변경
  5m OHLCV + 호가창 기반 → entry TF와 무관
──────────────────────────────────────────────────────────────────────
"""

import logging
import os
import time
from typing import Optional, Dict

import pandas as pd
import requests
import ccxt

import sys
sys.path.insert(0, os.path.dirname(__file__))

import config
from microstructure_analyzer import fetch_all_microstructure

logger = logging.getLogger(__name__)

OKX_BASE = "https://www.okx.com/api/v5"


# ════════════════════════════════════════════════════════════════════
# OKX 공개 API 직접 호출 헬퍼
# ════════════════════════════════════════════════════════════════════

def _okx_get(path: str, params: dict = None) -> dict:
    try:
        r = requests.get(
            f"{OKX_BASE}{path}",
            params=params or {},
            timeout=10,
            headers={"Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"[OKX-HTTP] {path} 실패: {e}")
        return {"code": "error", "data": [], "msg": str(e)}


# ════════════════════════════════════════════════════════════════════
# 거래소 초기화
# ════════════════════════════════════════════════════════════════════

def create_exchange() -> ccxt.okx:
    return ccxt.okx({
        "apiKey":          config.OKX_API_KEY,
        "secret":          config.OKX_API_SECRET,
        "password":        config.OKX_PASSPHRASE,
        "enableRateLimit": True,
        "options":         {"defaultType": "swap"},
    })


# ════════════════════════════════════════════════════════════════════
# 심볼 변환 유틸리티
# ════════════════════════════════════════════════════════════════════

def _to_ccxt_swap(symbol: str) -> str:
    """BTC/USDT → BTC/USDT:USDT"""
    if ":" in symbol:
        return symbol
    parts = symbol.split("/")
    return f"{parts[0]}/{parts[1]}:{parts[1]}" if len(parts) == 2 else symbol

def _to_base_id(symbol: str) -> str:
    """BTC/USDT → BTC-USDT"""
    return symbol.replace("/", "-").split(":")[0]

def _to_swap_id(symbol: str) -> str:
    """BTC/USDT → BTC-USDT-SWAP"""
    return _to_base_id(symbol) + "-SWAP"

def _to_ccy(symbol: str) -> str:
    """BTC/USDT → BTC"""
    return symbol.split("/")[0]

def _ohlcv_to_df(ohlcv_list: list) -> pd.DataFrame:
    if not ohlcv_list:
        return pd.DataFrame()
    df = pd.DataFrame(
        ohlcv_list,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["close"])


# ════════════════════════════════════════════════════════════════════
# 1. OHLCV (config.CANDLE_LIMITS 자동 반영 → 1h/4h/1d 수집)
# ════════════════════════════════════════════════════════════════════

def collect_ohlcv(exchange: ccxt.okx, symbol: str) -> Dict[str, pd.DataFrame]:
    """
    config.CANDLE_LIMITS = {"1h": 250, "4h": 210, "1d": 100} 자동 순회
    1h Bot: entry=1h, mid=4h, macro=1d 전부 수집
    """
    swap = _to_ccxt_swap(symbol)
    result = {}
    for tf, limit in config.CANDLE_LIMITS.items():
        for attempt in range(config.MAX_RETRIES):
            try:
                raw = exchange.fetch_ohlcv(swap, tf, limit=limit)
                df  = _ohlcv_to_df(raw)
                result[tf] = df
                logger.info(f"  ✅ {symbol} [{tf}] {len(df)}개")
                break
            except ccxt.RateLimitExceeded:
                time.sleep(config.RETRY_DELAY_S * (attempt + 2))
            except Exception as e:
                if attempt < config.MAX_RETRIES - 1:
                    time.sleep(config.RETRY_DELAY_S)
                else:
                    logger.warning(f"  ❌ {symbol} [{tf}] OHLCV 실패: {e}")
                    result[tf] = pd.DataFrame()
    return result


# ════════════════════════════════════════════════════════════════════
# 2. 펀딩비
# ════════════════════════════════════════════════════════════════════

def collect_funding_rate(exchange: ccxt.okx, symbol: str) -> Optional[dict]:
    try:
        fr        = exchange.fetch_funding_rate(_to_ccxt_swap(symbol))
        rate      = float(fr.get("fundingRate",     0) or 0)
        next_rate = float(fr.get("nextFundingRate", 0) or 0)
        logger.info(f"  💸 {symbol} 펀딩비: {rate*100:+.4f}%")
        return {
            "rate":          rate,
            "rate_pct":      round(rate * 100, 6),
            "next_rate":     next_rate,
            "next_rate_pct": round(next_rate * 100, 6),
        }
    except Exception as e:
        logger.warning(f"  ❌ {symbol} 펀딩비 실패: {e}")
        return None


# ════════════════════════════════════════════════════════════════════
# 3. 롱숏 비율 (1h Bot: period 4h)
# ════════════════════════════════════════════════════════════════════

def collect_ls_ratio(exchange: ccxt.okx, symbol: str) -> dict:
    """
    [1h Bot] period: "1H" → "4H"
    mid TF = 4h이므로 4h 기간 포지션 비율이 더 안정적

    3단계 폴백:
      1) CCXT fetch_long_short_ratio
      2) publicGetRubikStatContractsLongShortAccountRatio
      3) _okx_get /rubik/stat/contracts/long-short-pos-ratio
    """
    _neutral    = {"available": False, "long_pct": 0.5, "short_pct": 0.5, "ratio": 1.0}
    swap_symbol = _to_ccxt_swap(symbol)
    swap_exchange = getattr(exchange, "_swap", exchange)

    # 1단계: CCXT
    try:
        data = swap_exchange.fetch_long_short_ratio(swap_symbol, "4h", limit=1)
        if data and len(data) > 0:
            ls_ratio  = float(data[-1].get("longShortRatio", 1.0))
            long_pct  = ls_ratio / (1.0 + ls_ratio)
            short_pct = 1.0 - long_pct
            logger.info(f"  📊 {symbol} 롱숏(CCXT/4h): 롱 {long_pct*100:.1f}% / 숏 {short_pct*100:.1f}%")
            return {"long_pct": round(long_pct,4), "short_pct": round(short_pct,4),
                    "ratio": round(ls_ratio,4), "available": True}
    except AttributeError:
        logger.debug(f"[collect_ls_ratio] CCXT 미지원: {symbol}")
    except Exception as e:
        logger.debug(f"[collect_ls_ratio] CCXT 실패: {e}")

    # 2단계: publicGetRubikStatContractsLongShortAccountRatio
    try:
        result    = exchange.publicGetRubikStatContractsLongShortAccountRatio({
            "ccy": _to_ccy(symbol), "period": "4H", "limit": "1",
        })
        data_list = result.get("data", [])
        if data_list:
            ls        = float(data_list[0][1])
            long_pct  = ls / (1.0 + ls)
            short_pct = 1.0 - long_pct
            logger.info(f"  📊 {symbol} 롱숏(계정비율/4h): 롱 {long_pct*100:.1f}%")
            return {"long_pct": round(long_pct,4), "short_pct": round(short_pct,4),
                    "ratio": round(ls,4), "available": True}
    except AttributeError:
        logger.debug(f"[collect_ls_ratio] publicGetRubikStat... 미지원")
    except Exception as e:
        logger.debug(f"[collect_ls_ratio] 계정비율 폴백 실패: {e}")

    # 3단계: 직접 HTTP
    try:
        resp = _okx_get("/rubik/stat/contracts/long-short-pos-ratio", {
            "ccy": _to_ccy(symbol), "period": "4H", "limit": "1",
        })
        if resp.get("code") == "0" and resp.get("data"):
            ls        = float(resp["data"][0][1])
            long_pct  = ls / (1.0 + ls)
            short_pct = 1.0 - long_pct
            logger.info(f"  📊 {symbol} 롱숏(포지션비율/4h): 롱 {long_pct*100:.1f}%")
            return {"long_pct": round(long_pct,4), "short_pct": round(short_pct,4),
                    "ratio": round(ls,4), "available": True}
    except Exception as e:
        logger.warning(f"  ❌ {symbol} 롱숏비율 전체 실패: {e}")

    return _neutral


# ════════════════════════════════════════════════════════════════════
# 4. Taker 비율 (5m 유지 — 미시구조 분석용)
# ════════════════════════════════════════════════════════════════════

def collect_taker_volume(exchange: ccxt.okx, symbol: str) -> dict:
    empty = {
        "available": False, "buy_ratio": 0.5, "sell_ratio": 0.5,
        "bias": "neutral", "strength": "neutral", "buy_pct": 50.0,
    }
    try:
        resp = _okx_get("/rubik/stat/taker-volume-contract", {
            "instId": _to_swap_id(symbol),
            "period": "5m",
            "limit":  str(min(config.TAKER_LOOKBACK, 100)),
        })
        if resp.get("code") != "0" or not resp.get("data"):
            logger.warning(f"  ⚠️ {symbol} Taker 응답 오류: {resp.get('msg','unknown')}")
            return empty

        n          = min(20, len(resp["data"]))
        total_buy  = sum(float(row[1]) for row in resp["data"][:n])
        total_sell = sum(float(row[2]) for row in resp["data"][:n])
        total      = total_buy + total_sell
        if total <= 0:
            return empty

        buy_r  = total_buy  / total
        sell_r = total_sell / total

        if   buy_r  >= config.TAKER_STRONG_BUY:  bias, strength = "buy_dominant",  "strong"
        elif sell_r >= config.TAKER_STRONG_SELL:  bias, strength = "sell_dominant", "strong"
        elif buy_r  >= 0.55:                       bias, strength = "buy_dominant",  "normal"
        elif sell_r >= 0.55:                       bias, strength = "sell_dominant", "normal"
        else:                                      bias, strength = "neutral",       "neutral"

        logger.info(f"  🔄 {symbol} Taker: 매수 {buy_r*100:.1f}% / 매도 {sell_r*100:.1f}% [{bias}]")
        return {
            "available": True, "buy_ratio": round(buy_r,4), "sell_ratio": round(sell_r,4),
            "bias": bias, "strength": strength, "buy_pct": round(buy_r*100, 2),
        }
    except Exception as e:
        logger.warning(f"  ❌ {symbol} Taker 실패: {e}")
        return empty


# ════════════════════════════════════════════════════════════════════
# 5. 현재가
# ════════════════════════════════════════════════════════════════════

def collect_ticker(exchange: ccxt.okx, symbol: str) -> dict:
    try:
        t        = exchange.fetch_ticker(_to_ccxt_swap(symbol))
        last     = float(t.get("last",  0) or 0)
        open_24h = float(t.get("open",  last) or last)
        change   = ((last - open_24h) / open_24h * 100) if open_24h > 0 else 0.0
        logger.info(f"  💰 {symbol} ${last:,.4f} ({change:+.2f}%)")
        return {"last": last, "open": open_24h, "change_pct": round(change,4), "available": True}
    except Exception as e:
        logger.warning(f"  ❌ {symbol} 티커 실패: {e}")
        return {"last": 0.0, "open": 0.0, "change_pct": 0.0, "available": False}


# ════════════════════════════════════════════════════════════════════
# 단일 심볼 수집
# ════════════════════════════════════════════════════════════════════

def collect(exchange: ccxt.okx, symbol: str) -> dict:
    """
    [1h Bot] 수집 항목:
      ohlcv:          1h(250) / 4h(210) / 1d(100)  ← config 자동 반영
      ticker:         현재가
      funding_rate:   펀딩비
      ls_ratio:       롱숏비율 (4h 기간)
      taker_volume:   Taker 비율 (5m, 미시구조용)
      microstructure: 호가창 / 청산 / 캔들모멘텀 등
    """
    logger.info(f"{'─'*50}")
    logger.info(f"📡 수집 [1H봇]: {symbol}")

    ohlcv        = collect_ohlcv(exchange, symbol)
    funding_rate = collect_funding_rate(exchange, symbol)
    ls_ratio     = collect_ls_ratio(exchange, symbol)
    taker_volume = collect_taker_volume(exchange, symbol)
    ticker       = collect_ticker(exchange, symbol)
    micro        = fetch_all_microstructure(exchange, symbol)

    return {
        "symbol":         symbol,
        "ohlcv":          ohlcv,
        "ticker":         ticker,
        "funding_rate":   funding_rate,
        "ls_ratio":       ls_ratio,
        "oi_change":      {"available": False},
        "taker_volume":   taker_volume,
        "liquidations":   {},
        "price":          ticker.get("last", 0.0),
        "microstructure": micro,
    }


# ════════════════════════════════════════════════════════════════════
# 일괄 수집 (main.py 진입점)
# ════════════════════════════════════════════════════════════════════

def collect_all_data(exchange: ccxt.okx, symbols) -> dict:
    """
    SINGLE_SYMBOL 환경변수 설정 시 → flat dict 반환 (main.py 호환)
    로컬 전체 실행: {symbol: collected_data} dict 반환
    """
    single = os.environ.get("SINGLE_SYMBOL", "").strip()
    if single:
        return collect(exchange, single)

    if isinstance(symbols, str):
        symbols = [symbols]
    results = {}
    for sym in symbols:
        try:
            results[sym] = collect(exchange, sym)
        except Exception as e:
            logger.error(f"[Pipeline] {sym} 수집 오류: {e}")
            results[sym] = None
    return results


# ════════════════════════════════════════════════════════════════════
# 헬스체크
# ════════════════════════════════════════════════════════════════════

def check_connection(exchange: ccxt.okx) -> bool:
    try:
        exchange.fetch_time()
        logger.info("✅ OKX API 연결 정상")
        return True
    except Exception as e:
        logger.error(f"❌ OKX API 연결 실패: {e}")
        return False
