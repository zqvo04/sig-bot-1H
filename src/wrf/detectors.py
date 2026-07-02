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


def _confluence_bonus(L: float, raw: dict, direction: str) -> float:
    """[완결성#1] 컨플루언스(FVG/OB/피보/주간 중첩수 0~3) → L 가점.
    측정만 되고 발사엔 미반영이던 confluence를 L에 소폭 반영. bonus=0 이면 OFF."""
    conf = int(raw.get(f"confluence_{direction}", 0) or 0)
    bonus = getattr(config, "WRF_CONFLUENCE_L_BONUS", 0.05)
    return _clip(L + bonus * min(conf, 3))


def _rev_vol_ok(raw: dict) -> bool:
    """[A5/G7] 반전캔들 거래량 게이트 — 반전봉 거래량 > 직전 N봉 평균 × mult.
    데이터 부재(None) 시 통과(격리·안전). mult=0 이면 게이트 OFF."""
    mult = getattr(config, "WRF_REV_VOL_MULT", 1.0)
    if mult <= 0:
        return True
    rv = raw.get("rev_vol_ratio")
    if rv is None:
        return True
    return rv >= mult


# ── 연속형(TF/BO) 축: 추세 정합 ─────────────────────────────────────────
def _ctx_struct_align(ctx: dict, raw: dict) -> float:
    """구조 맥락 부호합(양수=강세). 거시·일봉바이어스·4H추세·일봉EMA20/50, [-1,1].

    가중치는 측정 부호의 고정 합성(새 임계·튜닝 없음, 합=1.0). _ctx_align(추종)과
    _ctx_exhaustion v2(반전)가 공유 — 심볼-로컬 맥락(4H·일봉구조)을 셀 키를 늘리지
    않고 C축 연속피처로 주입(콜드스타트·과적합 보호)."""
    m = {"UPLEG": 1.0, "DOWNLEG": -1.0, "CHOP": 0.0}.get(ctx.get("btc_macro", "CHOP"), 0.0)
    b = {"BULL": 1.0, "BEAR": -1.0, "NEUTRAL": 0.0}.get(ctx.get("bias_1d", "NEUTRAL"), 0.0)
    h4 = float(raw.get("ema_4h") or 0)        # 4H 추세 방향(±1)
    ds = float(raw.get("ema_1d_struct") or 0)  # 일봉 EMA20/50 구조(±1)
    return 0.45 * m + 0.25 * b + 0.20 * h4 + 0.10 * ds


