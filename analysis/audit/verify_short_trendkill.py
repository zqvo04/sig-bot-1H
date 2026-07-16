"""[개선-Phase0] 숏 성과붕괴 진단 재현 + 사전등록(pre-registration) — 측정 전용.

Notion 내보내기 CSV 36건 진단(숏 승률 ~35%·PF 0.57)을 리포 JSONL 전량 후보로
재확인한다. 라이브 코드 미변경(analysis/audit 관례). calibrate와 동일 파이프
(build_dataset.load_snapshots + labels.candidate_dataset)를 써서 '결판(WIN/LOSS)'
후보 모집단을 만들고, 저장된 raw 피처(무상태·자기분포 재현)를 snapshot_id로 조인한다.

⚠️ 순환(circularity) 주의 — 사전등록의 핵심:
  research 스냅샷의 Ret 4h/12h/24h 는 '진입 후 실현' FORWARD 수익률(라벨)이다.
  숏은 (승 ⟺ forward_ret<0) 이므로 이를 예측피처로 쓰면 동어반복이다. 따라서
  본 검증은 '진입시점 trailing 피처'(adx/rsi/bb_pctb/dist_vwap_atr/vol_ratio/macd)
  만 후보 판별에 사용한다. ret_* 는 라벨 확인용으로만 출력한다.

사전등록 가설(H1):
  RV/BR 숏 결판 중, 진입시점 추세강도가 강한(자기분포 adx 백분위 ≥ τ) 부분모집단의
  승률이 나머지보다 유의하게 낮다. 이 부분모집단을 발사에서 제거(닫기만)하면 숏
  발사집합 승률이 상승하고 롱은 대칭 적용에도 비악화한다.

출력:
  [A] 방향별 성과(전체 결판 / 발사분)
  [B] 셀(setup|regime|macro) × 방향 승률 — '방향 희석' 정량화
  [C] 반전숏 결판의 trailing 피처 win vs loss (비순환) + ret_24h(순환·참고)
  [D] adx 백분위 컷 반사실(단조성 점검, 판정 아님)

실행: python analysis/audit/verify_short_trendkill.py
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

REV_SETUPS = {"MR", "RV", "BR"}
# 진입시점 trailing 피처(비순환) — 자기분포 백분위/절대 그대로 저장된 raw
TRAIL = ["adx", "adx_slope", "rsi", "rsi_4h", "bb_pctb",
         "dist_vwap_atr", "dist_ema20_atr", "vol_ratio", "macd", "atr_pct"]


def _wr(rows):
    n = len(rows)
    w = sum(1 for r in rows if r["tb_win"])
    return (100.0 * w / n) if n else float("nan"), w, n


def _pf_sumr(rows):
    gp = sum(r["tb_r"] for r in rows if r["tb_r"] is not None and r["tb_r"] > 0)
    gl = abs(sum(r["tb_r"] for r in rows if r["tb_r"] is not None and r["tb_r"] <= 0))
    pf = (gp / gl) if gl > 0 else float("inf")
    sr = sum(r["tb_r"] for r in rows if r["tb_r"] is not None)
    return pf, sr


def _pct_rank(sorted_vals, x):
    """자기분포 대비 x의 백분위(≤ 비율). sorted_vals 오름차순."""
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


def main():
    rows = bd.load_snapshots(os.path.join(_ROOT, "data", "research"))
    # snapshot_id → raw (trailing 피처 조인용)
    raw_by_id = {r.get("snapshot_id"): (r.get("raw") or {})
                 for r in rows if r.get("schema_version") == 3}

    df = lab.candidate_dataset(rows)
    if df.empty:
        print("표본 0 — 중단")
        return
    dec = df[df["tb_win"].notna()].copy()
    recs = dec.to_dict("records")
    for r in recs:
        raw = raw_by_id.get(r["snapshot_id"], {})
        for k in TRAIL:
            r[k] = raw.get(k)

    print(f"=== 결판 후보 모집단: {len(recs)}건 "
          f"(long {sum(r['dir']=='long' for r in recs)} / "
          f"short {sum(r['dir']=='short' for r in recs)}) ===\n")

    # [A] 방향별 성과
    print("[A] 방향별 성과 (결판 전체 / 발사분)")
    for label, pop in [("결판전체", recs),
                       ("발사분", [r for r in recs if r["fire"]])]:
        for side in ("long", "short"):
            d = [r for r in pop if r["dir"] == side]
            wr, w, n = _wr(d)
            pf, sr = _pf_sumr(d)
            print(f"  {label:6s} {side:5s}: n={n:3d} WR={wr:5.1f}% "
                  f"PF={pf:4.2f} ΣR={sr:+6.2f}")
    print()

    # [B] 셀 × 방향 승률 — 방향 희석
    print("[B] 셀(setup|regime|macro) × 방향 — 방향 희석 정량화")
    cells = defaultdict(lambda: {"long": [], "short": []})
    for r in recs:
        cells[r["cell"]][r["dir"]].append(r)
    print(f"  {'cell':28s} {'long':>14s} {'short':>14s}")
    for cell in sorted(cells):
        lo, sh = cells[cell]["long"], cells[cell]["short"]
        wl, _, nl = _wr(lo)
        ws, _, ns = _wr(sh)
        if nl + ns == 0:
            continue
        ls = f"{wl:4.0f}%({nl})" if nl else "  -   "
        ss = f"{ws:4.0f}%({ns})" if ns else "  -   "
        flag = " ← 희석" if (nl and ns and wl - ws >= 25) else ""
        print(f"  {cell:28s} {ls:>14s} {ss:>14s}{flag}")
    print()

    # [C] 반전숏 결판의 trailing 피처 win vs loss (비순환) + ret_24h(순환·참고)
    rev_short = [r for r in recs if r["dir"] == "short" and r["setup"] in REV_SETUPS]
    wins = [r for r in rev_short if r["tb_win"]]
    loss = [r for r in rev_short if not r["tb_win"]]
    print(f"[C] 반전(MR/RV/BR)숏 결판 {len(rev_short)}건 — "
          f"win {len(wins)} / loss {len(loss)}: 진입시점 trailing 피처")

    def _mean(rs, k):
        v = [r[k] for r in rs if r.get(k) is not None]
        return (sum(v) / len(v)) if v else float("nan")

    for k in TRAIL:
        mw, ml = _mean(wins, k), _mean(loss, k)
        print(f"  {k:15s} WIN={mw:+9.3f}  LOSS={ml:+9.3f}  Δ={mw-ml:+9.3f}")
    print("  --- (참고·순환) forward 라벨 ---")
    print(f"  {'exret_24h':15s} WIN={_mean(wins,'exret_24h'):+9.4f}  "
          f"LOSS={_mean(loss,'exret_24h'):+9.4f}  ← 숏은 승⟺forward<0 (동어반복)")
    print()

    # [D] adx 백분위 컷 반사실 — 단조성 점검(판정 아님)
    print("[D] 반전숏: adx 자기분포 백분위 상위 컷 → 제거 부분집단 승률 (단조성)")
    adx_vals = sorted(r["adx"] for r in rev_short if r.get("adx") is not None)
    for r in rev_short:
        r["_adx_pct"] = _pct_rank(adx_vals, r.get("adx"))
    for tau in (0.5, 0.6, 0.7, 0.8):
        killed = [r for r in rev_short if (r.get("_adx_pct") or 0) >= tau]
        kept = [r for r in rev_short if (r.get("_adx_pct") or 0) < tau]
        wk, _, nk = _wr(killed)
        wr_keep, _, n_keep = _wr(kept)
        print(f"  τ={tau:.1f}: 제거 n={nk:2d} WR={wk:5.1f}%  |  "
              f"잔존 n={n_keep:2d} WR={wr_keep:5.1f}%")
    print("\n주: 표본은 소수 독립사건(자기상관) — 방향 점검용이지 통계적 판정이 아니다.")


if __name__ == "__main__":
    main()
