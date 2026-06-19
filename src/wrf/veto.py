"""L0 — VETO (하드 ~4). 발사 절대 차단 조건.

  ① 스프레드 폭발        : 호가 스프레드 > WRF_VETO_SPREAD_BP (bp)
  ② 진입 정면 대량청산캐스케이드 : 진입방향을 때리는 청산 ≥ WRF_VETO_LIQ_CASCADE
  ③ 데이터 신선도 실패   : 마지막 봉 경과 > WRF_VETO_DATA_AGE_MIN (분)
  ④ 거시 정면충돌        : 롱인데 DOWNLEG / 숏인데 UPLEG (강추세 역행)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

try:
    import config
except ImportError:  # pragma: no cover
    from src import config  # type: ignore


def global_vetoes(feat: dict, collected: dict) -> list:
    """방향 무관 전역 베토(스프레드·신선도). 반환: 사유 리스트."""
    v = []
    # ③ 데이터 신선도
    try:
        ts = datetime.fromisoformat(feat["ts"])
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
        if age_min > getattr(config, "WRF_VETO_DATA_AGE_MIN", 90):
            v.append("DATA_STALE")
    except Exception:
        v.append("DATA_STALE")
    # ① 스프레드 폭발
    try:
        micro = (collected or {}).get("microstructure") or {}
        books = micro.get("orderbook") or (collected or {}).get("orderbook") or {}
        bids, asks = books.get("bids"), books.get("asks")
        if bids and asks:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            mid = (best_bid + best_ask) / 2.0
            if mid > 0:
                spread_bp = (best_ask - best_bid) / mid * 1e4
                if spread_bp > getattr(config, "WRF_VETO_SPREAD_BP", 8.0):
                    v.append("SPREAD_BLOWOUT")
    except Exception:
        pass
    return v


def directional_vetoes(candidate: dict, feat: dict, collected: dict) -> list:
    """방향별 베토(청산 캐스케이드·거시 정면충돌)."""
    v = []
    direction = candidate["dir"]
    long = direction == "long"
    raw = feat["raw"]
    ctx = feat["ctx"]
    # ④ 거시 정면충돌 — 단, RV(전환)는 면제. RV는 CHoCH+리테스트+소진(=구조붕괴
    #    증거)을 이미 강제하므로 하드베토가 본분(전환 포착)을 무력화한다. 역추세
    #    위험은 C축(_ctx_exhaustion)·min-axis 소프트게이트로 통제(역할 분담).
    rv_exempt = (candidate.get("setup") == "RV"
                 and getattr(config, "WRF_RV_MACRO_EXEMPT", True))
    macro = ctx.get("btc_macro", "CHOP")
    if not rv_exempt and ((long and macro == "DOWNLEG") or ((not long) and macro == "UPLEG")):
        v.append("MACRO_HEADON")
    # ② 진입 정면 대량청산 캐스케이드
    try:
        liq = (collected or {}).get("liquidations") or {}
        thr = getattr(config, "WRF_VETO_LIQ_CASCADE", 5)
        # 롱 진입 정면 = 롱청산 캐스케이드(하방 가속)
        cnt = liq.get("long_liq_count" if long else "short_liq_count", 0) or 0
        if raw.get("liq_spike") and int(cnt) >= thr:
            adverse = (liq.get("favorable_direction") not in (direction, None))
            if adverse:
                v.append("LIQ_CASCADE")
    except Exception:
        pass
    return v


def evaluate(candidate: dict, feat: dict, collected: dict, global_v: list = None) -> list:
    """후보의 전체 VETO 사유(전역+방향). 비어있으면 통과."""
    g = global_v if global_v is not None else global_vetoes(feat, collected)
    return list(g) + directional_vetoes(candidate, feat, collected)
