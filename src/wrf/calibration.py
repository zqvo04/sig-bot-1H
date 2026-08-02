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
    """calibration_table.json 로드(mtime 캐시). 부재 시 {} (전부 prior).

    [개선안2·3] 반환은 파일 전체(cells·prior_refit·fire_rights_hier 등 최상위 키 보존).
    과거엔 cells 서브딕만 반환했으나(하위호환: 셀 조회부(evaluate)가 table.get("cells",
    table)로 양쪽 형태 모두 처리), prior_refit·fire_rights_hier 소비를 위해 전체로 확장."""
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
        _TABLE_CACHE = data if isinstance(data, dict) else {}
        _TABLE_MTIME = mtime
        return _TABLE_CACHE
    except Exception as e:  # pragma: no cover
        logger.warning(f"[calib] 테이블 로드 실패 → 전부 prior: {e}")
        return {}


# ════════════════════════════════════════════════════════════════════
# prior (보수적 고정 직교게이트) — 보정의 '기울기·기준선'이기도 하다
# ════════════════════════════════════════════════════════════════════

def _prior_coefs(table: dict = None) -> dict:
    """[개선안2] prior 계수 소스 — 활성화 시 오프라인 재적합 블록(테이블의 prior_refit)을
    우선 소비, 부재/미달/비활성이면 config 상수로 폴백(콜드스타트 안전). 라이브는 이
    테이블을 읽기만 한다(5-B) — 재적합 자체는 analysis/calibrate.py 오프라인 전용."""
    if getattr(config, "WRF_PRIOR_REFIT_ENABLED", False) and table:
        refit = table.get("prior_refit")
        if refit and refit.get("b0") and refit.get("wC") is not None:
            return refit
    return {"b0": getattr(config, "WRF_PRIOR_B0", {}),
            "wC": getattr(config, "WRF_PRIOR_WC", 1.1),
            "wL": getattr(config, "WRF_PRIOR_WL", 1.3),
            "wF": getattr(config, "WRF_PRIOR_WF", 1.2)}


def _prior_logodds(setup: str, C: float, L: float, F: float, table: dict = None) -> float:
    """prior 로그오즈 z = b0[setup] + wC·C + wL·L + wF·F (캡·min-axis 적용 전)."""
    coefs = _prior_coefs(table)
    b0 = (coefs.get("b0") or {}).get(setup, -0.5)
    return b0 + coefs["wC"] * C + coefs["wL"] * L + coefs["wF"] * F


def prior_raw_p(setup: str, C: float, L: float, F: float, table: dict = None) -> float:
    """캡·min-axis 적용 전 raw 로지스틱 확률. 보정 δ 측정의 '기준선'(일관성)."""
    return _sigmoid(_prior_logodds(setup, C, L, F, table))


def _min_axis_penalty(C: float, L: float, F: float, table: dict = None) -> float:
    """[Pillar3-①/②] 직교 3축 동의 게이트의 '연속' 페널티(로그오즈 차감, ≥0).

    구버전은 한 축이라도 <min_axis면 p를 floor-0.03(=0.55)로 고정 → floor 통과 불가한
    '위장 하드베토'(불연속 절벽). 대신 가장 약한 축의 '부족분'(min_axis−m)에 비례하는 연속
    페널티를 로그오즈에서 뺀다 — m이 0.10 근방이면 미미(near-miss FN 회복), m이 음수(역추세
    칼받기·무소진)면 급증(FP 보존). prior·보정 경로에 동일 적용해 불연속을 제거한다.

    [개선안4, docs/DIAGNOSTIC_2026-08_FPFN.md §4] λ=2.5는 config 고정 기울기(wC/wL/wF
    합 3.6)의 스케일에서 정해진 값이다. prior 재적합(WRF_PRIOR_REFIT_ENABLED)이 기울기를
    줄이면(예: 합 0.03) 페널티만 원래 크기로 남아 신호보다 감점이 커진다(이중 차감).
    WRF_MIN_AXIS_SCALED=true 면 λ를 재적합 기울기 합에 비례하도록 재계산 —
    WRF_MIN_AXIS_LAMBDA_RATIO 기본값(0.69)은 config 기본 기울기(합 3.6)에서 λ≈2.484로
    현행 동작을 근사 보존한다(5-K③). 기본 OFF — 셋업내부 AUC 개선 측정 후 점등(5-I)."""
    min_axis = getattr(config, "WRF_PRIOR_MIN_AXIS", 0.10)
    m = min(C, L, F)
    if m >= min_axis:
        return 0.0
    lam = getattr(config, "WRF_PRIOR_MIN_AXIS_LAMBDA", 2.5)
    if getattr(config, "WRF_MIN_AXIS_SCALED", False):
        coefs = _prior_coefs(table)
        slope_sum = abs(coefs.get("wC", 0.0)) + abs(coefs.get("wL", 0.0)) + abs(coefs.get("wF", 0.0))
        ratio = getattr(config, "WRF_MIN_AXIS_LAMBDA_RATIO", 0.69)
        lam = ratio * slope_sum
    return lam * (min_axis - m)


