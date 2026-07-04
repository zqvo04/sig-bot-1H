"""WRF-4 엔진 — L0~L4 오케스트레이션 (무상태·페이퍼).

발사 ⟺ P̂ ≥ W_floor ∧ ¬VETO ∧ ¬격리(섀도셋업·발사권강등 — Phase A).
사이징 ∝ P̂. 발사 무관 모든 후보를 기록한다
(전량 기록 → 오프라인 보정 데이터). 본체는 main에서 try/except로 격리되며,
디텍터/베토/레벨 각각도 내부 격리한다.
"""
from __future__ import annotations

import logging

from . import calibration, detectors, features, levels, veto
from .btc_macro import classify_btc_macro

logger = logging.getLogger(__name__)

try:
    import config
except ImportError:  # pragma: no cover
    from src import config  # type: ignore


def _size_from_p(p_hat: float, floor: float) -> float:
    """사이징 ∝ P̂. floor에서 base, 그 위로 선형 증가, 상한 적용(페이퍼)."""
    base = getattr(config, "WRF_SIZE_BASE", 1.0)
    smax = getattr(config, "WRF_SIZE_MAX", 2.0)
    if p_hat <= floor:
        return round(base, 3)
    span = max(1e-6, 1.0 - floor)
    return round(min(smax, base + (smax - base) * (p_hat - floor) / span), 3)


def _regime_routing_state(feat: dict):
    """강확정 추세면 'down'/'up', 아니면 None. 토글 OFF면 항상 None(무변경).
    횡보(미정렬)에선 절대 작동 안 함(반전엣지 보존).

    [Pillar1-③] BTC 종속성 분리: 구버전은 btc_macro==DOWNLEG/UPLEG(=BTC 7D±3% 필요)를
    강제해, BTC 횡보 중 홀로 흘러내리는 알트는 영구 미라우팅(FN)이었다. self-struct 모드는
    심볼 자신의 일봉 EMA구조(ema_1d_struct)로도 확정 — btc_macro는 OR-가산(여전히 기여)."""
    if not getattr(config, "WRF_REGIME_ROUTING", False):
        return None
    raw, ctx = feat.get("raw", {}), feat.get("ctx", {})
    h4 = raw.get("ema_4h"); bias = ctx.get("bias_1d"); macro = ctx.get("btc_macro")
    if getattr(config, "WRF_ROUTING_SELF_STRUCT", True):
        ds = raw.get("ema_1d_struct")   # 심볼 자신의 일봉 EMA20/50 구조(±1)
        if h4 == -1 and bias == "BEAR" and (ds == -1 or macro == "DOWNLEG"):
            return "down"
        if h4 == 1 and bias == "BULL" and (ds == 1 or macro == "UPLEG"):
            return "up"
        return None
    # 구동작: btc_macro 3중 정렬 필수(BTC 종속)
    if h4 == -1 and bias == "BEAR" and macro == "DOWNLEG":
        return "down"
    if h4 == 1 and bias == "BULL" and macro == "UPLEG":
        return "up"
    return None


