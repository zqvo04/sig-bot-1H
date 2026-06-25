"""WRF-4 엔진 — L0~L4 오케스트레이션 (무상태·페이퍼).

발사 ⟺ P̂ ≥ W_floor ∧ ¬VETO. 사이징 ∝ P̂. 발사 무관 모든 후보를 기록한다
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
    """[Path1-①] ema_4h·bias_1d·btc_macro 3중 정렬 강확정 추세면 'down'/'up', 아니면 None.
    토글 OFF면 항상 None(무변경). 횡보(미정렬)에선 절대 작동 안 함(반전엣지 보존)."""
    if not getattr(config, "WRF_REGIME_ROUTING", False):
        return None
    raw, ctx = feat.get("raw", {}), feat.get("ctx", {})
    h4 = raw.get("ema_4h"); bias = ctx.get("bias_1d"); macro = ctx.get("btc_macro")
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

    # L2 후보 — [Path1-①] 강확정 추세면 TF(추종) 활성화 후 역추세 반전(MR/RV) 억제.
    # 토글 OFF면 route=None → 무변경(구동작). 횡보에선 작동 안 함(반전엣지 보존).
    route = _regime_routing_state(feat)
    if route:
        al = feat["ctx"].get("allowed_setups", [])
        if "TF" not in al:                                  # ADX 지연 보강 — 추종 라우팅 복원
            feat["ctx"]["allowed_setups"] = list(al) + ["TF"]
    cands = detectors.detect_all(feat)
    if route:
        counter = "long" if route == "down" else "short"    # 추세 반대 = 칼받기 → 억제
        cands = [c for c in cands if c.get("d_shadow")
                 or not (c.get("setup") in ("MR", "RV") and c.get("dir") == counter)]

    enriched = []
    fired = []
    for c in cands:
        try:
            lv = levels.compute_levels(c, feat)
            # [Phase 2] prior·보정 동시 평가(그림자 A/B). p_hat는 스위치 반영값.
            pe = calibration.evaluate(c, feat["ctx"], table)
            p_hat, source, floor = pe["p_hat"], pe["source"], pe["floor"]
            vetoes = veto.evaluate(c, feat, collected, global_v)
            # RR 품질필터: prior 발사는 최소 RR 요구(보정셀은 학습 승률 존중 → 우회).
            min_rr = getattr(config, "WRF_MIN_RR", 1.5)
            rr_ok = (source == "calibrated") or (lv["rr"] >= min_rr)
            is_dshadow = bool(c.get("d_shadow"))
            # d_shadow(=D 트리거 무장) 후보는 라이브 발사에서 영구 제외(섀도 전용).
            fire = bool(p_hat >= floor and not vetoes and rr_ok and not is_dshadow)
            # [near-miss 섀도 밴드] 플로어만 못 넘은 '문턱탈락'(veto·RR은 통과) 후보 태깅.
            # 발사엔 무영향 — 표본 굶주린 클래스(특히 숏)의 near-miss 기록용(오프라인 보정).
            band_w = getattr(config, "WRF_SHADOW_BAND_WIDTH", 0.03)
            shadow_band = bool(
                getattr(config, "WRF_SHADOW_BAND", True)
                and not fire and not vetoes and rr_ok and not is_dshadow
                and (floor - band_w) <= p_hat < floor
            )
            # [D-shadow] D 트리거 무장 후보의 '섀도 발사'. 라이브 발사와 동일 게이트
            # (p_hat≥floor ∧ ¬veto ∧ rr_ok)를 적용 — floor의 min-axis(C/L/F 직교동의)가
            # 반(反)추세 칼받기(역레그 C<0)·무소진(F<0)을 차단(과발화·오발 방지). D는
            # precond만 완화하고 품질게이트는 존중한다. (구버전은 floor를 우회해 라이브에서
            # DOWNLEG 딥매수 롱이 무더기 오발 → 우회 제거.)
            shadow_fire = bool(is_dshadow and p_hat >= floor and not vetoes and rr_ok)
            size = _size_from_p(p_hat, floor) if fire else 0.0
            rec = {
                "setup": c["setup"], "dir": c["dir"], "precond": True,
                "entry": lv["entry"], "tp": lv["tp"], "sl": lv["sl"],
                "r_dist": lv["r_dist"], "rr": lv["rr"], "t_max": lv["t_max"],
                "p_hat": round(p_hat, 4), "p_source": source,
                "p_prior": round(pe["p_prior"], 4), "p_cal": round(pe["p_cal"], 4),
                "p_cal_source": pe["cal_source"],
                "win_floor": round(floor, 4),
                "C": c["C"], "L": c["L"], "F": c["F"],
                "confluence_n": c.get("confluence_n", 0),
                "veto": vetoes, "size": size, "fire": fire,
                "shadow_band": shadow_band,
                "d_shadow": is_dshadow, "shadow_fire": shadow_fire,
                "reason": c.get("reason", ""),
            }
            enriched.append(rec)
            if fire:
                fired.append(rec)
        except Exception as e:  # pragma: no cover
            logger.warning(f"[engine] 후보 처리 실패(격리) {c.get('setup')}/{c.get('dir')}: {e}")

    # 발사 후보는 P̂ 내림차순 서열화(BO·RV는 base-rate 낮아 자동 후순위)
    fired.sort(key=lambda r: r["p_hat"], reverse=True)
    # near-miss 섀도 밴드 후보(발사 무관·기록/집계용)
    shadowed = [r for r in enriched if r.get("shadow_band")]
    # [D-shadow] D 트리거가 추가로 잡은 반전 후보(실제 발사와 방향 중복은 제외) — 섀도 기록·판정용.
    _fired_dirs = {r["dir"] for r in fired}
    fired_shadow = [r for r in enriched
                    if r.get("shadow_fire") and r["dir"] not in _fired_dirs]
    fired_shadow.sort(key=lambda r: r["p_hat"], reverse=True)

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
        "fired_shadow": fired_shadow,
        "global_veto": global_v,
        "feat": feat,
    }
