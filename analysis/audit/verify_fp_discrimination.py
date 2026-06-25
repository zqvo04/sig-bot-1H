"""FP-통제 검증 — '하드게이트→점수강등+floor위임'이 FP-안전하려면 floor+EV 게이트가
실제로 승자/패자를 분리해야 한다(floor 통과분 승률 > 미통과분). 실데이터 결판결과로 확인.
또한 NEW 발사집합의 실현 승률이 floor를 지키는지(=FP 낮음) 본다. ※표본 소(≈5일)·참고용."""
import os, sys
sys.path.insert(0, 'src'); sys.path.insert(0, 'src/wrf'); sys.path.insert(0, 'analysis')
import numpy as np, pandas as pd
import config
import wrf.calibration as cal
from build_dataset import load_snapshots
import labels as lab

FLOOR = config.WRF_WIN_FLOOR
df = lab.candidate_dataset(load_snapshots('data/research'))
df = df[df[["C","L","F","rr"]].notna().all(axis=1)].copy()

def newfire(r):
    config.WRF_PRIOR_MIN_AXIS_SOFT = True
    p = cal.prior_p_hat(r.setup, r.C, r.L, r.F)
    floor = r.win_floor if pd.notna(r.win_floor) else FLOOR
    ev = p*r.rr - (1-p)
    rr_ok = ev >= config.WRF_EV_MIN and r.rr >= config.WRF_EV_RR_FLOOR
    return bool(p>=floor and (r.veto_n or 0)==0 and rr_ok), p
res = [newfire(r) for r in df.itertuples()]
df["new_fire"] = [x[0] for x in res]; df["p_new"] = [x[1] for x in res]
dec = df[df.tb_win.notna()].copy()   # 결판(WIN/LOSS)

def wr(g):
    return (round(g.tb_win.mean()*100,1), len(g)) if len(g) else (None,0)

print("="*78); print(f"FP-통제 검증 (결판 후보 {len(dec)}건, floor={FLOOR})"); print("="*78)

print("\n■ 게이트 분별력: NEW 발사 vs 미발사 (결판 기준) — 발사>미발사면 게이트가 FP를 거른다")
w_f,n_f = wr(dec[dec.new_fire]); w_n,n_n = wr(dec[~dec.new_fire])
print(f"  NEW 발사     승률 {w_f}% (n={n_f})")
print(f"  NEW 미발사   승률 {w_n}% (n={n_n})")
print(f"  → 분별 {'✅ 발사>미발사(게이트 유효)' if (w_f or 0)>(w_n or 0) else '⚠ 분별 약함(표본 소)'}")

print("\n■ floor 단독 분별 (p_new≥floor vs <floor)")
w_hi,n_hi = wr(dec[dec.p_new>=FLOOR]); w_lo,n_lo = wr(dec[dec.p_new<FLOOR])
print(f"  p̂≥floor 승률 {w_hi}% (n={n_hi}) | p̂<floor 승률 {w_lo}% (n={n_lo})")

print("\n■ 셋업별 결판 승률(전체 precond 통과) — RV(숏 FN 핵심 경로)")
for s in sorted(dec.setup.unique()):
    g=dec[dec.setup==s]; ww,nn=wr(g)
    gf=g[g.new_fire]; wf,nf=wr(gf)
    print(f"  {s:<4} 전체 {ww}% (n={nn}) | NEW발사분 {wf}% (n={nf})")

print("\n■ 방향별 결판 승률")
for d in ("long","short"):
    g=dec[dec.dir==d]; ww,nn=wr(g)
    print(f"  {d:<6} {ww}% (n={nn})  발사 {wr(g[g.new_fire])}")

print("\n■ NEW 발사집합 vs floor (FP 판정)")
w_all,n_all = wr(dec[dec.new_fire])
print(f"  NEW 발사 실현승률 {w_all}% (결판 {n_all}건) vs floor {FLOOR*100:.0f}% → "
      f"{'충족(FP 통제)' if (w_all or 0)>=FLOOR*100 else '미달(표본 소·참고)'}")
