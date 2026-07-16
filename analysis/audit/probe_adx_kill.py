"""[개선-B Phase2] C축 ADX 킬 반사실(counterfactual) — 측정 전용, 라이브 미변경.

Phase0(verify_short_trendkill) 사전등록 H1을 '발사집합' 관점에서 검정한다. 저장된
반전(MR/RV/BR) 후보의 C만 킬 규칙으로 낮춰 p_hat을 실제 prior 경로(calibration.
prior_p_hat)로 재계산하고, 발사판정(p_hat≥floor)이 어떻게 바뀌는지 잰다.

킬 규칙(후보): 반전셋업 ∧ adx 자기분포 백분위 ≥ τ ∧ 페이드대상 레그 생존(_leg_alive_n≥2)
  → C := min(C, −0.5)  (기존 _impulse_kill과 동일 수위·구조. '스트레치' 대신 'adx백분위').
  '닫기만'(kill-only): C를 낮추기만 하므로 발사집합은 축소만 — 새 발사 0.

대칭(5-D): 롱·숏에 동일 규칙 적용 후 양방향 성과를 함께 본다.

adx 백분위: 각 심볼의 전체 스냅샷 adx 분포에 후보 adx를 순위매김(라이브 롤링-200
자기분포 근사). 순환 아님(진입시점 trailing).

Gate-In(사전등록, 판정 기준):
  ① 숏 발사집합 WR ≥ floor(58%)  ② 롱 발사집합 성과 비악화(ΣR·WR)
  ③ 제거된 승리(FN) ≤ 제거된 패배 / 3   ④ 시간 2분할 방향 일관
표본 소수·자기상관 → 방향 점검. 통과해도 Phase3은 기본 OFF 토글로만 점등(5-I).

실행: python analysis/audit/probe_adx_kill.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "analysis"))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "src", "wrf"))

import build_dataset as bd  # noqa: E402
import labels as lab  # noqa: E402
import calibration as cal  # noqa: E402
import detectors as det  # noqa: E402

REV_SETUPS = {"MR", "RV", "BR"}
FLOOR = 0.58
KILL_C = -0.5           # _impulse_kill와 동일 수위
LEG_ALIVE_MIN = 2       # WRF_REV_IK_ALIVE 기본과 동일


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
        return (float("nan"), 0, 0, 0.0)
    w = sum(1 for r in rows if r["tb_win"])
    sr = sum(r["tb_r"] for r in rows if r["tb_r"] is not None)
    return (100.0 * w / n, w, n, sr)


def _fmt(rows, label):
    wr, w, n, sr = _stats(rows)
    return f"{label:22s} n={n:3d} WR={wr:5.1f}% ({w}W/{n-w}L) ΣR={sr:+6.2f}"


def main():
    rows = bd.load_snapshots(os.path.join(_ROOT, "data", "research"))
    # 심볼별 전체 adx 분포(라이브 자기분포 근사) + snapshot_id→raw
    adx_by_sym = defaultdict(list)
    raw_by_id = {}
    for r in rows:
        if r.get("schema_version") != 3:
            continue
        raw = r.get("raw") or {}
        raw_by_id[r.get("snapshot_id")] = raw
        a = raw.get("adx")
        if a is not None:
            adx_by_sym[r.get("symbol")].append(a)
    for s in adx_by_sym:
        adx_by_sym[s].sort()

    df = lab.candidate_dataset(rows)
    dec = df[df["tb_win"].notna()].copy()
    recs = [r for r in dec.to_dict("records") if r["setup"] in REV_SETUPS]
    for r in recs:
        raw = raw_by_id.get(r["snapshot_id"], {})
        r["_raw"] = raw
        r["_adx_pct"] = _pct_rank(adx_by_sym.get(r["symbol"], []), raw.get("adx"))
        r["_leg_alive"] = det._leg_alive_n(raw, r["dir"])

    def killed(r, tau):
        return (r["_adx_pct"] is not None and r["_adx_pct"] >= tau
                and r["_leg_alive"] >= LEG_ALIVE_MIN)

    def recompute_fire(r, tau):
        """킬 적용 후 prior 경로 p_hat 재계산 → 발사판정(닫기만)."""
        if not r["fire"]:
            return False  # 킬은 신규발사 없음
        if not killed(r, tau):
            return True   # 미킬 → 기존 발사 유지
        C_new = min(r["C"], KILL_C)
        p_new = cal.prior_p_hat(r["setup"], C_new, r["L"], r["F"])
        return bool(p_new >= (r.get("win_floor") or FLOOR))

    print(f"=== 반전(MR/RV/BR) 결판 {len(recs)}건 "
          f"(long {sum(r['dir']=='long' for r in recs)} / "
          f"short {sum(r['dir']=='short' for r in recs)}) ===")
    print(f"킬 규칙: adx_pct ≥ τ ∧ leg_alive ≥ {LEG_ALIVE_MIN} → C:=min(C,{KILL_C})  (양방향 대칭)\n")

    base_fired = {d: [r for r in recs if r["fire"] and r["dir"] == d]
                  for d in ("long", "short")}
    print("[베이스라인 발사집합]")
    for d in ("short", "long"):
        print("  " + _fmt(base_fired[d], f"{d}"))
    print()

    for tau in (0.5, 0.6, 0.7):
        print(f"[τ={tau:.1f}] 킬 후 발사집합 + FN(제거된 승리)·TP(제거된 패배)")
        for d in ("short", "long"):
            fired = base_fired[d]
            kept = [r for r in fired if recompute_fire(r, tau)]
            removed = [r for r in fired if not recompute_fire(r, tau)]
            rem_w = [r for r in removed if r["tb_win"]]
            rem_l = [r for r in removed if not r["tb_win"]]
            print("  " + _fmt(kept, f"{d} 잔존"))
            print(f"    └ 제거 {len(removed)}건: 패배(정타)={len(rem_l)} · 승리(FN)={len(rem_w)}"
                  + (f"  FN비율={len(rem_w)}/{len(rem_l)}" if rem_l else "  (제거된 패배 0)"))
        # Gate-In ① 숏 잔존 WR
        sk = [r for r in base_fired["short"] if recompute_fire(r, tau)]
        wr_s, _, n_s, sr_s = _stats(sk)
        lk = [r for r in base_fired["long"] if recompute_fire(r, tau)]
        _, _, _, sr_l0 = _stats(base_fired["long"])
        _, _, _, sr_l1 = _stats(lk)
        g1 = "✅" if (n_s and wr_s >= FLOOR * 100) else "❌"
        g2 = "✅" if sr_l1 >= sr_l0 - 1e-9 else "❌"
        print(f"    Gate-In: ①숏WR≥58%={g1}({wr_s:.0f}%)  ②롱ΣR비악화={g2}({sr_l0:+.2f}→{sr_l1:+.2f})")
        print()

    # 시간 2분할 일관성(τ=0.6)
    print("[시간 2분할 일관성 τ=0.6] — 숏 발사집합 잔존 WR")
    sh = sorted([r for r in base_fired["short"]], key=lambda r: r["ts"])
    half = len(sh) // 2
    for lab_, seg in [("전반", sh[:half]), ("후반", sh[half:])]:
        kept = [r for r in seg if recompute_fire(r, 0.6)]
        wr, w, n, sr = _stats(kept)
        print(f"  {lab_}: 잔존 n={n} WR={wr:.0f}% ΣR={sr:+.2f}")
    print("\n주: 표본 소수·자기상관 → 통계 판정 아님. Phase3 점등은 기본 OFF 토글.")


if __name__ == "__main__":
    main()
