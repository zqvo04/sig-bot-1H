"""L2 — 셋업 디텍터 ×4. 레짐이 허용집합을 결정한다.

각 디텍터는 롱/숏 대칭으로 후보를 만든다. 후보는 구조적 전제(precond)와
직교 3축(C/L/F ∈ [-1,1], 진입방향 정렬치)을 담는다. precond는 "강확증"
구조게이트(특히 BO 리테스트·RV ≥3확인은 필수★), 축은 prior P̂ 입력이다.

  TF(TRENDING+HTF정합): HH/HL + EMA20/VWAP 눌림 + 모멘텀 재정렬
  BO(SQUEEZE→확장/박스): 경계돌파 + 거래량스파이크 + [리테스트 유지★필수]
  MR(RANGING): BB극단 + RSI극단백분위 + 반전마이크로트리거
  RV(추세소진): 다이버전스 + 키레벨거부 + CHoCH + [≥3확인★] + (청산·펀딩·OI플러시)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import config
except ImportError:  # pragma: no cover
    from src import config  # type: ignore


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))


# ── 연속형(TF/BO) 축: 추세 정합 ─────────────────────────────────────────
def _ctx_align(ctx: dict, direction: str) -> float:
    """C(연속) — 거시방향·일봉바이어스 정합 (추세에 올라타는 셋업용)."""
    m = {"UPLEG": 1.0, "DOWNLEG": -1.0, "CHOP": 0.0}.get(ctx.get("btc_macro", "CHOP"), 0.0)
    b = {"BULL": 1.0, "BEAR": -1.0, "NEUTRAL": 0.0}.get(ctx.get("bias_1d", "NEUTRAL"), 0.0)
    base = 0.6 * m + 0.4 * b
    return _clip(base if direction == "long" else -base)


def _flow_align(raw: dict, pcts: dict, direction: str) -> float:
    """F(연속) — 진입방향 모멘텀·포지셔닝 동조."""
    long = direction == "long"
    mom = (pcts.get("macd", 0.5) - 0.5) * 2.0
    taker = ((raw.get("taker_buy") or 0.5) - 0.5) * 2.0
    smart = max(-1.0, min(1.0, (raw.get("smart_div") or 0.0) * 4.0))
    oi = {"trend_long": 0.5, "expanding_long": 0.5, "trend_short": -0.5,
          "expanding_short": -0.5}.get(raw.get("oi_quadrant", "neutral"), 0.0)
    base = 0.45 * mom + 0.25 * taker + 0.2 * smart + 0.1 * oi
    return _clip(base if long else -base)


# ── 반전형(MR/RV) 축: 소진·역포지션 (추세를 *거스르는* 셋업용) ─────────────
# 반전 셋업은 본질적으로 역추세 → 정합축으로 재면 영구 차단된다. 대신
#   C = "거스를 추세가 신선한 거시레그가 아닌가"(레인지 톱/바텀이면 통과,
#        신선한 동방향 거시레그면 차단=나이프캐칭 방지 유지)
#   F = 모멘텀 *소진* + 군중 역포지션(과열RSI·펀딩극단·테이커소진·스마트머니 반대)
def _ctx_exhaustion(ctx: dict, direction: str) -> float:
    """C(반전) — 페이드 대상 추세의 신선도 기반. CHOP은 완만 통과, 신선한 역행레그는 차단."""
    m = {"UPLEG": 1.0, "DOWNLEG": -1.0, "CHOP": 0.0}.get(ctx.get("btc_macro", "CHOP"), 0.0)
    # 롱반전(하락 페이드)은 거시가 DOWN(신선)이면 위험 → fade_align=m; 숏반전은 -m
    fade_align = m if direction == "long" else -m
    base = getattr(config, "WRF_REV_CTX_BASE", 0.25)
    return _clip(base + 0.75 * fade_align)


def _flow_exhaustion(raw: dict, pcts: dict, direction: str) -> float:
    """F(반전) — 모멘텀 소진 + 군중 역포지션(컨트래리언)."""
    long = direction == "long"
    rsi_ext = (pcts.get("rsi", 0.5) - 0.5) * 2.0      # 과매수=+1
    rsi_term = (-rsi_ext) if long else rsi_ext         # 롱:과매도(+) / 숏:과매수(+)
    f_ext = (pcts.get("funding", 0.5) - 0.5) * 2.0     # 펀딩 군중도
    fund_term = (-f_ext) if long else f_ext            # 롱:군중숏(+) / 숏:군중롱(+)
    taker = ((raw.get("taker_buy") or 0.5) - 0.5) * 2.0
    taker_term = (-taker) if long else taker           # 매수/매도 소진 컨트래리언
    smart = max(-1.0, min(1.0, (raw.get("smart_div") or 0.0) * 4.0))
    smart_term = smart if long else -smart             # 스마트머니 반대편
    base = 0.4 * rsi_term + 0.25 * fund_term + 0.2 * taker_term + 0.15 * smart_term
    return _clip(base)


def _detect_tf(feat: dict, measures: dict):
    raw, pcts, ctx = feat["raw"], feat["pct"], feat["ctx"]
    out = []
    if "TF" not in ctx["allowed_setups"]:
        return out
    for direction in ("long", "short"):
        long = direction == "long"
        ema_aligned = (raw.get("ema") == (1 if long else -1)
                       and raw.get("ema_4h") in ((1, 0) if long else (-1, 0)))
        # 눌림: 가격이 EMA20 근방으로 되돌림 (loc_ema20 백분위 중하단/중상단)
        loc = pcts.get("loc_ema20", 0.5)
        pullback = (0.15 <= loc <= 0.55) if long else (0.45 <= loc <= 0.85)
        mom_realign = raw.get("macd_bull") if long else (not raw.get("macd_bull"))
        struct = raw.get("bos") == (1 if long else -1) or raw.get("bos_4h") == (1 if long else -1)
        precond = bool(ema_aligned and pullback and (mom_realign or struct))
        if not precond:
            continue
        C = _ctx_align(ctx, direction)
        # L: 눌림 품질 — 이상적 눌림(롱 loc≈0.35)에서 +1, 추세 정합 보강
        ideal = 0.35 if long else 0.65
        L = _clip(1.0 - abs(loc - ideal) / 0.35) * (0.7 + 0.3 * (1 if struct else 0))
        F = _flow_align(raw, pcts, direction)
        out.append({"setup": "TF", "dir": direction, "precond": True,
                    "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
                    "confluence_n": raw.get(f"confluence_{direction}", 0),
                    "reason": "HTF정합+눌림+모멘텀재정렬"})
    return out


def _detect_bo(feat: dict, measures: dict):
    raw, pcts, ctx = feat["raw"], feat["pct"], feat["ctx"]
    out = []
    if "BO" not in ctx["allowed_setups"]:
        return out
    df = feat["df_1h"]
    if df is None or len(df) < 26:
        return out
    # 박스는 돌파봉 이전 20봉으로 산정(돌파봉·리테스트봉 제외)
    box_hi = float(df["high"].iloc[-22:-2].max())
    box_lo = float(df["low"].iloc[-22:-2].min())
    brk = float(df["close"].iloc[-2])     # 돌파봉 종가(직전 봉)
    cur = float(df["close"].iloc[-1])     # 현재(리테스트) 봉 종가 = p0
    cur_lo = float(df["low"].iloc[-1])
    cur_hi = float(df["high"].iloc[-1])
    box_h = (box_hi - box_lo) / cur if cur else 0.0
    rt = getattr(config, "WRF_BO_RETEST_TOL", 0.002)  # 리테스트 허용 근접도
    vol_spike = (raw.get("vol_ratio") or 0) >= 1.5
    for direction in ("long", "short"):
        long = direction == "long"
        # 리테스트 유지★필수: ① 직전 봉이 경계를 돌파(broke) ②현재 봉이 경계를
        # 되돌아 눌렀다가(retest) 다시 경계 너머로 마감(hold). 단일봉 윅이 아니라
        # 돌파→리테스트 2봉 패턴을 요구.
        broke = (brk > box_hi) if long else (brk < box_lo)
        retest = (cur_lo <= box_hi * (1 + rt)) if long else (cur_hi >= box_lo * (1 - rt))
        hold = (cur > box_hi) if long else (cur < box_lo)
        precond = bool(broke and vol_spike and retest and hold)
        if not precond:
            continue
        C = _ctx_align(ctx, direction)
        L = _clip(0.5 + min(0.5, box_h * 10))  # 박스가 넓을수록 측정이동 여지 ↑
        F = _flow_align(raw, pcts, direction)
        out.append({"setup": "BO", "dir": direction, "precond": True,
                    "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
                    "confluence_n": raw.get(f"confluence_{direction}", 0),
                    "box_hi": box_hi, "box_lo": box_lo,
                    "reason": "경계돌파+거래량+리테스트유지"})
    return out


def _detect_mr(feat: dict, measures: dict):
    raw, pcts, ctx = feat["raw"], feat["pct"], feat["ctx"]
    out = []
    if "MR" not in ctx["allowed_setups"]:
        return out
    c1 = measures.get("candle_pattern", {})
    for direction in ("long", "short"):
        long = direction == "long"
        bbpos = raw.get("bb_pctb")
        bb_extreme = (bbpos is not None and bbpos <= 0.1) if long \
            else (bbpos is not None and bbpos >= 0.9)
        rsi_p = pcts.get("rsi", 0.5)
        rsi_extreme = (rsi_p <= 0.15) if long else (rsi_p >= 0.85)
        micro = (c1.get("bullish_pin") or c1.get("bullish_engulf")) if long \
            else (c1.get("bearish_pin") or c1.get("bearish_engulf"))
        precond = bool(bb_extreme and rsi_extreme and micro)
        if not precond:
            continue
        C = _ctx_exhaustion(ctx, direction)
        # MR은 평균회귀 — 극단일수록 L 강함(방향 정렬: 롱이면 저극단 = +)
        depth = (0.15 - rsi_p) / 0.15 if long else (rsi_p - 0.85) / 0.15
        L = _clip(0.5 + max(0.0, depth))
        F = _flow_exhaustion(raw, pcts, direction)
        out.append({"setup": "MR", "dir": direction, "precond": True,
                    "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
                    "confluence_n": raw.get(f"confluence_{direction}", 0),
                    "reason": "BB극단+RSI극단+반전마이크로"})
    return out


def _detect_rv(feat: dict, measures: dict):
    raw, pcts, ctx = feat["raw"], feat["pct"], feat["ctx"]
    out = []
    if "RV" not in ctx["allowed_setups"]:
        return out
    rsi_m = measures.get("rsi", {})
    c1 = measures.get("candle_pattern", {})
    wk = measures.get("weekly_levels", {})
    for direction in ("long", "short"):
        long = direction == "long"
        # ── 소진(exhaustion) 신호: 추세가 지쳤는가 ──────────────────────
        div = rsi_m.get("bullish_divergence") if long else rsi_m.get("bearish_divergence")
        rsi_extreme = (pcts.get("rsi", 0.5) <= 0.12) if long else (pcts.get("rsi", 0.5) >= 0.88)
        liq_flush = bool(raw.get("liq_spike"))
        funding_extreme = (pcts.get("funding", 0.5) <= 0.1) if long \
            else (pcts.get("funding", 0.5) >= 0.9)
        oi_flush = raw.get("oi_quadrant") in ("reversal_long", "weak_bounce") if long else \
            raw.get("oi_quadrant") in ("reversal_short", "weak_bounce")
        exhaustion = [div, rsi_extreme, liq_flush, funding_extreme, oi_flush]
        # ── 트리거(trigger) 신호: 전환이 시작됐는가 (CHoCH는 선택) ─────────
        rev_candle = (c1.get("bullish_pin") or c1.get("bullish_engulf")) if long \
            else (c1.get("bearish_pin") or c1.get("bearish_engulf"))
        key_reject = bool(wk.get("near_level"))
        # 실패한 돌파/유동성 스윕: failed_break +1=하향이탈실패(롱) / -1=상향이탈실패(숏)
        swept = (raw.get("failed_break") == 1) if long else (raw.get("failed_break") == -1)
        choch = (raw.get("choch") == 1 or raw.get("choch_4h") == 1) if long \
            else (raw.get("choch") == -1 or raw.get("choch_4h") == -1)
        triggers = [rev_candle, key_reject, swept, choch]
        n_exh = sum(bool(x) for x in exhaustion)
        n_trg = sum(bool(x) for x in triggers)
        confirms = n_exh + n_trg
        # ★ 소진 ≥1 ∧ 트리거 ≥1 ∧ 총 ≥3 (CHoCH 없어도 첫 전환봉에서 포착 가능)
        precond = bool(n_exh >= 1 and n_trg >= 1 and confirms >= 3)
        if not precond:
            continue
        C = _ctx_exhaustion(ctx, direction)
        L = _clip(0.4 + 0.1 * confirms)
        F = _flow_exhaustion(raw, pcts, direction)
        out.append({"setup": "RV", "dir": direction, "precond": True,
                    "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
                    "confluence_n": raw.get(f"confluence_{direction}", 0),
                    "confirms": confirms,
                    "reason": f"추세소진(소진{n_exh}+트리거{n_trg})"})
    return out


def detect_all(feat: dict) -> list:
    """4디텍터 실행 → 후보 리스트(발사 무관 전량). 디텍터별 try/except 격리."""
    measures = feat.get("measures", {})
    cands = []
    for fn in (_detect_tf, _detect_bo, _detect_mr, _detect_rv):
        try:
            cands.extend(fn(feat, measures))
        except Exception as e:  # pragma: no cover
            logger.warning(f"[detector {fn.__name__}] 실패(격리): {e}")
    return cands