def _ctx_align(ctx: dict, raw: dict, direction: str) -> float:
    """C(연속) — 거시·일봉바이어스·4H추세·일봉EMA20/50 정합 (추종 셋업용)."""
    base = _ctx_struct_align(ctx, raw)
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
def _ctx_exhaustion(ctx: dict, raw: dict, direction: str) -> float:
    """C(반전) — 페이드 대상 추세의 신선도 기반. CHOP은 완만 통과, 신선한 역행레그는 차단.

    [Phase C] v2(WRF_REV_CTX_V2, 기본 OFF): 구버전은 btc_macro echo만 써서 DOWNLEG×숏이
    코인 자기상태와 무관하게 C=1.0으로 **포화**(실측: 고유값 3개 → floor·사이징이 변별력
    상실, 매크로 태그의 알트 예측력도 약함). v2는 심볼-로컬 구조(_ctx_struct_align:
    4H추세·일봉EMA·바이어스)를 주입해 macro 유효가중을 0.75→0.34로 낮추고 나머지를
    심볼 자체 구조로 채운다. **출력 envelope[-0.5,1.0]과 극단(깨끗한정렬=+1·신선칼받기=-0.5)은
    구설계와 동일 — 중간 해상도만 추가**(구설계가 맞았던 극단은 불변). 롱/숏 대칭은 부호
    반전으로 보장(5-D).

    검증(오프라인 47결판·독립재구현): 고유값 3→10, IC old +0.13→new +0.20(시간분할 양
    구간 일관), 의미론 비반전. **단 데이터가 DOWNLEG/CHOP 단일레짐이라 fade 방향의 통계
    확증은 UPLEG 관측 후 재검증 전제 → 기본 OFF(5-I).**"""
    base = getattr(config, "WRF_REV_CTX_BASE", 0.25)
    if getattr(config, "WRF_REV_CTX_V2", False):
        align = _ctx_struct_align(ctx, raw)
        align = align if direction == "long" else -align   # 진입방향 정합(양수=안전 페이드)
        return _clip(base + (1.0 - base) * align)           # envelope [2·base−1, 1] = 구설계와 동일
    # 구동작: btc_macro echo만(롱반전=하락페이드는 거시 DOWN 신선이면 위험 → fade=m; 숏=-m)
    m = {"UPLEG": 1.0, "DOWNLEG": -1.0, "CHOP": 0.0}.get(ctx.get("btc_macro", "CHOP"), 0.0)
    fade_align = m if direction == "long" else -m
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
    use_fib = getattr(config, "WRF_TF_FIB_PULLBACK", True)
    for direction in ("long", "short"):
        long = direction == "long"
        htf_aligned = raw.get("ema_4h") in ((1, 0) if long else (-1, 0))
        ema_1h_aligned = raw.get("ema") == (1 if long else -1)
        loc = pcts.get("loc_ema20", 0.5)
        # 얕은 눌림: 1H EMA 정렬 유지 + loc 밴드 (구동작)
        shallow = (0.15 <= loc <= 0.55) if long else (0.45 <= loc <= 0.85)
        pullback_shallow = bool(ema_1h_aligned and htf_aligned and shallow)
        # [A1] 깊은 눌림: 4H 피보 zone(optimal/deep) + 4H 정렬. 1H EMA는 깊은
        # 눌림에서 추세 반대로 튀므로 요구하지 않음(데이터: 깊은 눌림 = 1H 비정렬).
        zone = raw.get("retrace_long_zone" if long else "retrace_short_zone", "none")
        fib_pullback = bool(zone in ("optimal", "deep"))
        pullback_deep = bool(use_fib and htf_aligned and fib_pullback)
        if not (pullback_shallow or pullback_deep):
            continue
        # 반전 확인: 모멘텀 재정렬 또는 구조 BOS
        if getattr(config, "WRF_TF_MACD_SYM", True):
            # [Pillar4-②] 숏도 명시적 약세(히스토그램<0) 요구 — 구버전 not macd_bull(중립0 포함)
            # 비대칭(숏에 관대) 제거. 롱=강세, 숏=약세 대칭.
            mom_realign = raw.get("macd_bull") if long else (raw.get("macd") is not None and raw.get("macd") < 0)
        else:
            mom_realign = raw.get("macd_bull") if long else (not raw.get("macd_bull"))
        struct = raw.get("bos") == (1 if long else -1) or raw.get("bos_4h") == (1 if long else -1)
        if not (mom_realign or struct):
            continue
        # [A5] 눌림 종료(재가속) 봉의 거래량 확증
        if not _rev_vol_ok(raw):
            continue
        C = _ctx_align(ctx, raw, direction)
        # L: 깊은 눌림(피보 optimal)은 강한 위치, 얕은 눌림은 loc 기반 품질
        if pullback_deep:
            L = _clip(0.7 + 0.3 * (1 if zone == "optimal" else 0))
        else:
            ideal = 0.35 if long else 0.65
            L = _clip(1.0 - abs(loc - ideal) / 0.35) * (0.7 + 0.3 * (1 if struct else 0))
        # [연결결함#5] 성숙(late) 추세는 반전위험↑ → 동방향 성숙 시 TF 확신 감쇠
        mat = raw.get("maturity")
        mnet = raw.get("maturity_net", 0) or 0
        if mat == "late" and ((mnet > 0) if long else (mnet < 0)):
            L = _clip(L * getattr(config, "WRF_TF_LATE_MATURITY_MULT", 0.85))
        L = _confluence_bonus(L, raw, direction)
        F = _flow_align(raw, pcts, direction)
        ptype = "피보깊은눌림" if pullback_deep and not pullback_shallow else "EMA얕은눌림"
        out.append({"setup": "TF", "dir": direction, "precond": True,
                    "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
                    "confluence_n": raw.get(f"confluence_{direction}", 0),
                    "reason": f"HTF정합+{ptype}+모멘텀/구조"})
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
        C = _ctx_align(ctx, raw, direction)
        L = _clip(0.5 + min(0.5, box_h * 10))  # 박스가 넓을수록 측정이동 여지 ↑
        # [G7] 펀딩 컨트래리언 확증: 군중이 돌파 반대로 쏠림 → 스퀴즈 연료 → L 가점
        f_pct = pcts.get("funding", 0.5)
        contrarian = (f_pct <= getattr(config, "WRF_BO_FUND_LO", 0.20)) if long \
            else (f_pct >= getattr(config, "WRF_BO_FUND_HI", 0.80))
        if contrarian:
            L = _clip(L + getattr(config, "WRF_BO_FUND_BONUS", 0.15))
        L = _confluence_bonus(L, raw, direction)
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
    # [G4] 박스 산정(반전봉 제외) — levels.py 가 박스 기하학 TP/SL 산출에 사용
    df = feat.get("df_1h")
    box_hi = box_lo = None
    try:
        w = getattr(config, "WRF_MR_BOX_WINDOW", 20)
        if df is not None and len(df) >= w + 1:
            box_hi = float(df["high"].iloc[-(w + 1):-1].max())
            box_lo = float(df["low"].iloc[-(w + 1):-1].min())
    except Exception:
        box_hi = box_lo = None
    for direction in ("long", "short"):
        long = direction == "long"
        bbpos = raw.get("bb_pctb")
        bb_lo = getattr(config, "WRF_MR_BB_EXTREME_LO", 0.10)
        bb_hi = getattr(config, "WRF_MR_BB_EXTREME_HI", 0.90)
        bb_extreme = (bbpos is not None and bbpos <= bb_lo) if long \
            else (bbpos is not None and bbpos >= bb_hi)
        rsi_p = pcts.get("rsi", 0.5)
        # [Pillar4-⑤] MR RSI 극단을 死파라미터였던 WRF_PCT_EXTREME_LO/HI로 구동(배선)
        rsi_lo = getattr(config, "WRF_PCT_EXTREME_LO", 0.15)
        rsi_hi = getattr(config, "WRF_PCT_EXTREME_HI", 0.85)
        rsi_extreme = (rsi_p <= rsi_lo) if long else (rsi_p >= rsi_hi)
        micro = (c1.get("bullish_pin") or c1.get("bullish_engulf")) if long \
            else (c1.get("bearish_pin") or c1.get("bearish_engulf"))
        precond = bool(bb_extreme and rsi_extreme and micro)
        if not precond:
            continue
        # [A5] 반전캔들 거래량 확증
        if not _rev_vol_ok(raw):
            continue
        C = _ctx_exhaustion(ctx, raw, direction)
        # MR은 평균회귀 — 극단일수록 L 강함(방향 정렬: 롱이면 저극단 = +)
        depth = (0.15 - rsi_p) / 0.15 if long else (rsi_p - 0.85) / 0.15
        L = _clip(0.5 + max(0.0, depth))
        L = _confluence_bonus(L, raw, direction)
        F = _flow_exhaustion(raw, pcts, direction)
        rec = {"setup": "MR", "dir": direction, "precond": True,
               "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
               "confluence_n": raw.get(f"confluence_{direction}", 0),
               "reason": "BB극단+RSI극단+반전마이크로+거래량"}
        if box_hi is not None and box_lo is not None and box_hi > box_lo:
            rec["box_hi"] = box_hi
            rec["box_lo"] = box_lo
        out.append(rec)
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
        # [Path1-②] 방향-사이드 신호(기본 OFF·라이브안전): 청산·키레벨 거부를 진입방향에
        # 맞는 쪽만 카운트(롱=숏청산/지지거부, 숏=롱청산/저항거부). OFF면 구동작(방향무관).
        sided = getattr(config, "WRF_RV_SIDED_SIGNALS", False)
        # ── 소진(exhaustion) 신호: 추세가 지쳤는가 ──────────────────────
        div = rsi_m.get("bullish_divergence") if long else rsi_m.get("bearish_divergence")
        rv_rsi_lo = getattr(config, "WRF_RV_RSI_EXTREME_LO", 0.12)
        rv_rsi_hi = getattr(config, "WRF_RV_RSI_EXTREME_HI", 0.88)
        rsi_extreme = (pcts.get("rsi", 0.5) <= rv_rsi_lo) if long else (pcts.get("rsi", 0.5) >= rv_rsi_hi)
        liq_flush = ((raw.get("liq_signal") == ("short_liq_detected" if long else "long_liq_detected"))
                     if sided else bool(raw.get("liq_spike")))
        rv_f_lo = getattr(config, "WRF_RV_FUND_EXTREME_LO", 0.10)
        rv_f_hi = getattr(config, "WRF_RV_FUND_EXTREME_HI", 0.90)
        funding_extreme = (pcts.get("funding", 0.5) <= rv_f_lo) if long \
            else (pcts.get("funding", 0.5) >= rv_f_hi)
        oi_flush = raw.get("oi_quadrant") in ("reversal_long", "weak_bounce") if long else \
            raw.get("oi_quadrant") in ("reversal_short", "weak_bounce")
        exhaustion = [div, rsi_extreme, liq_flush, funding_extreme, oi_flush]
        # ── 트리거(trigger) 신호: 전환이 시작됐는가 (CHoCH는 선택) ─────────
        rev_candle = (c1.get("bullish_pin") or c1.get("bullish_engulf")) if long \
            else (c1.get("bearish_pin") or c1.get("bearish_engulf"))
        key_reject = bool(wk.get("near_level") and (
            (((not wk.get("is_resistance")) if long else wk.get("is_resistance"))) if sided else True))
        # 실패한 돌파/유동성 스윕: failed_break +1=하향이탈실패(롱) / -1=상향이탈실패(숏)
        swept = (raw.get("failed_break") == 1) if long else (raw.get("failed_break") == -1)
        choch = (raw.get("choch") == 1 or raw.get("choch_4h") == 1) if long \
            else (raw.get("choch") == -1 or raw.get("choch_4h") == -1)
        triggers = [rev_candle, key_reject, swept, choch]
        n_exh = sum(bool(x) for x in exhaustion)
        n_trg = sum(bool(x) for x in triggers)
        confirms = n_exh + n_trg
        # [A4/G6] 전략 ④ 시퀀스: 구조붕괴(CHoCH) → 리테스트(스윕/키레벨거부) → 반전캔들.
        retest = bool(swept or key_reject)
        need_choch = getattr(config, "WRF_RV_REQUIRE_CHOCH", True)
        need_retest = getattr(config, "WRF_RV_REQUIRE_RETEST", True)
        min_conf = getattr(config, "WRF_RV_MIN_CONFIRMS", 3)
        soft = getattr(config, "WRF_RV_SOFT_PRECOND", True)
        if soft:
            # [Pillar2-①] hard AND → soft score: 5중 동시 AND는 grind에서 ∏pᵢ로 소멸(FN 핵심).
            # 안전 최소치(소진≥1 ∧ 반전캔들 ∧ 확인≥완화치)만 게이트로 남기고 CHoCH·리테스트는
            # 아래 L 감쇠로 흡수 → 부분정렬 반전도 후보화하되, 약하면 P̂<floor로 자동 탈락(FP는 floor).
            precond = bool(n_exh >= 1 and bool(rev_candle)
                           and confirms >= getattr(config, "WRF_RV_SOFT_MIN_CONFIRMS", 2))
        else:
            precond = bool(
                n_exh >= 1
                and bool(rev_candle)                       # 반전 확인 캔들 필수
                and ((choch) if need_choch else (n_trg >= 1))
                and ((retest) if need_retest else True)
                and confirms >= min_conf
            )
        if not precond:
            continue
        # [A5] 반전캔들 거래량 확증
        if not _rev_vol_ok(raw):
            continue
        C = _ctx_exhaustion(ctx, raw, direction)
        L = _clip(0.4 + 0.1 * confirms)
        if soft:
            # 강확증 시퀀스 부재 → L 감쇠(소진은 됐으나 구조확정 약함). floor가 최종 품질필터.
            if not choch:
                L = _clip(L * getattr(config, "WRF_RV_SOFT_NO_CHOCH_MULT", 0.82))
            if not retest:
                L = _clip(L * getattr(config, "WRF_RV_SOFT_NO_RETEST_MULT", 0.90))
        L = _confluence_bonus(L, raw, direction)
        F = _flow_exhaustion(raw, pcts, direction)
        seq = ("CHoCH+리테스트" if (choch and retest) else "CHoCH" if choch
               else "리테스트" if retest else "소진우위")
        out.append({"setup": "RV", "dir": direction, "precond": True,
                    "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
                    "confluence_n": raw.get(f"confluence_{direction}", 0),
                    "confirms": confirms,
                    "reason": f"추세소진(소진{n_exh}+트리거{n_trg}/{seq})"})
    return out


