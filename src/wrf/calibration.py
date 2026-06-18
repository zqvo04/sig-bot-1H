"""L3 — 보정 승률 P̂. 셀=(setup×regime×btc_macro).

라이브는 절대 학습하지 않는다. 오프라인 주간 잡(analysis/calibrate.py)이 검증된
셀만 calibration_table.json으로 배포하고, 라이브는 그 테이블만 읽는다.

신뢰게이트 미충족 셀(현재 전부) → 보수적 고정 prior(직교게이트). 충족 셀 →
isotonic(로지스틱(C,L,F)). 테이블 부재/예외 시 항상 prior(콜드스타트 안전).
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


def prior_p_hat(setup: str, C: float, L: float, F: float) -> float:
    """보수적 고정 직교게이트 prior. 셋업별 b0 비대칭(BO·RV는 낮음→소수만 통과)."""
    b0 = getattr(config, "WRF_PRIOR_B0", {}).get(setup, -0.5)
    wC = getattr(config, "WRF_PRIOR_WC", 1.1)
    wL = getattr(config, "WRF_PRIOR_WL", 1.3)
    wF = getattr(config, "WRF_PRIOR_WF", 1.2)
    cap = getattr(config, "WRF_PRIOR_CAP", 0.65)
    z = b0 + wC * C + wL * L + wF * F
    p = min(cap, _sigmoid(z))
    # 직교 3축 광범위 동의 게이트: 한 축이라도 최소동의 미만이면 콜드스타트 발사 보류.
    # (가중합이 높아도 단일 축 과의존으로 발사되던 약발 신호 차단. 보정셀엔 미적용.)
    min_axis = getattr(config, "WRF_PRIOR_MIN_AXIS", 0.10)
    if min(C, L, F) < min_axis:
        floor = getattr(config, "WRF_WIN_FLOOR", 0.58)
        p = min(p, floor - 0.03)
    return p


def _isotonic_apply(x: float, xs: list, ys: list) -> float:
    """단조 보정맵 적용 (선형보간). xs는 오름차순."""
    if not xs:
        return x
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


def cell_qualified(cell: dict) -> bool:
    """신뢰게이트: 탈중첩 독립표본 N≥n_min ∧ 거시방향 ≥2종 ∧ 베타착시 아님."""
    if not cell:
        return False
    n_min = getattr(config, "WRF_CELL_N_MIN", 100)
    macro_min = getattr(config, "WRF_CELL_MACRO_MIN", 2)
    return bool(
        cell.get("qualified", False)
        and int(cell.get("n_indep", 0)) >= n_min
        and int(cell.get("macro_coverage", 0)) >= macro_min
        and not cell.get("beta_illusion", False)
    )


def compute_p_hat(candidate: dict, ctx: dict, table: dict = None) -> tuple:
    """후보 → (p_hat, source, win_floor). source ∈ {'prior','calibrated'}."""
    setup = candidate["setup"]
    C, L, F = candidate["C"], candidate["L"], candidate["F"]
    floor = getattr(config, "WRF_WIN_FLOOR", 0.58)
    table = load_table() if table is None else table
    key = cell_key(setup, ctx.get("regime_1h", "UNKNOWN"), ctx.get("btc_macro", "CHOP"))
    cell = table.get(key) if table else None

    if cell and cell_qualified(cell):
        try:
            w = cell["weights"]  # {b0, wC, wL, wF}
            z = w["b0"] + w["wC"] * C + w["wL"] * L + w["wF"] * F
            p = _sigmoid(z)
            iso = cell.get("isotonic")
            if iso:
                p = _isotonic_apply(p, iso.get("x", []), iso.get("y", []))
            return float(p), "calibrated", float(cell.get("win_floor", floor))
        except Exception as e:  # pragma: no cover
            logger.warning(f"[calib] 셀 {key} 보정 실패 → prior: {e}")

    return prior_p_hat(setup, C, L, F), "prior", floor
