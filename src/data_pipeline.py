"""
data_pipeline.py — OKX 선물 데이터 수집 (1h Bot v3.0)
──────────────────────────────────────────────────────────────────────
[v3.0 신규 수집 함수]

① collect_top_trader_ls()
   /rubik/stat/contracts/long-short-account-ratio-contract-top-trader
   → 상위 트레이더 계좌 LS 비율 (스마트머니)

② collect_oi_data()
   /api/v5/market/open-interest (현재 OI)
   /api/v5/rubik/stat/contracts/open-interest-history (4h OI 변화)
   → OI 현재값 + 4h 전 대비 변화율

③ collect_funding_history()
   /api/v5/public/funding-rate-history
   → 최근 8개 펀딩비 (64h) 추세 분석용
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
# 헬퍼
# ════════════════════════════════════════════════════════════════════

def _okx_get(path: str, params: dict = None) -> dict:
    try:
        r = requests.get(f"{OKX_BASE}{path}", params=params or {},
                         timeout=10, headers={"Content-Type": "application/json"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning(f"[OKX-HTTP] {path} 실패: {e}")
        return {"code": "error", "data": [], "msg": str(e)}

def create_exchange() -> ccxt.okx:
    return ccxt.okx({
        "apiKey": config.OKX_API_KEY, "secret": config.OKX_API_SECRET,
        "password": config.OKX_PASSPHRASE,
        "enableRateLimit": True, "options": {"defaultType": "swap"},
    })

def _to_ccxt_swap(symbol: str) -> str:
    if ":" in symbol: return symbol
    p = symbol.split("/")
    return f"{p[0]}/{p[1]}:{p[1]}" if len(p) == 2 else symbol

def _to_base_id(symbol: str) -> str:
    return symbol.replace("/", "-").split(":")[0]

def _to_swap_id(symbol: str) -> str:
    return _to_base_id(symbol) + "-SWAP"

def _to_ccy(symbol: str) -> str:
    return symbol.split("/")[0]

def _ohlcv_to_df(ohlcv_list: list) -> pd.DataFrame:
    if not ohlcv_list: return pd.DataFrame()
    df = pd.DataFrame(ohlcv_list, columns=["timestamp","open","high","low","close","volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["close"])


# ════════════════════════════════════════════════════════════════════
# 1. OHLCV
# ════════════════════════════════════════════════════════════════════

def collect_ohlcv(exchange: ccxt.okx, symbol: str) -> Dict[str, pd.DataFrame]:
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
        return {"rate": rate, "rate_pct": round(rate*100,6),
                "next_rate": next_rate, "next_rate_pct": round(next_rate*100,6)}
    except Exception as e:
        logger.warning(f"  ❌ {symbol} 펀딩비 실패: {e}")
        return None


# ════════════════════════════════════════════════════════════════════
# 3. 롱숏 비율 (1H×4 평균 → 4H 근사)
# ════════════════════════════════════════════════════════════════════

def collect_ls_ratio(exchange: ccxt.okx, symbol: str) -> dict:
    _neutral = {"available": False, "long_pct": 0.5, "short_pct": 0.5, "ratio": 1.0}

    def _parse(ls_val: float) -> dict:
        lp = ls_val / (1.0 + ls_val)
        return {"long_pct": round(lp,4), "short_pct": round(1-lp,4),
                "ratio": round(ls_val,4), "available": True}

    def _avg(data_list: list) -> float:
        ratios = [float(d[1]) for d in data_list[:4]]
        return sum(ratios) / len(ratios)

    ccy = _to_ccy(symbol)
    swap_exchange = getattr(exchange, "_swap", exchange)

    try:
        data = swap_exchange.fetch_long_short_ratio(_to_ccxt_swap(symbol), "1h", limit=4)
        if data:
            ratios = [float(d.get("longShortRatio", 1.0)) for d in data]
            result = _parse(sum(ratios) / len(ratios))
            logger.info(f"  📊 {symbol} 롱숏(CCXT/1h×{len(ratios)}): 롱 {result['long_pct']*100:.1f}%")
            return result
    except Exception as e:
        logger.debug(f"[LS] CCXT 실패: {e}")

    try:
        resp = exchange.publicGetRubikStatContractsLongShortAccountRatio(
            {"ccy": ccy, "period": "1H", "limit": "4"})
        dl = resp.get("data", [])
        if dl:
            result = _parse(_avg(dl))
            logger.info(f"  📊 {symbol} 롱숏(publicGet/1H×{min(4,len(dl))}): 롱 {result['long_pct']*100:.1f}%")
            return result
    except Exception as e:
        logger.debug(f"[LS] publicGet 실패: {e}")

    try:
        resp = _okx_get("/rubik/stat/contracts/long-short-account-ratio",
                        {"ccy": ccy, "period": "1H", "limit": "4"})
        if resp.get("code") == "0" and resp.get("data"):
            result = _parse(_avg(resp["data"]))
            logger.info(f"  📊 {symbol} 롱숏(HTTP/1H×{min(4,len(resp['data']))}): 롱 {result['long_pct']*100:.1f}%")
            return result
    except Exception as e:
        logger.debug(f"[LS] HTTP 실패: {e}")

    logger.warning(f"  ❌ {symbol} 롱숏비율 실패 → neutral")
    return _neutral


# ════════════════════════════════════════════════════════════════════
# 4. Taker 비율
# ════════════════════════════════════════════════════════════════════

def collect_taker_volume(exchange: ccxt.okx, symbol: str) -> dict:
    empty = {"available": False, "buy_ratio": 0.5, "sell_ratio": 0.5,
             "bias": "neutral", "strength": "neutral", "buy_pct": 50.0}
    try:
        resp = _okx_get("/rubik/stat/taker-volume-contract", {
            "instId": _to_swap_id(symbol), "period": "5m",
            "limit":  str(min(config.TAKER_LOOKBACK, 100)),
        })
        if resp.get("code") != "0" or not resp.get("data"):
            return empty
        n          = min(20, len(resp["data"]))
        total_buy  = sum(float(r[1]) for r in resp["data"][:n])
        total_sell = sum(float(r[2]) for r in resp["data"][:n])
        total      = total_buy + total_sell
        if total <= 0: return empty
        buy_r = total_buy / total; sell_r = total_sell / total
        if   buy_r  >= config.TAKER_STRONG_BUY:  bias, strength = "buy_dominant",  "strong"
        elif sell_r >= config.TAKER_STRONG_SELL:  bias, strength = "sell_dominant", "strong"
        elif buy_r  >= 0.55:                       bias, strength = "buy_dominant",  "normal"
        elif sell_r >= 0.55:                       bias, strength = "sell_dominant", "normal"
        else:                                      bias, strength = "neutral",       "neutral"
        logger.info(f"  🔄 {symbol} Taker: 매수 {buy_r*100:.1f}% [{bias}]")
        return {"available": True, "buy_ratio": round(buy_r,4), "sell_ratio": round(sell_r,4),
                "bias": bias, "strength": strength, "buy_pct": round(buy_r*100,2)}
    except Exception as e:
        logger.warning(f"  ❌ {symbol} Taker 실패: {e}")
        return empty


# ════════════════════════════════════════════════════════════════════
# 5. 현재가
# ════════════════════════════════════════════════════════════════════

def collect_ticker(exchange: ccxt.okx, symbol: str) -> dict:
    try:
        t    = exchange.fetch_ticker(_to_ccxt_swap(symbol))
        last = float(t.get("last", 0) or 0)
        op   = float(t.get("open", last) or last)
        chg  = ((last - op) / op * 100) if op > 0 else 0.0
        logger.info(f"  💰 {symbol} ${last:,.4f} ({chg:+.2f}%)")
        return {"last": last, "open": op, "change_pct": round(chg,4), "available": True}
    except Exception as e:
        logger.warning(f"  ❌ {symbol} 티커 실패: {e}")
        return {"last": 0.0, "open": 0.0, "change_pct": 0.0, "available": False}


# ════════════════════════════════════════════════════════════════════
# [v3.0] 6. 스마트머니 — 상위 트레이더 LS 비율
# ════════════════════════════════════════════════════════════════════

def collect_top_trader_ls(symbol: str) -> dict:
    """
    OKX 상위 트레이더 계좌 LS 비율
    /rubik/stat/contracts/long-short-account-ratio-contract-top-trader
    instId=BTC-USDT-SWAP, period=1H, limit=4 (4H 근사)
    """
    _empty = {"available": False, "long_pct": 0.5, "short_pct": 0.5}

    def _parse_avg(data_list: list) -> dict:
        ratios   = [float(d[1]) for d in data_list[:4]]
        avg_ratio = sum(ratios) / len(ratios)
        lp = avg_ratio / (1.0 + avg_ratio)
        return {"long_pct": round(lp,4), "short_pct": round(1-lp,4), "available": True}

    try:
        resp = _okx_get(
            "/rubik/stat/contracts/long-short-account-ratio-contract-top-trader", {
                "instId": _to_swap_id(symbol),
                "period": "1H",
                "limit":  "4",
            }
        )
        if resp.get("code") == "0" and resp.get("data"):
            result = _parse_avg(resp["data"])
            logger.info(
                f"  🐋 {symbol} 상위트레이더: 롱 {result['long_pct']*100:.1f}% "
                f"/ 숏 {result['short_pct']*100:.1f}%"
            )
            return result
    except Exception as e:
        logger.debug(f"[TopTrader] 실패: {e}")

    return _empty


# ════════════════════════════════════════════════════════════════════
# [v3.0] 7. OI 데이터 (현재 OI + 4H 변화)
# ════════════════════════════════════════════════════════════════════

def collect_oi_data(symbol: str, current_price: float) -> dict:
    """
    1단계: OI 히스토리 (rubik, 1H 5개)
    2단계: 현재 OI (/api/v5/market/open-interest)

    반환:
      oi_current:    현재 OI (USD 기준)
      oi_4h_ago:     4H 전 OI
      oi_change_pct: 변화율
      price_4h_change_pct: 4H 가격 변화 (OI와 매칭)
      available: bool
    """
    _empty = {
        "available": False, "oi_current": 0.0, "oi_4h_ago": 0.0,
        "oi_change_pct": 0.0, "direction": "neutral"
    }
    swap_id = _to_swap_id(symbol)

    # 1단계: rubik OI 히스토리
    try:
        resp = _okx_get("/rubik/stat/contracts/open-interest-history", {
            "instId": swap_id, "period": "1H", "limit": "5",
        })
        if resp.get("code") == "0" and resp.get("data") and len(resp["data"]) >= 2:
            data = resp["data"]
            oi_now  = float(data[0][1])   # 최신
            oi_4h   = float(data[min(4, len(data)-1)][1])  # 4H 전
            # [II-9] OI 방향성 기울기 계산용 히스토리 (최신순)
            oi_history = [float(row[1]) for row in data]
            if oi_4h > 0:
                change = (oi_now - oi_4h) / oi_4h
                direction = "up" if change > config.OI_CHANGE_THRESHOLD else \
                            "down" if change < -config.OI_CHANGE_THRESHOLD else "neutral"
                logger.info(
                    f"  📈 {symbol} OI: {oi_now:.0f}→{oi_4h:.0f} "
                    f"변화:{change*100:+.2f}% [{direction}]"
                )
                return {
                    "available": True, "oi_current": round(oi_now,2),
                    "oi_4h_ago": round(oi_4h,2),
                    "oi_change_pct": round(change,4), "direction": direction,
                    "oi_history": oi_history,
                }
    except Exception as e:
        logger.debug(f"[OI] rubik 히스토리 실패: {e}")

    # 2단계: 현재 OI만 수집 (히스토리 없어도 현재값은 확보)
    try:
        resp2 = _okx_get("/api/v5/market/open-interest", {
            "instType": "SWAP", "instId": swap_id,
        })
        if resp2.get("code") == "0" and resp2.get("data"):
            oi = float(resp2["data"][0].get("oi", 0) or 0)
            logger.info(f"  📈 {symbol} OI(현재): {oi:.0f}")
            return {
                "available": True, "oi_current": round(oi,2),
                "oi_4h_ago": 0.0, "oi_change_pct": 0.0, "direction": "neutral"
            }
    except Exception as e:
        logger.debug(f"[OI] 현재값 실패: {e}")

    return _empty


# ════════════════════════════════════════════════════════════════════
# [v3.0] 8. 펀딩비 히스토리
# ════════════════════════════════════════════════════════════════════

def collect_funding_history(symbol: str) -> dict:
    """
    /api/v5/public/funding-rate-history
    최근 8개 (8×8h = 64h)
    """
    _empty = {"available": False, "rates": [], "trend": "neutral",
              "flip": None, "consecutive_extreme": 0}
    try:
        resp = _okx_get("/public/funding-rate-history", {
            "instId": _to_swap_id(symbol),
            "limit":  str(config.FUNDING_HISTORY_LIMIT),
        })
        if resp.get("code") != "0" or not resp.get("data"):
            return _empty

        rates = [float(d.get("fundingRate", 0)) for d in resp["data"]]
        if not rates: return _empty

        # 추세 방향 (최근 vs 4개 전)
        recent = rates[0];  old = rates[min(3, len(rates)-1)]
        trend  = "rising" if recent > old + 0.0001 else \
                 "falling" if recent < old - 0.0001 else "neutral"

        # 전환점 감지 (직전 음수→현재 양수, 또는 반대)
        flip = None
        if len(rates) >= 2:
            if rates[1] < 0 and rates[0] > 0: flip = "neg_to_pos"
            if rates[1] > 0 and rates[0] < 0: flip = "pos_to_neg"

        # 연속 극단값 (고율 펀딩 누적)
        consec = 0
        sign = 1 if rates[0] > 0 else -1
        for r in rates:
            if abs(r) >= config.FUNDING_EXTREME_THRESHOLD and (r * sign > 0):
                consec += 1
            else:
                break

        logger.info(
            f"  💸 {symbol} 펀딩이력: 최근{recent*100:+.4f}% "
            f"추세:{trend} 전환:{flip} 연속극단:{consec}"
        )
        return {
            "available": True, "rates": rates[:8],
            "trend": trend, "flip": flip, "consecutive_extreme": consec,
        }
    except Exception as e:
        logger.warning(f"  ❌ {symbol} 펀딩히스토리 실패: {e}")
        return _empty


# ════════════════════════════════════════════════════════════════════
# 단일 심볼 수집
# ════════════════════════════════════════════════════════════════════

def collect(exchange: ccxt.okx, symbol: str) -> dict:
    logger.info(f"{'─'*50}")
    logger.info(f"📡 수집 [1H봇 v3.0]: {symbol}")

    ohlcv        = collect_ohlcv(exchange, symbol)
    funding_rate = collect_funding_rate(exchange, symbol)
    ls_ratio     = collect_ls_ratio(exchange, symbol)
    taker_volume = collect_taker_volume(exchange, symbol)
    ticker       = collect_ticker(exchange, symbol)
    micro        = fetch_all_microstructure(exchange, symbol)

    price = ticker.get("last", 0.0)

    # [v3.0] 신규 수집
    top_trader_ls    = collect_top_trader_ls(symbol)
    oi_data          = collect_oi_data(symbol, price)
    funding_history  = collect_funding_history(symbol)

    return {
        "symbol":           symbol,
        "ohlcv":            ohlcv,
        "ticker":           ticker,
        "funding_rate":     funding_rate,
        "ls_ratio":         ls_ratio,
        "oi_change":        {"available": False},
        "taker_volume":     taker_volume,
        "liquidations":     {},
        "price":            price,
        "microstructure":   micro,
        # [v3.0]
        "top_trader_ls":    top_trader_ls,
        "oi_data":          oi_data,
        "funding_history":  funding_history,
    }


def collect_all_data(exchange: ccxt.okx, symbols) -> dict:
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


def check_connection(exchange: ccxt.okx) -> bool:
    try:
        exchange.fetch_time()
        logger.info("✅ OKX API 연결 정상")
        return True
    except Exception as e:
        logger.error(f"❌ OKX API 연결 실패: {e}")
        return False
