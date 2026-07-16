"""L3 — 승률 P̂. 셀=(setup×regime×btc_macro).

[Phase 2] 계층적 부분풀링(partial pooling) 보정. 구(舊) 자격 게이트(독립 N≥100 ×
거시≥2종)는 비현실적으로 높아 실효≈0이었다 → 폐기. 대신 random-intercept 로지스틱:
prior의 기울기(wC/wL/wF)는 고정하고, 오프라인 잡이 학습한 셀별 절편 오프셋 δ_eff만
prior 로그오즈에 더한다.

  라이브:  z = prior_logodds(C,L,F) + δ_eff[cell]
          P̂ = min(calib_cap, sigmoid(z))      (셀 없으면 prior 폴백 — 콜드스타트 안전)

δ_eff는 오프라인에서 Beta-Binomial 수축(부모로) + 신뢰도 가중 + 하드캡을 거쳐 산출돼,
소표본 셀은 자동으로 δ≈0(=prior)에 머문다(과적합 차단). 테이블 부재/예외 시에도 prior.

그림자 운영(WRF_CALIB_DISABLED=true 기본): 발사는 prior, 보정 P̂은 계산·기록만(A/B).
OOS 우위 입증 후 false 로 전환하면 보정 P̂으로 발사.
"""
from __future__ import annotations

import json
import logging
import math
import os

logger = logging.getLogger(__name__)

try:
    import config
except ImportError:  # pragma: no cover
    from src import config  # type: ignore

_TABLE_CACHE = None
_TABLE_MTIME = None


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def cell_key(setup: str, regime_1h: str, btc_macro: str) -> str:
    return f"{setup}|{regime_1h}|{btc_macro}"


def load_table(path: str = None) -> dict:
    """calibration_table.json 로드(mtime 캐시). 부재 시 {} (전부 prior)."""
    global _TABLE_CACHE, _TABLE_MTIME
    path = path or getattr(config, "WRF_CALIB_TABLE", "data/calibration_table.json")
    try:
        if not os.path.exists(path):
            return {}
        mtime = os.path.getmtime(path)
        if _TABLE_CACHE is not None and _TABLE_MTIME == mtime:
            return _TABLE_CACHE
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        _TABLE_CACHE = data.get("cells", data) if isinstance(data, dict) else {}
        _TABLE_MTIME = mtime
        return _TABLE_CACHE
    except Exception as e:  # pragma: no cover
        logger.warning(f"[calib] 테이블 로드 실패 → 전부 prior: {e}")
        return {}


# ════════════════════════════════════════════════════════════════════
# prior (보수적 고정 직교게이트) — 보정의 '기울기·기준선'이기도 하다
# ════════════════════════════════════════════════════════════════════

def _prior_logodds(setup: str, C: float, L: float, F: float) -> float:
    """prior 로그오즈 z = b0[setup] + wC·C + wL·L + wF·F (캡·min-axis 적용 전)."""
    b0 = getattr(config, "WRF_PRIOR_B0", {}).get(setup, -0.5)
    wC = getattr(config, "WRF_PRIOR_WC", 1.1)
    wL = getattr(config, "WRF_PRIOR_WL", 1.3)
    wF = getattr(config, "WRF_PRIOR_WF", 1.2)
    return b0 + wC * C + wL * L + wF * F


def prior_raw_p(setup: str, C: float, L: float, F: float) -> float:
    """캡·min-axis 적용 전 raw 로지스틱 확률. 보정 δ 측정의 '기준선'(일관성)."""
    return _sigmoid(_prior_logodds(setup, C, L, F))


def _min_axis_penalty(C: float, L: float, F: float) -> float:
    """[Pillar3-①/②] 직교 3축 동의 게이트의 '연속' 페널티(로그오즈 차감, ≥0).

    구버전은 한 축이라도 <min_axis면 p를 floor-0.03(=0.55)로 고정 → floor 통과 불가한
    '위장 하드베토'(불연속 절벽). 대신 가장 약한 축의 '부족분'(min_axis−m)에 비례하는 연속
    페널티를 로그오즈에서 뺀다 — m이 0.10 근방이면 미미(near-miss FN 회복), m이 음수(역추세
    칼받기·무소진)면 급증(FP 보존). prior·보정 경로에 동일 적용해 불연속을 제거한다."""
    min_axis = getattr(config, "WRF_PRIOR_MIN_AXIS", 0.10)
    m = min(C, L, F)
    if m >= min_axis:
        return 0.0
    lam = getattr(config, "WRF_PRIOR_MIN_AXIS_LAMBDA", 2.5)
    return lam * (min_axis - m)


def prior_p_hat(setup: str, C: float, L: float, F: float) -> float:
    """보수적 고정 직교게이트 prior(발사용). 셋업별 b0 비대칭 + 캡 + min-axis 게이트."""
    cap = getattr(config, "WRF_PRIOR_CAP", 0.65)
    z = _prior_logodds(setup, C, L, F)
    if getattr(config, "WRF_PRIOR_MIN_AXIS_SOFT", True):
        # 연속 페널티(소프트) — 약한 축은 매끄럽게, 역행 축은 강하게 차단.
        return min(cap, _sigmoid(z - _min_axis_penalty(C, L, F)))
    # 구동작: 하드 절벽(한 축이라도 <min_axis → floor-0.03 고정).
    p = min(cap, _sigmoid(z))
    min_axis = getattr(config, "WRF_PRIOR_MIN_AXIS", 0.10)
    if min(C, L, F) < min_axis:
        floor = getattr(config, "WRF_WIN_FLOOR", 0.58)
        p = min(p, floor - 0.03)
    return p


