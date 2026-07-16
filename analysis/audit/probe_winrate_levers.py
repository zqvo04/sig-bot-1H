"""[승률실험] 승률 레버 3종 워크포워드(시간분할) 프로브 — 측정 전용.

전반(학습) 데이터로만 보정테이블/발사권을 만들고, 후반(평가) 발사집합에 적용해
승률이 실제로 오르는지 잰다(유사-OOS). 레버:

  L1 calib  : WRF_CALIB_DISABLED=false 상당 — 전반 학습 δ_eff로 p_cal 재계산,
              p_cal < floor 인 발사를 제거(닫기만; 보정 cap>prior cap으로 새 발사
              가능성도 있으나 발사집합엔 fired만 있어 제거 효과가 지배적).
  L2 fr-dir : WRF_FR_BY_DIR + 공격적 강등(MIN_DECIDED=3, DEMOTE_P=0.35, PRIOR_N=6)
              — 전반 발사결판으로 (cell,dir) 강등 → 후반 해당 (cell,dir) 발사 제거.
  L3 adxkill: 반전셋업 ∧ adx백분위≥0.6 ∧ 페이드레그 생존≥2 → C:=min(C,-0.5) 재계산.

주의(정직성): 전 기간 표본이 작아(발사결판 ~23) 후반 평가집합은 극소수다.
이 프로브는 '방향 점검 + 레버 간 상대비교'용이며 통계 판정이 아니다. 전 기간
인샘플 수치도 참고로 병기한다(과적합 상한선).

실행: python analysis/audit/probe_winrate_levers.py
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "analysis"))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "src", "wrf"))

import build_dataset as bd  # noqa: E402
import labels as lab  # noqa: E402
import config  # noqa: E402
import calibration as cal  # noqa: E402
import detectors as det  # noqa: E402
import calibrate as cb  # noqa: E402

REV_SETUPS = {"MR", "RV", "BR"}
FLOOR = 0.58
ADX_TAU = 0.6
KILL_C = -0.5
# L2 공격적 발사권 파라미터(실험 프로파일 후보)
FR_EXP = {"WRF_FR_BY_DIR": True, "WRF_FR_MIN_DECIDED": 3,
          "WRF_FR_DEMOTE_P": 0.35, "WRF_FR_PRIOR_N": 6.0}

DATA_DIR = os.path.join(_ROOT, "data", "research")


def _pct_rank(sorted_vals, x):
    if x is None or not sorted_vals:
        return None
    lo, hi = 0, len(sorted_vals)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_vals[mid] <= x:
            lo = mid + 1
        else:
            hi = mid
    return lo / len(sorted_vals)


def _stats(rows):
    n = len(rows)
    if not n:
        return "n=  0   WR=  -    ΣR=   -  "
    w = sum(1 for r in rows if r["tb_win"])
    sr = sum(r["tb_r"] for r in rows if r["tb_r"] is not None)
    return f"n={n:3d}  WR={100.0*w/n:5.1f}%  ΣR={sr:+6.2f}"


def _build_table(rows_subset, fr_overrides=None):
    """rows 부분집합으로 보정테이블 생성(실코드 경로 재사용 — load_snapshots 패치)."""
    saved = {}
    if fr_overrides:
        for k, v in fr_overrides.items():
            saved[k] = getattr(config, k, None)
            setattr(config, k, v)
    orig_load = bd.load_snapshots
    bd.load_snapshots = lambda *a, **k: rows_subset
    try:
        rep = cb.calibrate(DATA_DIR, prev_table_path="/dev/null")
    finally:
        bd.load_snapshots = orig_load
        for k, v in saved.items():
            setattr(config, k, v)
    return rep.get("cells", {})


def _apply_levers(fired, table_calib, table_fr, adx_by_sym, raw_by_id):
    """발사행 리스트 → 레버별 잔존 집합 dict."""
    out = {"base": list(fired), "L1_calib": [], "L2_frdir": [], "L3_adx": [],
           "L1+L2": [], "L1+L2+L3": []}

    def keep_calib(r):
        cell = table_calib.get(r["cell"])
        if not cell:
            return True  # 셀 없음 → prior 그대로(기존 발사 유지)
        p, src, floor = cal.calibrated_p_hat(r["setup"], r["C"], r["L"], r["F"], cell)
        return bool(p >= floor)

    def keep_frdir(r):
        cell = table_fr.get(r["cell"]) or {}
        bd_ = (cell.get("fire_rights_by_dir") or {}).get(r["dir"])
        if bd_ and bd_.get("fire_rights") == "shadow":
            return False
        return True

    def keep_adx(r):
        if r["setup"] not in REV_SETUPS:
            return True
        raw = raw_by_id.get(r["snapshot_id"], {})
        apct = _pct_rank(adx_by_sym.get(r["symbol"], []), raw.get("adx"))
        if apct is None or apct < ADX_TAU or det._leg_alive_n(raw, r["dir"]) < 2:
            return True
        p = cal.prior_p_hat(r["setup"], min(r["C"], KILL_C), r["L"], r["F"])
        return bool(p >= (r.get("win_floor") or FLOOR))

    for r in fired:
        k1, k2, k3 = keep_calib(r), keep_frdir(r), keep_adx(r)
        if k1:
            out["L1_calib"].append(r)
        if k2:
            out["L2_frdir"].append(r)
        if k3:
            out["L3_adx"].append(r)
        if k1 and k2:
            out["L1+L2"].append(r)
        if k1 and k2 and k3:
            out["L1+L2+L3"].append(r)
    return out


def _report(tag, sets):
    print(f"\n[{tag}]")
    for name, rows in sets.items():
        sh = [r for r in rows if r["dir"] == "short"]
        lo = [r for r in rows if r["dir"] == "long"]
        print(f"  {name:10s} 전체 {_stats(rows)} | 숏 {_stats(sh)} | 롱 {_stats(lo)}")


def main():
    rows = bd.load_snapshots(DATA_DIR)
    v3 = [r for r in rows if r.get("schema_version") == 3]
    raw_by_id = {r["snapshot_id"]: (r.get("raw") or {}) for r in v3}
    adx_by_sym = {}
    for r in v3:
        a = (r.get("raw") or {}).get("adx")
        if a is not None:
            adx_by_sym.setdefault(r["symbol"], []).append(a)
    for s in adx_by_sym:
        adx_by_sym[s].sort()

    df = lab.candidate_dataset(rows)
    dec = df[df["tb_win"].notna()].copy()
    fired_all = dec[dec["fire"] == True].to_dict("records")  # noqa: E712
    print(f"결판 후보 {len(dec)} · 발사결판 {len(fired_all)}")

    # ── 시간분할: 발사결판 ts 중앙값 기준(평가집합 균형) ──
    ts_sorted = sorted(r["ts"] for r in fired_all)
    cut = ts_sorted[len(ts_sorted) // 2]
    train_rows = [r for r in v3 if r.get("ts") and r["ts"] < cut.isoformat()]
    test_fired = [r for r in fired_all if r["ts"] >= cut]
    print(f"분할점 {cut} — 학습 스냅샷 {len(train_rows)} · 평가 발사결판 {len(test_fired)}")

    table_train = _build_table(train_rows)
    table_train_fr = _build_table(train_rows, FR_EXP)
    sets_oos = _apply_levers(test_fired, table_train, table_train_fr,
                             adx_by_sym, raw_by_id)
    _report("워크포워드(후반 평가 — 유사 OOS)", sets_oos)

    # ── 참고: 전 기간 인샘플(과적합 상한선) ──
    table_full = _build_table(v3)
    table_full_fr = _build_table(v3, FR_EXP)
    sets_ins = _apply_levers(fired_all, table_full, table_full_fr,
                             adx_by_sym, raw_by_id)
    _report("전 기간 인샘플(참고 — 과적합 상한선)", sets_ins)

    # L2가 강등한 (cell,dir) 목록(투명성)
    print("\n[L2 공격적 발사권이 강등한 (cell,dir)] — 전 기간 테이블 기준")
    for cell, c in sorted(table_full_fr.items()):
        for d, v in (c.get("fire_rights_by_dir") or {}).items():
            if v.get("fire_rights") == "shadow":
                print(f"  🚫 {cell}|{d}: 발사결판={v['n_fire_decided']} "
                      f"P(WR≥floor)={v['p_wr_ge_floor']}")
    print("\n주: 표본 극소·자기상관 — 방향 점검 + 레버 상대비교용. 통계 판정 아님.")


if __name__ == "__main__":
    main()
