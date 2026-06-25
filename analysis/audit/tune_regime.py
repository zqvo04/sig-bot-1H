"""실데이터로 Pillar1 승격신호의 'DIR vs CHOP' 판별력을 진단하고 파라미터를 튜닝.
핵심: 현재 slope_persist≥0.70 / ER-pctl≥0.70이 너무 느슨 → chop 42% 오승격(FP). 더 나은
판별자(순드리프트 magnitude 추가)와 임계를 실데이터에서 sweep해 FN회수↑·FP↓ 최적점 탐색."""
import os, sys, json
sys.path.insert(0, 'src'); sys.path.insert(0, 'analysis')
import numpy as np, pandas as pd
import config
from build_dataset import fwd_ret

SYMS = ["BTC-USDT","ETH-USDT","HYPE-USDT"]
DIR_RET, CHOP_RET = 0.02, 0.01

def load(sym):
    rows=[]
    with open(f"data/research/{sym}/2026-06.jsonl") as f:
        for l in f:
            if not l.strip(): continue
            r=json.loads(l)
            if "raw" in r and r.get("p0") and r["raw"].get("adx") is not None: rows.append(r)
    rows.sort(key=lambda x:x["ts"]); return rows

def signals(close):  # close: list up to current bar
    c=pd.Series(close,dtype=float); ma20=c.rolling(20).mean()
    lb=min(40,len(c)-1)
    seg=c.iloc[-lb:].values
    nc=abs(seg[-1]-seg[0]); tc=sum(abs(seg[i]-seg[i-1]) for i in range(1,len(seg)))
    er=nc/tc if tc>0 else 1.0
    mdiff=ma20.diff().iloc[-20:].dropna()
    sp=float(max((mdiff>0).mean(),(mdiff<0).mean())) if len(mdiff)>=10 else 0.5
    drift=abs(c.iloc[-1]-c.iloc[-20])/c.iloc[-1] if len(c)>20 else 0.0
    # ER 백분위
    d=c.diff().abs(); net=(c-c.shift(lb)).abs(); ers=(net/d.rolling(lb).sum())
    ers=ers[np.isfinite(ers)].iloc[-150:]
    erp=float((ers<=er).mean()) if len(ers)>=20 else None
    # 회귀 R^2 (대안 판별자)
    x=np.arange(len(seg));
    try: r2=float(np.corrcoef(x,seg)[0,1]**2)
    except: r2=0.0
    return dict(er=er, sp=sp, drift=float(drift), erp=erp, r2=r2, adx=None)

rows_all={s:load(s) for s in SYMS}
rec=[]
for s in SYMS:
    rows=rows_all[s]; closes=[float(r["p0"]) for r in rows]
    for i in range(60,len(rows)):
        sg=signals(closes[:i+1]); adx=rows[i]["raw"]["adx"]
        r24=fwd_ret(rows[i].get("path") or {},24,realistic=True)
        if r24 is None: continue
        lab=("DIR_DOWN" if r24<=-DIR_RET else "DIR_UP" if r24>=DIR_RET else "CHOP" if abs(r24)<CHOP_RET else "GRAY")
        sg.update(adx=adx, fwd=lab, r24=r24); rec.append(sg)
df=pd.DataFrame(rec)
# 승격-결정 구간: adx<25 & 추세/스퀴즈 아닌 곳(=현재 RANGING로 떨어지는 바)에서만 승격이 의미
elig=df[df.adx<25].copy()
print("="*82); print(f"Pillar1 승격신호 판별력 (승격-결정구간 adx<25, n={len(elig)})"); print("="*82)
print("\n■ 신호별 DIR vs CHOP 평균 (분리도가 클수록 좋은 판별자)")
for sig in ("sp","drift","er","erp","r2"):
    dn=elig[elig.fwd=="DIR_DOWN"][sig].mean(); up=elig[elig.fwd=="DIR_UP"][sig].mean()
    ch=elig[elig.fwd=="CHOP"][sig].mean()
    print(f"  {sig:<6} DIR_DOWN={dn:.3f}  DIR_UP={up:.3f}  CHOP={ch:.3f}   (DIR평균−CHOP={(np.nanmean([dn,up])-ch):+.3f})")

def evalrule(fn, name):
    e=elig.copy(); e["prom"]=e.apply(fn,axis=1)
    dirset=e[e.fwd.isin(["DIR_DOWN","DIR_UP"])]; chop=e[e.fwd=="CHOP"]
    rec_=dirset.prom.mean()*100 if len(dirset) else 0
    recd=e[(e.fwd=="DIR_DOWN")].prom.mean()*100
    fp=chop.prom.mean()*100 if len(chop) else 0
    prom=e[e.prom]
    prec=prom.fwd.isin(["DIR_DOWN","DIR_UP"]).mean()*100 if len(prom) else 0
    print(f"  {name:<42} 추세회수 {rec_:4.0f}% (숏 {recd:4.0f}%) | chop오승격 {fp:4.0f}% | 승격정밀도 {prec:4.0f}% | 승격수 {len(prom)}")
    return rec_,fp

print("\n■ 규칙 sweep (목표: 추세회수↑ · chop오승격↓)")
print("  [현행]")
evalrule(lambda r: (r.sp>=0.70) or (r.erp is not None and r.erp>=0.70), "현행: sp≥.70 OR erp≥.70")
print("  [순드리프트 게이트 추가: sp AND drift]")
for s in (0.75,0.80,0.85):
    for d in (0.015,0.02,0.025):
        evalrule(lambda r,s=s,d=d: (r.sp>=s and r.drift>=d), f"sp≥{s} AND drift≥{d:.3f}")
print("  [드리프트 + ER백분위 보조]")
for s,d,p in [(0.80,0.02,0.90),(0.85,0.02,0.90),(0.80,0.025,0.85)]:
    evalrule(lambda r,s=s,d=d,p=p: (r.sp>=s and r.drift>=d) or (r.erp is not None and r.erp>=p and r.drift>=0.015),
             f"(sp≥{s}&drift≥{d}) OR (erp≥{p}&drift≥.015)")
print("  [회귀 R² 대안]")
for r2t,d in [(0.5,0.015),(0.6,0.02),(0.7,0.02)]:
    evalrule(lambda r,r2t=r2t,d=d: r.r2>=r2t and r.drift>=d, f"R²≥{r2t} AND drift≥{d}")