def prior_p_hat(setup: str, C: float, L: float, F: float, table: dict = None) -> float:
    """보수적 고정 직교게이트 prior(발사용). 셋업별 b0 비대칭 + 캡 + min-axis 게이트.

    [개선안2] WRF_PRIOR_CAP_SIZING_ONLY=true 면 캡을 확률에 걸지 않고 그대로 반환한다
    (다수 후보가 캡 한 점에 몰려 해상도가 소멸하던 문제 완화 — 실측 32/59가 cap 고정).
    사이징(engine._size_from_p)에서만 캡을 적용해 과신 사이징은 그대로 차단한다."""
    cap = getattr(config, "WRF_PRIOR_CAP", 0.65)
    z = _prior_logodds(setup, C, L, F, table)
    sizing_only = getattr(config, "WRF_PRIOR_CAP_SIZING_ONLY", False)
    if getattr(config, "WRF_PRIOR_MIN_AXIS_SOFT", True):
        # 연속 페널티(소프트) — 약한 축은 매끄럽게, 역행 축은 강하게 차단.
        p = _sigmoid(z - _min_axis_penalty(C, L, F, table))
        return min(1.0, p) if sizing_only else min(cap, p)
    # 구동작: 하드 절벽(한 축이라도 <min_axis → floor-0.03 고정).
    p = _sigmoid(z) if sizing_only else min(cap, _sigmoid(z))
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
                     cell: dict, table: dict = None) -> tuple:
    """보정 P̂ = min(calib_cap, sigmoid(prior_logodds + δ_eff)).

    반환 (p, source, floor). 보정셀 부재/δ=0이면 (prior_p_hat, 'prior', floor).
    """
    floor = getattr(config, "WRF_WIN_FLOOR", 0.58)
    delta = cell_delta(cell)
    if delta == 0.0:
        return prior_p_hat(setup, C, L, F, table), "prior", floor
    # [②캡 비대칭 수리] 보정 캡은 셀 신뢰도(conf=n_indep/(n_indep+k_conf))가 충분할 때만.
    # 소표본 셀(conf<min)은 δ가 미미해 캡만 오르면 과신 → prior 캡(0.65)으로 강등.
    cap = getattr(config, "WRF_CALIB_CAP", 0.72)
    conf = float(cell.get("confidence", 0.0) or 0.0)
    if conf < getattr(config, "WRF_CALIB_CAP_CONF_MIN", 0.50):
        cap = min(cap, getattr(config, "WRF_PRIOR_CAP", 0.65))
    z = _prior_logodds(setup, C, L, F, table) + delta
    # [Pillar3-②] min-axis 페널티를 보정 경로에도 일관 적용 — 콜드스타트↔보정 불연속 제거
    # (구버전은 보정셀이 min-axis 보호를 우회 → 같은 C/L/F가 보정 후 갑자기 발사되던 비일관).
    if getattr(config, "WRF_PRIOR_MIN_AXIS_SOFT", True):
        z -= _min_axis_penalty(C, L, F, table)
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

    table = load_table() if table is None else table
    p_prior = prior_p_hat(setup, C, L, F, table)

    key = cell_key(setup, ctx.get("regime_1h", "UNKNOWN"), ctx.get("btc_macro", "CHOP"))
    # table은 파일 전체(cells 서브딕 포함)이거나, 하위호환으로 cells-only 딕셔너리일 수
    # 있다 — "cells" 키가 없으면 table 자체를 셀맵으로 취급(구 캐시·외부 호출 대비).
    cells_map = (table or {}).get("cells", table or {})
    cell = cells_map.get(key) if cells_map else None
    try:
        p_cal, cal_source, cal_floor = calibrated_p_hat(setup, C, L, F, cell, table)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[calib] 셀 {key} 보정 실패 → prior: {e}")
        p_cal, cal_source, cal_floor = p_prior, "prior", floor

    # [Phase A] 발사권 — P̂ 추정경로(prior/보정)와 무관하게 셀의 실현 승률 검정 결과.
    # [개선-A] 방향분리: 테이블에 fire_rights_by_dir 가 있고 해당 방향 항목이 있으면
    # 방향별 발사권을 쓴다(동일 셀 롱/숏 성과역전 대응). 없으면 셀 단위 폴백(구동작).
    direction = candidate.get("dir")
    fire_rights = (cell or {}).get("fire_rights") or "live"
    resolved_n = 0
    if getattr(config, "WRF_FR_BY_DIR", False) and cell:
        by_dir = (cell.get("fire_rights_by_dir") or {}).get(direction)
        if by_dir and by_dir.get("fire_rights"):
            fire_rights = by_dir["fire_rights"]
            resolved_n = int(by_dir.get("n_fire_decided") or 0)
    # [개선안3] 계층 폴백 — 셀 표본이 희소해 강등이 사실상 불가능하던 문제 완화.
    # (cell,dir)의 결판수가 부족하면 더 넓은 층((setup,regime,dir) → (setup,dir))에서
    # 결판수가 충분한 첫 층의 발사권을 쓴다. 셀 키(5-H)는 불변 — 이 계층은 검정 집계용.
    hier_min = getattr(config, "WRF_FR_HIER_MIN_DECIDED", 6)
    if getattr(config, "WRF_FR_HIER_ENABLED", True) and resolved_n < hier_min and table:
        hier = table.get("fire_rights_hier") or {}
        regime_1h = ctx.get("regime_1h", "UNKNOWN")
        base_entry = (hier.get("base_dir") or {}).get(f"{setup}|{regime_1h}|{direction}")
        setup_entry = (hier.get("setup_dir") or {}).get(f"{setup}|{direction}")
        for entry in (base_entry, setup_entry):
            if entry and int(entry.get("n_fire_decided") or 0) >= hier_min:
                fire_rights = entry["fire_rights"]
                break

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