def run_engine(symbol: str, measures: dict, ohlcv: dict, collected: dict,
               btc_macro: str = None) -> dict:
    """측정치 → L1 피처 → 4디텍터 → P̂ → VETO → 발사판정. 전체 후보 반환."""
    if btc_macro is None:
        btc_macro = classify_btc_macro((ohlcv or {}).get("1d"))

    feat = features.build_features(measures, ohlcv, btc_macro)
    table = calibration.load_table()
    floor_default = getattr(config, "WRF_WIN_FLOOR", 0.58)

    # L0 전역 베토 (방향 무관) — 한 번만 계산
    try:
        global_v = veto.global_vetoes(feat, collected)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[engine] 전역 베토 실패: {e}")
        global_v = []

    # L2 후보 — [Pillar1] 강확정 추세면 TF(추종) 활성화 후 역추세 반전(MR/RV) 억제.
    # 토글 OFF면 route=None → 무변경(구동작). 횡보에선 작동 안 함(반전엣지 보존).
    route = _regime_routing_state(feat)
    if route:
        al = feat["ctx"].get("allowed_setups", [])
        if "TF" not in al:                                  # ADX 지연 보강 — 추종 라우팅 복원
            feat["ctx"]["allowed_setups"] = list(al) + ["TF"]
    cands = detectors.detect_all(feat)
    if route:
        counter = "long" if route == "down" else "short"    # 추세 반대 = 칼받기 → 억제
        cands = [c for c in cands
                 if not (c.get("setup") in ("MR", "RV", "BR") and c.get("dir") == counter)]

    # [Phase A] 발사권 통제: 섀도 셋업(신규·미검증 — 기본 BR)과 발사권 강등 셀은
    # 후보 생성·기록·오프라인 채점은 그대로 하되 라이브 발사만 차단(검증→점등).
    shadow_setups = getattr(config, "WRF_SHADOW_SETUPS", set())
    fire_rights_on = getattr(config, "WRF_FIRE_RIGHTS_ENABLED", True)

    enriched = []
    fired = []
    for c in cands:
        try:
            lv = levels.compute_levels(c, feat)
            # [Phase 2] prior·보정 동시 평가(그림자 A/B). p_hat는 스위치 반영값.
            pe = calibration.evaluate(c, feat["ctx"], table)
            p_hat, source, floor = pe["p_hat"], pe["source"], pe["floor"]
            # [Pillar2-③] BO near-SL 타이트니스 보정 — SL을 박스높이→~ATR로 당기면 실제 승률↓
            # 인데 prior P̂은 SL을 모른다 → r_dist/박스높이가 작을수록 p_hat 소폭 차감(기하-확률 결합).
            if (c["setup"] == "BO" and getattr(config, "WRF_BO_SL_NEAR", False)
                    and "box_hi" in c and "box_lo" in c):
                box_h = abs(float(c["box_hi"]) - float(c["box_lo"]))
                if box_h > 0:
                    tight = lv["r_dist"] / box_h
                    ref = getattr(config, "WRF_BO_SL_TIGHT_REF", 0.60)
                    p_hat = max(0.0, p_hat - getattr(config, "WRF_BO_SL_TIGHT_PEN", 0.15)
                                * max(0.0, ref - tight))
            vetoes = veto.evaluate(c, feat, collected, global_v)
            # [Pillar3-③] EV-결합 게이트: 고정 RR≥1.5 대신 기대값 EV=P̂·RR−(1−P̂)≥EV_MIN
            # (고확률일수록 RR 요구 완화 = EV 정합). 보정셀은 학습 승률 존중 → 우회.
            if getattr(config, "WRF_EV_GATE", True):
                ev = p_hat * lv["rr"] - (1.0 - p_hat)
                rr_ok = (source == "calibrated") or (
                    ev >= getattr(config, "WRF_EV_MIN", 0.15)
                    and lv["rr"] >= getattr(config, "WRF_EV_RR_FLOOR", 1.0))
            else:
                rr_ok = (source == "calibrated") or (lv["rr"] >= getattr(config, "WRF_MIN_RR", 1.5))
            # [Phase A] 격리(quarantine): 발사조건과 무관한 발사권 통제(거버넌스 게이트).
            #   SHADOW_SETUP — 미검증 셋업(WRF_SHADOW_SETUPS)  ·  FIRE_RIGHTS — 실현
            #   승률 사후검정 강등 셀(테이블 발행). 격리돼도 기록·오프라인 채점은 계속.
            quarantine = []
            if c["setup"] in shadow_setups:
                quarantine.append("SHADOW_SETUP")
            if fire_rights_on and pe.get("fire_rights") == "shadow":
                quarantine.append("FIRE_RIGHTS")
            fire = bool(p_hat >= floor and not vetoes and rr_ok and not quarantine)
            # [near-miss 섀도 밴드] 플로어만 못 넘은 '문턱탈락'(veto·RR은 통과) 후보 태깅.
            # 발사엔 무영향 — 표본 굶주린 클래스(특히 숏)의 near-miss 기록용(오프라인 보정).
            band_w = getattr(config, "WRF_SHADOW_BAND_WIDTH", 0.03)
            shadow_band = bool(
                getattr(config, "WRF_SHADOW_BAND", True)
                and not fire and not vetoes and rr_ok
                and (floor - band_w) <= p_hat < floor
            )
            size = _size_from_p(p_hat, floor) if fire else 0.0
            rec = {
                "setup": c["setup"], "dir": c["dir"], "precond": True,
                "entry": lv["entry"], "tp": lv["tp"], "sl": lv["sl"],
                "r_dist": lv["r_dist"], "rr": lv["rr"], "t_max": lv["t_max"],
                **({"trail_dist": lv["trail_dist"]} if "trail_dist" in lv else {}),
                "p_hat": round(p_hat, 4), "p_source": source,
                "p_prior": round(pe["p_prior"], 4), "p_cal": round(pe["p_cal"], 4),
                "p_cal_source": pe["cal_source"],
                "win_floor": round(floor, 4),
                "C": c["C"], "L": c["L"], "F": c["F"],
                "confluence_n": c.get("confluence_n", 0),
                "veto": vetoes, "size": size, "fire": fire,
                "shadow_band": shadow_band,
                "quarantine": quarantine,
                "reason": c.get("reason", ""),
            }
            enriched.append(rec)
            if fire:
                fired.append(rec)
        except Exception as e:  # pragma: no cover
            logger.warning(f"[engine] 후보 처리 실패(격리) {c.get('setup')}/{c.get('dir')}: {e}")

    # 발사 후보 (setup,dir) 중복 제거 — 더 높은 P̂만 남기고 패자는 비발사로 강등(이중
    # 발사/이중 기록 방지·JSONL 정합). BR(밴드반전)은 RV와 같은 반전 패밀리로 묶는다
    # (원트랙 시절 '디텍터-RV vs 밴드복귀 동시발화 방지' 의도를 분리 후에도 보존).
    _best = {}
    for r in fired:
        k = ("RV" if r["setup"] == "BR" else r["setup"], r["dir"])
        if k not in _best or r["p_hat"] > _best[k]["p_hat"]:
            _best[k] = r
    _winners = {id(r) for r in _best.values()}
    for r in fired:
        if id(r) not in _winners:
            r["fire"] = False
            r["size"] = 0.0
    fired = list(_best.values())
    # 발사 후보는 P̂ 내림차순 서열화(BO·RV는 base-rate 낮아 자동 후순위)
    fired.sort(key=lambda r: r["p_hat"], reverse=True)
    # near-miss 섀도 밴드 후보(발사 무관·기록/집계용)
    shadowed = [r for r in enriched if r.get("shadow_band")]

    return {
        "symbol": symbol,
        "ts": feat["ts"],
        "p0": feat["p0"],
        "raw": feat["raw"],
        "pct": feat["pct"],
        "ctx": feat["ctx"],
        "candidates": enriched,
        "fired": fired,
        "shadowed": shadowed,
        "global_veto": global_v,
        "feat": feat,
    }
