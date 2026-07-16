"""[Phase 2] 오프라인 보정 잡 — 계층적 부분풀링(partial pooling). 주 1회 CI.

라이브는 산출물(calibration_table.json)의 셀별 δ_eff만 읽는다(여기선 학습만).

구(舊) 방식의 자격 게이트(독립 N≥100 × 거시≥2종)는 데이터 누적 대비 비현실적이라
어떤 셀도 보정되지 못했다(실효≈0). 이를 폐기하고 random-intercept 로지스틱으로 교체:

  계층  GLOBAL → SETUP → BASE(setup×regime) → CELL(setup×regime×macro)
  ① prior 기울기(wC/wL/wF) 고정 — 소표본에서 (C,L,F) 반응성 재학습 금지(과적합 차단).
  ② 셀 승률을 Beta-Binomial로 부모 승률에 수축:
        wr_pooled = (wr_obs·n_indep + wr_parent·k) / (n_indep + k)
     데이터 적으면 부모로 회귀, 쌓이면 자기 셀로 수렴(자격 0/1 이분법 폐기).
  ③ 셀 절편 오프셋  δ = logit(wr_pooled) − logit(prior_raw_mean)
        (prior가 이 셀에서 얼마나 어긋났나 = 보정해야 할 로그오즈 양)
  ④ 신뢰도 가중 + 하드캡  δ_eff = clamp( conf·δ , ±delta_cap ),  conf = n_indep/(n_indep+k_conf)
  ⑤ 비정상성 가드: 부모(setup×regime)가 거시방향별로 승률이 갈리면(베타착시) conf 페널티.

수축·신뢰도의 n은 모두 '독립표본 n'(72h 중첩 탈상관, stride=24h) — 명목 n의 과신 차단.
산출물은 셀별 {n, n_indep, wr_pooled, delta_eff, win_floor, p_source,
p_wr_ge_floor, fire_rights}. 라이브는 δ_eff·fire_rights만 읽는다.

[Phase A] 발사권(fire-rights) 게이트: 셀별 실현 결판의 Beta-Binomial 사후검정
P(WR ≥ floor)로 live/shadow 를 발행 — ex-post 플로어 폐루프(자세한 근거는 config
WRF_FR_* 블록). 밴드반전(BR) 소급 재분류는 labels.candidate_dataset 이 수행.

CLI:
  python analysis/calibrate.py            # JSONL → calibration_table.json 생성
  python analysis/calibrate.py --dry-run  # 파일 쓰지 않고 요약만
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "src"))
sys.path.insert(0, os.path.join(_HERE, "..", "src", "wrf"))

import build_dataset as bd  # noqa: E402
import labels as lab  # noqa: E402
import config  # noqa: E402
import calibration as live_calib  # noqa: E402  (src/wrf/calibration.py — prior 일관성)


_EPS = 1e-6


def _logit(p: float) -> float:
    p = min(1.0 - _EPS, max(_EPS, p))
    return math.log(p / (1.0 - p))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def independent_n(ts_series: pd.Series, stride_h: float) -> int:
    """탈중첩 독립표본 수(72h 자기상관 차단): stride_h 간격으로 그리디 선택."""
    ts = ts_series.dropna().sort_values()
    if ts.empty:
        return 0
    count, last = 0, None
    for t in ts:
        if last is None or (t - last).total_seconds() / 3600.0 >= stride_h:
            count += 1
            last = t
    return count


def _shrink(wr_obs: float, n_eff: float, wr_parent: float, k: float) -> float:
    """Beta-Binomial 수축: 부모 승률을 k 의사관측으로 본 사후평균."""
    denom = n_eff + k
    if denom <= 0:
        return wr_parent
    return (wr_obs * n_eff + wr_parent * k) / denom


# ════════════════════════════════════════════════════════════════════
# [Phase A] 발사권(fire-rights) 게이트 — ex-post 플로어 폐루프
# ════════════════════════════════════════════════════════════════════
# 목적함수 max N s.t. WR≥floor 의 제약을 실현 결판으로 강제한다: 셀별 Beta-Binomial
# 사후분포에서 P(WR ≥ floor)를 계산해 fire_rights ∈ {live, shadow} 발행. 라이브는
# 이 필드를 읽기만 한다(5-B). 예측 파라미터 학습 없음(발사권 박탈/복권만) — 과적합 무관.
# 주의: n은 명목 결판수(중첩 트레이드 상관으로 실효 표본은 이보다 작다) — 보수적
# DEMOTE_P(0.15)·MIN_DECIDED·히스테리시스·자동복권(섀도로 데이터 계속 축적)이 완충.

def _p_wr_ge_floor(wins: float, losses: float, floor: float, prior_n: float) -> float:
    """Beta 사후분포 P(승률 ≥ floor). prior = floor 중심 중립(α0=floor·n0).

    무데이터 셀 ≈ 0.5(강등 불가 = 콜드스타트 발사 허용 보존). 정규화 불완전베타를
    심프슨 적분으로 계산(의존성 없음·a,b≥1에서 매끈)."""
    a = floor * prior_n + wins
    b = (1.0 - floor) * prior_n + losses
    ln_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)

    def pdf(x: float) -> float:
        if x <= 0.0 or x >= 1.0:
            return 0.0
        return math.exp((a - 1.0) * math.log(x) + (b - 1.0) * math.log(1.0 - x) - ln_beta)

    n_steps = 2000  # 짝수(심프슨)
    h = (1.0 - floor) / n_steps
    s = pdf(floor) + pdf(1.0)
    for i in range(1, n_steps):
        s += pdf(floor + i * h) * (4.0 if i % 2 else 2.0)
    return min(1.0, max(0.0, s * h / 3.0))


def _load_prev_rights(path: str) -> dict:
    """직전 테이블의 셀별 fire_rights(히스테리시스용). 부재/오류 시 {} (전부 live 취급).

    [개선-A] 방향분리 시 키 `{cell}|{dir}` 도 함께 실어 방향별 히스테리시스를 지원한다
    (셀 단위 키는 그대로 유지 — 폴백·구동작 보존)."""
    try:
        with open(path, encoding="utf-8") as fh:
            prev = json.load(fh)
        out = {}
        for k, v in (prev.get("cells") or {}).items():
            out[k] = v.get("fire_rights") or "live"
            for d, r in (v.get("fire_rights_by_dir") or {}).items():
                out[f"{k}|{d}"] = r or "live"
        return out
    except Exception:
        return {}


def _fire_rights(p_ge_floor: float, n_decided: int, prev: str) -> str:
    """강등/복권 판정(비대칭 히스테리시스).

    강등(live→shadow): P(WR≥floor) < DEMOTE_P ∧ 결판 ≥ MIN_DECIDED.
    복권(shadow→live): P(WR≥floor) ≥ PROMOTE_P.
    비대칭 근거 = 손실 비대칭: 오발사는 실손 R 영구, 오강등은 기회비용 일시(섀도로
    후보 기록·채점이 계속돼 증거가 쌓이면 자동 복권)."""
    demote_p = getattr(config, "WRF_FR_DEMOTE_P", 0.15)
    promote_p = getattr(config, "WRF_FR_PROMOTE_P", 0.50)
    min_n = getattr(config, "WRF_FR_MIN_DECIDED", 8)
    if prev == "shadow":
        return "live" if p_ge_floor >= promote_p else "shadow"
    return "shadow" if (n_decided >= min_n and p_ge_floor < demote_p) else "live"


def _would_fire(row) -> bool:
    """발사권 검정 모집단 판정: 발사됐거나, '격리만 아니었으면 발사'였을 후보.

    제약(WR≥floor)은 '발사분'의 승률에 대한 것 — floor가 이미 거부한 후보의 손실로
    셀을 강등하면 안 된다(올바른 거부를 처벌·미발사 셀 강등은 무의미한 FN 위험).
    격리(quarantine: 섀도셋업·발사권강등) 후보를 포함해야 강등된 셀에도 증거가 계속
    쌓여 자동 복권이 가능하다(fire=False 고착 방지). RR 게이트는 엔진과 동일 산식 재계산.
    """
    if bool(row.get("fire")):
        return True
    if not row.get("quarantine_n"):
        return False
    p, rr = row.get("p_hat"), row.get("rr")
    floor = row.get("win_floor")
    if p is None or rr is None or floor is None or pd.isna(p) or pd.isna(rr):
        return False
    if row.get("veto_n") or p < floor:
        return False
    if getattr(config, "WRF_EV_GATE", True):
        ev = p * rr - (1.0 - p)
        return bool(ev >= getattr(config, "WRF_EV_MIN", 0.15)
                    and rr >= getattr(config, "WRF_EV_RR_FLOOR", 0.85))
    return bool(rr >= getattr(config, "WRF_MIN_RR", 1.5))


def calibrate(data_dir: str, prev_table_path: str = None) -> dict:
    rows = bd.load_snapshots(data_dir)
    df = lab.candidate_dataset(rows)   # [Phase A] 밴드반전 소급 재분류(RV→BR) 포함

    stride = getattr(config, "WRF_INDEP_STRIDE_H", 24)
    floor = getattr(config, "WRF_WIN_FLOOR", 0.58)
    k_setup = getattr(config, "WRF_CALIB_K_SETUP", 40.0)
    k_base = getattr(config, "WRF_CALIB_K_BASE", 30.0)
    k_cell = getattr(config, "WRF_CALIB_K_CELL", 25.0)
    k_conf = getattr(config, "WRF_CALIB_K_CONF", 20.0)
    min_dec = getattr(config, "WRF_CALIB_MIN_DECIDED", 3)
    delta_cap = getattr(config, "WRF_CALIB_DELTA_CAP", 1.2)
    fr_prior_n = getattr(config, "WRF_FR_PRIOR_N", 10.0)
    prev_rights = _load_prev_rights(
        prev_table_path or getattr(config, "WRF_CALIB_TABLE", "data/calibration_table.json"))

    base_params = {
        "method": "partial_pooling", "k_setup": k_setup, "k_base": k_base,
        "k_cell": k_cell, "k_conf": k_conf, "min_decided": min_dec,
        "delta_cap": delta_cap, "stride_h": stride, "floor": floor,
        "fr_prior_n": fr_prior_n,
        "fr_demote_p": getattr(config, "WRF_FR_DEMOTE_P", 0.15),
        "fr_promote_p": getattr(config, "WRF_FR_PROMOTE_P", 0.50),
        "fr_min_decided": getattr(config, "WRF_FR_MIN_DECIDED", 8),
    }
    if df.empty:
        return _empty_report(base_params, "표본 0 — 전부 prior(콜드스타트)")

    # 결판(WIN/LOSS)만 보정 모집단. TIMEOUT=스크래치 제외.
    dec = df[df["tb_win"].notna()].copy()
    if dec.empty:
        return _empty_report(base_params, "결판 후보 0(경로 미성숙) — 전부 prior")

    dec["btc_macro"] = dec["btc_macro"].astype(str)
    dec["base"] = dec["setup"].astype(str) + "|" + dec["regime_1h"].astype(str)

    # ── 계층 수축 cascade: GLOBAL → SETUP → BASE ──────────────────────
    wr_global = float(dec["tb_win"].mean())

    wr_setup = {}
    for s, g in dec.groupby("setup"):
        n_ind = independent_n(g["ts"], stride)
        wr_setup[s] = _shrink(float(g["tb_win"].mean()), n_ind, wr_global, k_setup)

    wr_base, base_macro = {}, {}
    for b, g in dec.groupby("base"):
        setup = b.split("|")[0]
        parent = wr_setup.get(setup, wr_global)
        n_ind = independent_n(g["ts"], stride)
        wr_base[b] = _shrink(float(g["tb_win"].mean()), n_ind, parent, k_base)
        # 베타착시(비정상성): 거시방향별 승률 분산(각 ≥5건). 한쪽만 성립하면 페널티.
        per_macro = {m: float(gm["tb_win"].mean())
                     for m, gm in g.groupby("btc_macro") if len(gm) >= 5}
        illusion = False
        if len(per_macro) >= 2:
            vals = list(per_macro.values())
            above = [v for v in vals if v >= floor]
            below = [v for v in vals if v < floor - 0.1]
            illusion = bool(len(above) == 1 and below)
        base_macro[b] = {"per_macro": per_macro, "macro_coverage": len(per_macro),
                         "beta_illusion": illusion}

    # ── CELL: 수축 승률 → δ → δ_eff ───────────────────────────────────
    cells, drift = {}, {}
    for cell, g in dec.groupby("cell"):
        setup, regime, macro = (str(cell).split("|") + ["", "", ""])[:3]
        base = f"{setup}|{regime}"
        n = len(g)
        n_ind = independent_n(g["ts"], stride)
        wr_obs = float(g["tb_win"].mean())
        parent = wr_base.get(base, wr_setup.get(setup, wr_global))
        wr_pooled = _shrink(wr_obs, n_ind, parent, k_cell)

        # 이 셀 결판후보들의 prior raw 평균(δ 기준선; 라이브 base와 동일 정의)
        priors = [live_calib.prior_raw_p(setup, float(c), float(l), float(f))
                  for c, l, f in zip(g["C"], g["L"], g["F"])
                  if c is not None and l is not None and f is not None]
        p_prior_mean = sum(priors) / len(priors) if priors else None

        bm = base_macro.get(base, {"beta_illusion": False, "macro_coverage": 0,
                                   "per_macro": {}})
        # [Phase A] 발사권: '발사 ∪ 격리-미발사' 결판의 사후검정 P(WR≥floor) → live/shadow.
        # δ 보정(위)은 전체 후보로 학습하지만(확률모델 보정), 발사권은 발사분 승률 제약의
        # 집행이므로 모집단을 발사분으로 한정한다(floor가 거부한 후보의 손실로 강등 금지).
        gf = g[g.apply(_would_fire, axis=1)]
        wins_f = float(gf["tb_win"].sum())
        n_f = int(len(gf))
        p_ge = _p_wr_ge_floor(wins_f, n_f - wins_f, floor, fr_prior_n)
        rights = _fire_rights(p_ge, n_f, prev_rights.get(str(cell), "live"))
        # [개선-A] 방향분리 발사권: 셀 단위 검정의 방향 희석을 제거. (cell,dir)별 사후검정으로
        # 나쁜 방향만 강등. 토글 OFF면 빈 dict → 라이브는 셀 단위 폴백(구동작 보존).
        fire_rights_by_dir = {}
        if getattr(config, "WRF_FR_BY_DIR", False) and not gf.empty:
            for d, gd in gf.groupby("dir"):
                w_d = float(gd["tb_win"].sum())
                n_d = int(len(gd))
                pg_d = _p_wr_ge_floor(w_d, n_d - w_d, floor, fr_prior_n)
                fire_rights_by_dir[str(d)] = {
                    "fire_rights": _fire_rights(pg_d, n_d,
                                                prev_rights.get(f"{cell}|{d}", "live")),
                    "n_fire_decided": n_d, "p_wr_ge_floor": round(pg_d, 4),
                }
        rec = {
            "n": int(n), "n_indep": int(n_ind),
            "base": base, "win_rate": round(wr_obs, 4),
            "wr_pooled": round(wr_pooled, 4),
            "wr_parent": round(parent, 4),
            "macro_coverage": int(bm["macro_coverage"]),
            "beta_illusion": bool(bm["beta_illusion"]),
            "win_floor": floor, "p_source": "prior", "delta_eff": 0.0,
            "n_fire_decided": n_f, "p_wr_ge_floor": round(p_ge, 4),
            "fire_rights": rights,
            "fire_rights_by_dir": fire_rights_by_dir,
        }
        if p_prior_mean is not None and n >= min_dec:
            delta = _logit(wr_pooled) - _logit(p_prior_mean)
            conf = n_ind / (n_ind + k_conf) if (n_ind + k_conf) > 0 else 0.0
            if bm["beta_illusion"]:
                conf *= 0.5  # 비정상성 페널티(한쪽 거시에서만 성립)
            delta_eff = _clamp(conf * delta, -delta_cap, delta_cap)
            rec.update({
                "p_prior_mean": round(p_prior_mean, 4),
                "delta": round(delta, 4), "confidence": round(conf, 4),
                "delta_eff": round(delta_eff, 4),
                "p_source": "calibrated" if abs(delta_eff) > 1e-4 else "prior",
            })
        cells[cell] = rec
        drift[cell] = {"n": int(n), "win_rate": round(wr_obs, 4),
                       "wr_pooled": round(wr_pooled, 4)}

    n_cal = sum(1 for c in cells.values() if c["p_source"] == "calibrated")
    n_shadow = sum(1 for c in cells.values() if c.get("fire_rights") == "shadow")
    n_shadow_dir = sum(1 for c in cells.values()
                       for v in (c.get("fire_rights_by_dir") or {}).values()
                       if v.get("fire_rights") == "shadow")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": getattr(config, "WRF_SCHEMA_VERSION", 3),
        "params": base_params,
        "global": {"win_rate": round(wr_global, 4), "n_decided": int(len(dec))},
        "setups": {s: round(v, 4) for s, v in wr_setup.items()},
        "bases": {b: round(v, 4) for b, v in wr_base.items()},
        "n_cells": len(cells), "n_calibrated": n_cal, "n_shadow": n_shadow,
        "n_shadow_dir": n_shadow_dir,
        "cells": cells, "drift": drift,
    }
    return report


def _empty_report(params: dict, note: str) -> dict:
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": getattr(config, "WRF_SCHEMA_VERSION", 3),
            "params": params, "cells": {}, "n_cells": 0, "n_calibrated": 0,
            "note": note}


def _write(path: str, report: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description="WRF Phase 2 부분풀링 보정 잡")
    ap.add_argument("--dir", default=getattr(config, "RESEARCH_DATA_DIR", "data/research"))
    ap.add_argument("--out", default=getattr(config, "WRF_CALIB_TABLE", "data/calibration_table.json"))
    ap.add_argument("--dry-run", action="store_true", help="파일 쓰지 않고 요약만")
    args = ap.parse_args()

    rep = calibrate(args.dir, prev_table_path=args.out)
    if not args.dry_run:
        _write(args.out, rep)

    g = rep.get("global", {})
    print(f"보정(부분풀링) 완료: {rep.get('n_cells', 0)}셀 중 보정활성 "
          f"{rep.get('n_calibrated', 0)}셀 · 발사권강등 {rep.get('n_shadow', 0)}셀"
          f"(방향분리 {rep.get('n_shadow_dir', 0)}) "
          f"(전역승률 {g.get('win_rate')}, 결판 {g.get('n_decided', 0)})")
    if rep.get("note"):
        print(f"  · {rep['note']}")
    for cell, c in sorted(rep.get("cells", {}).items(),
                          key=lambda kv: -abs(kv[1].get("delta_eff", 0))):
        flag = "✅보정" if c["p_source"] == "calibrated" else "·prior"
        fr = " 🚫발사권강등" if c.get("fire_rights") == "shadow" else ""
        frd = c.get("fire_rights_by_dir") or {}
        if frd:
            fr += " [" + " ".join(
                f"{d}:{v['fire_rights']}({v['n_fire_decided']},P={v['p_wr_ge_floor']})"
                for d, v in sorted(frd.items())) + "]"
        extra = (f" δ_eff={c.get('delta_eff')} conf={c.get('confidence')}"
                 if c["p_source"] == "calibrated" else "")
        print(f"  {flag} {cell}: n={c['n']} indep={c['n_indep']} "
              f"wr={c['win_rate']}→pool={c['wr_pooled']} "
              f"발사결판={c.get('n_fire_decided')} P(WR≥floor)={c.get('p_wr_ge_floor')}"
              f"{' 베타착시' if c['beta_illusion'] else ''}{extra}{fr}")
    if not args.dry_run:
        print(f"\n→ {args.out}")


if __name__ == "__main__":
    main()