# ════════════════════════════════════════════════════════════════════
# [Phase 2] 보정 — 부분풀링 δ_eff 소비
# ════════════════════════════════════════════════════════════════════

def cell_delta(cell: dict) -> float:
    """보정셀에서 라이브에 적용할 로그오즈 오프셋 δ_eff. 없으면 0(=prior)."""
    if not cell or cell.get("p_source") != "calibrated":
        return 0.0
    try:
        return float(cell.get("delta_eff", 0.0))
    except (TypeError, ValueError):
        return 0.0


def calibrated_p_hat(setup: str, C: float, L: float, F: float,
                     cell: dict) -> tuple:
    """보정 P̂ = min(calib_cap, sigmoid(prior_logodds + δ_eff)).

    반환 (p, source, floor). 보정셀 부재/δ=0이면 (prior_p_hat, 'prior', floor).
    """
    floor = getattr(config, "WRF_WIN_FLOOR", 0.58)
    delta = cell_delta(cell)
    if delta == 0.0:
        return prior_p_hat(setup, C, L, F), "prior", floor
    # [②캡 비대칭 수리] 보정 캡은 셀 신뢰도(conf=n_indep/(n_indep+k_conf))가 충분할 때만.
    # 소표본 셀(conf<min)은 δ가 미미해 캡만 오르면 과신 → prior 캡(0.65)으로 강등.
    cap = getattr(config, "WRF_CALIB_CAP", 0.72)
    conf = float(cell.get("confidence", 0.0) or 0.0)
    if conf < getattr(config, "WRF_CALIB_CAP_CONF_MIN", 0.50):
        cap = min(cap, getattr(config, "WRF_PRIOR_CAP", 0.65))
    z = _prior_logodds(setup, C, L, F) + delta
    # [Pillar3-②] min-axis 페널티를 보정 경로에도 일관 적용 — 콜드스타트↔보정 불연속 제거
    # (구버전은 보정셀이 min-axis 보호를 우회 → 같은 C/L/F가 보정 후 갑자기 발사되던 비일관).
    if getattr(config, "WRF_PRIOR_MIN_AXIS_SOFT", True):
        z -= _min_axis_penalty(C, L, F)
    p = min(cap, _sigmoid(z))
    cell_floor = float(cell.get("win_floor", floor))
    return p, "calibrated", cell_floor


def evaluate(candidate: dict, ctx: dict, table: dict = None) -> dict:
    """후보 → 보정 평가 dict(그림자 A/B 포함).

    반환 키:
      p_prior   : 항상 prior P̂(발사용 직교게이트)
      p_cal     : 보정 P̂(셀 있으면 δ 반영, 없으면 prior와 동일)
      cal_source: 'calibrated' | 'prior'
      p_hat     : 발사에 쓸 값(WRF_CALIB_DISABLED=true면 p_prior, false면 p_cal)
      source    : p_hat의 출처
      floor     : 발사 플로어
      fire_rights: [Phase A] 셀 발사권('live'|'shadow') — 주간 잡이 실현 승률의
                   사후검정으로 발행. 셀/필드 부재 시 'live'(콜드스타트 = 발사 허용).
    보정 계산은 스위치와 무관하게 항상 수행 — 그림자 평가(backtest --ab)용.
    """
    setup = candidate["setup"]
    C, L, F = candidate["C"], candidate["L"], candidate["F"]
    floor = getattr(config, "WRF_WIN_FLOOR", 0.58)

    p_prior = prior_p_hat(setup, C, L, F)

    table = load_table() if table is None else table
    key = cell_key(setup, ctx.get("regime_1h", "UNKNOWN"), ctx.get("btc_macro", "CHOP"))
    cell = table.get(key) if table else None
    try:
        p_cal, cal_source, cal_floor = calibrated_p_hat(setup, C, L, F, cell)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[calib] 셀 {key} 보정 실패 → prior: {e}")
        p_cal, cal_source, cal_floor = p_prior, "prior", floor

    # [Phase A] 발사권 — P̂ 추정경로(prior/보정)와 무관하게 셀의 실현 승률 검정 결과.
    # [개선-A] 방향분리: 테이블에 fire_rights_by_dir(비어있지 않음)가 있으면 방향
    # 단위가 권위다 — 해당 방향 항목이 있으면 그 값, 없으면 '그 방향은 발사결판 0'
    # 이므로 콜드스타트 live(셀 강등이 검정 안 된 방향까지 차단하는 역방향 희석 방지).
    # by_dir 자체가 없으면(구 테이블/토글 OFF 학습) 셀 단위 폴백(구동작).
    fire_rights = (cell or {}).get("fire_rights") or "live"
    if getattr(config, "WRF_FR_BY_DIR", False) and cell:
        by_dir_map = cell.get("fire_rights_by_dir")
        if by_dir_map:
            fire_rights = (by_dir_map.get(candidate.get("dir")) or {}).get(
                "fire_rights") or "live"

    disabled = getattr(config, "WRF_CALIB_DISABLED", True)
    if disabled or cal_source != "calibrated":
        return {"p_prior": p_prior, "p_cal": p_cal, "cal_source": cal_source,
                "p_hat": p_prior, "source": "prior", "floor": floor,
                "fire_rights": fire_rights}
    return {"p_prior": p_prior, "p_cal": p_cal, "cal_source": cal_source,
            "p_hat": p_cal, "source": "calibrated", "floor": cal_floor,
            "fire_rights": fire_rights}


def compute_p_hat(candidate: dict, ctx: dict, table: dict = None) -> tuple:
    """후보 → (p_hat, source, floor). 발사에 쓰는 값(스위치 반영). 하위호환 유지."""
    r = evaluate(candidate, ctx, table)
    return r["p_hat"], r["source"], r["floor"]
