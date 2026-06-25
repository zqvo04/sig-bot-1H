"""Part A — Pillar-3 재채점(real data). 저장된 후보의 C/L/F/rr/tb_win을 그대로 두고
발사 게이트만 OLD(min-axis 하드절벽 + RR>=1.5) vs NEW(min-axis 연속 + EV게이트)로 바꿔
'동일 후보집합'에서 발사 수·실현승률·기대R이 어떻게 변하는지 측정한다.
※ 이 파트는 게이트 변경(Pillar3)만 격리한다 — 레짐/디텍터/레벨 변경(Pillar1/2/4)은
  후보집합 자체를 바꾸므로 저장데이터로 재현 불가 → Part B(합성 컴포넌트 테스트)에서 검증."""
import os, sys
sys.path.insert(0, 'src'); sys.path.insert(0, 'src/wrf'); sys.path.insert(0, 'analysis')
import numpy as np, pandas as pd
import config
import wrf.calibration as cal
from build_dataset import load_snapshots
import labels as lab

FLOOR = config.WRF_WIN_FLOOR
rows = load_snapshots('data/research')
df = lab.candidate_dataset(rows)
df = df[df[["C","L","F","rr"]].notna().all(axis=1)].copy()

def p_hat_mode(setup, C, L, F, soft):
    config.WRF_PRIOR_MIN_AXIS_SOFT = soft
    return cal.prior_p_hat(setup, C, L, F)

def fire(row, soft, ev):
    p = p_hat_mode(row.setup, row.C, row.L, row.F, soft)
    floor = row.win_floor if pd.notna(row.win_floor) else FLOOR
    veto_ok = (row.veto_n or 0) == 0
    if ev:
        e = p*row.rr - (1.0-p)
        rr_ok = (e >= config.WRF_EV_MIN) and (row.rr >= config.WRF_EV_RR_FLOOR)
    else:
        rr_ok = row.rr >= 1.5
    return bool(p >= floor and veto_ok and rr_ok), p

def summarize(mask, label):
    g = df[mask]
    dec = g[g.tb_win.notna()]
    res = g[g.tb_r.notna()]
    rr = res.tb_r.astype(float)
    pos, neg = rr[rr>0].sum(), -rr[rr<0].sum()
    win = dec.tb_win.mean()*100 if len(dec) else float('nan')
    return {
        "label": label, "fired": int(mask.sum()),
        "decided": len(dec), "win%": round(win,1) if len(dec) else None,
        "expR": round(rr.mean(),3) if len(res) else None,
        "PF": (round(pos/neg,2) if neg>0 else float('inf')) if len(res) else None,
    }

# OLD reproduction (hard min-axis + RR>=1.5) and NEW (soft + EV)
old_fire, old_p = zip(*[fire(r, soft=False, ev=False) for r in df.itertuples()])
new_fire, new_p = zip(*[fire(r, soft=True,  ev=True ) for r in df.itertuples()])
df["old_fire"] = old_fire; df["new_fire"] = new_fire
df["stored_fire"] = df["fire"].fillna(False)

print("="*78)
print(f"PART A — Pillar-3 게이트 재채점 (저장 후보 {len(df)}건, floor={FLOOR})")
print("="*78)
# Sanity: recomputed OLD vs stored live fire should match closely
match = (df.old_fire == df.stored_fire).mean()*100
print(f"[하니스 검증] 재현 OLD-fire ↔ 저장 live-fire 일치율: {match:.1f}%  "
      f"(저장발사 {int(df.stored_fire.sum())} / 재현OLD {int(df.old_fire.sum())})")

print("\n■ 발사집합 비교 (전체)")
for r in (summarize(df.old_fire, "OLD(하드 min-axis + RR≥1.5)"),
          summarize(df.new_fire, "NEW(연속 min-axis + EV게이트)")):
    print(f"  {r['label']:<32} 발사 {r['fired']:>3} | 결판 {r['decided']:>3} | "
          f"승률 {r['win%']}% | 기대R {r['expR']} | PF {r['PF']}")

print("\n■ 방향별 발사 수 (False-Negative 회수: 특히 숏)")
for d in ("long","short"):
    om = df.old_fire & (df.dir==d); nm = df.new_fire & (df.dir==d)
    print(f"  {d:<6} OLD {int(om.sum()):>3} → NEW {int(nm.sum()):>3}  (Δ{int(nm.sum())-int(om.sum()):+d})")

print("\n■ 셋업별 발사 수")
for s in sorted(df.setup.unique()):
    om = df.old_fire & (df.setup==s); nm = df.new_fire & (df.setup==s)
    print(f"  {s:<4} OLD {int(om.sum()):>3} → NEW {int(nm.sum()):>3}  (Δ{int(nm.sum())-int(om.sum()):+d})")

print("\n■ 새로 회수된 후보(NEW만 발사)의 실현 품질 — FP 점검")
recovered = df.new_fire & (~df.old_fire)
print(f"  신규발사 {int(recovered.sum())}건 | " + str(summarize(recovered, "recovered")))
rg = df[recovered]; rdec = rg[rg.tb_win.notna()]
if len(rdec):
    print(f"  신규발사 결판 {len(rdec)}건 실현승률 {rdec.tb_win.mean()*100:.1f}% vs floor {FLOOR*100:.0f}%")

print("\n■ 회수 후보 상세 (약축 진단 — 연속페널티가 적정한가)")
print("  setup dir  regime    btc_macro    C      L      F    minax   p_old  p_new   rr   tb_win")
for r in df[recovered].itertuples():
    p_o = p_hat_mode(r.setup, r.C, r.L, r.F, soft=False)
    p_n = p_hat_mode(r.setup, r.C, r.L, r.F, soft=True)
    print(f"  {r.setup:<4} {r.dir:<5} {str(r.regime_1h):<9} {str(r.btc_macro):<11} "
          f"{r.C:+.2f}  {r.L:+.2f}  {r.F:+.2f}  {min(r.C,r.L,r.F):+.2f}  "
          f"{p_o:.3f}  {p_n:.3f}  {r.rr:.2f}  {r.tb_win}")

print("\n■ 참고: 저장 live-fire(코드버전 혼재)를 OLD로 본 비교")
for r in (summarize(df.stored_fire, "STORED live-fire(실제 이력)"),
          summarize(df.new_fire,   "NEW(재채점)")):
    print(f"  {r['label']:<28} 발사 {r['fired']:>3} | 결판 {r['decided']:>3} | "
          f"승률 {r['win%']}% | 기대R {r['expR']} | PF {r['PF']}")