def _bb_pctb_prev(df, period: int, std_dev: float):
    """직전봉 BB %b (현재봉은 raw.bb_pctb). 밴드복귀 확증용. df 부족/오류 시 None."""
    try:
        c = df["close"].astype(float)
        if len(c) < period + 2:
            return None
        mid = c.rolling(period).mean()
        sd = c.rolling(period).std()
        lower = mid - std_dev * sd
        rng = (mid + std_dev * sd) - lower
        pb = (c - lower) / rng.replace(0, float("nan"))
        v = pb.iloc[-2]
        return float(v) if v == v else None   # NaN 가드
    except Exception:
        return None


# ── [밴드반전=BR] BB 밴드복귀로 무장하는 반전 후보 (양방향 대칭) ──────────────
# 설계: 트리거는 'BB 밴드복귀'(상단 외곽→복귀=숏 / 하단 외곽→복귀=롱)로 단순·대칭하게 무장만
# 하고, 방향적합성·소진·맥락 판정은 prior(C/L/F)+floor에 위임한다.
# [Phase A] setup="BR"로 분리: 구현은 setup="RV"에 편승했으나 트리거(밴드복귀 1개)·경제성이
# RV_proper(소진≥1+반전캔들+확인≥2)와 다른 이질 모집단 — 라이브 실측 승률 40% vs 100%로
# 확인돼 셀·보정·발사권을 분리한다. prior 계수(b0)·레벨·거시베토 면제는 RV와 동일하게
# 이관(동작 보존 — 분리 자체는 로직 변경이 아님). BR은 WRF_SHADOW_SETUPS로 섀도 강등:
# 후보 생성·기록·오프라인 채점은 계속되나 라이브 발사는 안 함(검증→점등, 5-I 원상복구).
# [이력] D-shadow 투트랙 → 원트랙(RV 편승) 승격 → 라이브 성적 미달로 BR 분리+섀도 강등.
def _detect_band_reversal(feat: dict, measures: dict):
    if not getattr(config, "WRF_D_SHADOW", True):
        return []
    raw, pcts, ctx = feat["raw"], feat["pct"], feat["ctx"]
    if not ({"MR", "RV"} & set(ctx.get("allowed_setups", []))):  # 반전 적합 레짐 한정
        return []
    bb = raw.get("bb_pctb")
    if bb is None:
        return []
    dv = raw.get("dist_vwap_atr"); r4 = raw.get("rsi_4h")  # 기록용(무장 조건엔 미사용)
    bb_hi = getattr(config, "WRF_D_BBPCTB_HI", 0.80)
    bb_lo = getattr(config, "WRF_D_BBPCTB_LO", 0.20)
    # [Path2-①] 밴드복귀 확증: 직전봉이 밴드 외곽이고 현재봉이 밴드 안으로 복귀(턴)한
    # 경우만 무장 → band-ride(강추세 칼받기 FP)와 소진반전을 분리. 직전 %b 부재 시 밴드터치 폴백.
    require_re = getattr(config, "WRF_D_REQUIRE_REENTRY", True)
    bb_prev = (_bb_pctb_prev(feat.get("df_1h"), getattr(config, "BOLLINGER_PERIOD", 20),
                             getattr(config, "BOLLINGER_STD", 2.0))
               if require_re else None)
    use_re = require_re and bb_prev is not None
    out = []
    for direction in ("long", "short"):
        # 상단(≥hi)=숏 / 하단(≤lo)=롱. 방향적합성은 prior C축(역레그 페이드면 C<0 →
        # floor의 min-axis가 차단)이 판정. 무장 = 밴드복귀(use_re) 또는 밴드터치(폴백).
        if direction == "short":   # 상단 이탈 → 밴드 안 복귀(턴) = 페이드 숏
            armed = (bb_prev >= bb_hi and bb < bb_hi) if use_re else (bb >= bb_hi)
            ext = bb_prev if use_re else bb
            stretch = max(0.0, (ext - bb_hi) / max(1e-6, 1.0 - bb_hi))
        else:                      # 하단 이탈 → 밴드 안 복귀(턴) = 페이드 롱
            armed = (bb_prev <= bb_lo and bb > bb_lo) if use_re else (bb <= bb_lo)
            ext = bb_prev if use_re else bb
            stretch = max(0.0, (bb_lo - ext) / max(1e-6, bb_lo))
        if not armed:
            continue
        C = _ctx_exhaustion(ctx, raw, direction)
        L = _clip(0.5 + 0.5 * min(1.0, stretch))
        L = _confluence_bonus(L, raw, direction)
        F = _flow_exhaustion(raw, pcts, direction)
        mode = (f"밴드복귀 %b={bb_prev:.2f}→{bb:.2f}" if use_re else f"밴드터치 %b={bb:.2f}")
        out.append({
            "setup": "BR", "dir": direction, "precond": True,
            "C": round(C, 4), "L": round(L, 4), "F": round(F, 4),
            "confluence_n": raw.get(f"confluence_{direction}", 0),
            "reason": f"[밴드반전] {mode}"
                      f"{f'/rsi4h={r4:.0f}' if r4 is not None else ''}"
                      f"{f'/vwapATR={dv:+.1f}' if dv is not None else ''}",
        })
    return out


def detect_all(feat: dict) -> list:
    """5디텍터 실행 → 후보 리스트(발사 무관 전량). 디텍터별 try/except 격리.
    _detect_band_reversal 은 BB 밴드복귀 반전(setup=BR) — [Phase A] RV에서 분리,
    WRF_SHADOW_SETUPS 기본값에 포함돼 기록만 되고 라이브 발사는 안 된다."""
    measures = feat.get("measures", {})
    cands = []
    for fn in (_detect_tf, _detect_bo, _detect_mr, _detect_rv, _detect_band_reversal):
        try:
            cands.extend(fn(feat, measures))
        except Exception as e:  # pragma: no cover
            logger.warning(f"[detector {fn.__name__}] 실패(격리): {e}")
    return cands
