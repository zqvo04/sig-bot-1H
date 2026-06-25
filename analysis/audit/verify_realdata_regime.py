"""실데이터 레짐 검증 — Pillar1(FN의 지배적 레버)을 봇 자신의 저장데이터로 재현.

JSONL은 p0(실제 1H 종가)·raw.adx(실제 ADX)·path(실제 forward 72h)를 저장한다.
classify_market_regime은 종가 + ADX/BB(종가파생) dict만 쓰므로 OLD↔NEW 레짐을 실제 바에서
'정확히' 재계산할 수 있다. 각 스냅샷을 '이후 실제 가격이 한 일'(path)로 라벨링해 혼동행렬을
만든다: 추세였는데 OLD가 RANGING(=TF차단)→NEW가 TRENDING으로 회수(FN↓)? chop을 NEW가
잘못 승격(FP↑)? 숏(하락추세) FN을 따로 본다."""
import os, sys, json
sys.path.insert(0, 'src'); sys.path.insert(0, 'src/wrf'); sys.path.insert(0, 'analysis')
import numpy as np, pandas as pd
import config, analysis_engine as ae
from build_dataset import fwd_ret, path_efficiency

SYMS = ["BTC-USDT", "ETH-USDT", "HYPE-USDT"]
DIR_RET = 0.02   # |24h fwd| ≥ 2% → 추세(스윙) | < 1% → chop
CHOP_RET = 0.01

def load(sym):
    rows = []
    with open(f"data/research/{sym}/2026-06.jsonl") as f:
        for l in f:
            if not l.strip(): continue
            r = json.loads(l)
            if "raw" in r and r.get("p0") and r["raw"].get("adx") is not None:
                rows.append(r)
    rows.sort(key=lambda x: x["ts"])
    return rows

def bb_from_close(close: pd.Series):
    mid = close.rolling(20).mean(); sd = close.rolling(20).std()
    up, lo = mid + 2*sd, mid - 2*sd
    bw = ((up - lo) / mid).iloc[-1]
    bw_ser = ((up - lo) / mid)
    avg = bw_ser.iloc[-50:].mean() if bw_ser.notna().sum() >= 50 else bw_ser.iloc[-20:].mean()
    if not np.isfinite(bw): return None
    return {"available": True, "band_width": float(bw), "avg_band_width": float(avg),
            "squeeze": bool(bw < avg * config.REGIME_SQUEEZE_RATIO and avg > 0)}

def regime_at(close_hist, adx_val, NEW):
    for k in ("WRF_REGIME_SLOPE_PERSIST","WRF_REGIME_ER_PCTL","WRF_REGIME_ER_TREND"):
        setattr(config, k, NEW)
    df = pd.DataFrame({"open": close_hist, "high": close_hist, "low": close_hist,
                       "close": close_hist, "volume": np.full(len(close_hist), 1e3)})
    bb = bb_from_close(df["close"])
    if bb is None: return None
    return ae.classify_market_regime(df, {"adx": adx_val}, bb)["regime"]

def fwd_label(path):
    r24 = fwd_ret(path, 24, realistic=True)
    if r24 is None: return None, None
    if r24 <= -DIR_RET: return "DIR_DOWN", r24
    if r24 >=  DIR_RET: return "DIR_UP", r24
    if abs(r24) < CHOP_RET: return "CHOP", r24
    return "GRAY", r24

# ── 집계 ─────────────────────────────────────────────────────────────────
rec = []
match_old = 0; match_n = 0
for sym in SYMS:
    rows = load(sym)
    closes = [float(r["p0"]) for r in rows]
    for i in range(60, len(rows)):
        ch = closes[:i+1]
        adx = rows[i]["raw"]["adx"]
        o = regime_at(ch, adx, NEW=False); n = regime_at(ch, adx, NEW=True)
        if o is None: continue
        lab, r24 = fwd_label(rows[i].get("path") or {})
        if lab is None: continue
        # sanity: recomputed OLD vs bot's stored regime
        stored = rows[i]["ctx"].get("regime_1h")
        if stored in ("RANGING","TRENDING","SQUEEZE","EXPLOSIVE"):
            match_n += 1; match_old += int(o == stored)
        rec.append({"sym": sym, "old": o, "new": n, "fwd": lab, "r24": r24,
                    "ema4": rows[i]["raw"].get("ema_4h")})
df = pd.DataFrame(rec)
TFBLOCK = ("RANGING","SQUEEZE","UNKNOWN")   # TF 라우팅이 막히는 레짐

print("="*82)
print(f"실데이터 레짐 검증 (3심볼, 평가 스냅샷 {len(df)}건, fwd=path 24h 실현)")
print("="*82)
print(f"[하니스 검증] 재계산 OLD-레짐 ↔ 봇 저장 레짐 일치율: {match_old/max(1,match_n)*100:.1f}% (n={match_n})")
print(f"  ※ 봇 저장은 코드버전 혼재(과거엔 ER승격 없음) → 100% 아님이 정상. 종가재구성 근사도 포함.")

print(f"\n■ 전체 레짐 분포 (TRENDING 비율 = TF 라우팅 가능 비율)")
for col in ("old","new"):
    vc = df[col].value_counts()
    tr = vc.get("TRENDING",0)/len(df)*100
    print(f"  {col.upper():<4} TRENDING {vc.get('TRENDING',0):>4} ({tr:4.1f}%) | RANGING {vc.get('RANGING',0):>4} "
          f"| SQUEEZE {vc.get('SQUEEZE',0):>3} | EXPLOSIVE {vc.get('EXPLOSIVE',0):>3}")

def confusion(fwd_classes, title):
    sub = df[df.fwd.isin(fwd_classes)]
    blocked_old = sub[sub.old.isin(TFBLOCK)]
    recov = blocked_old[blocked_old.new == "TRENDING"]
    print(f"\n■ {title}: forward={fwd_classes} 표본 {len(sub)}건")
    print(f"   OLD가 TF차단(RANGING/SQUEEZE) {len(blocked_old)}건 중 → NEW가 TRENDING 회수 "
          f"{len(recov)}건 ({len(recov)/max(1,len(blocked_old))*100:.0f}%)")
    return sub, recov

# FN: 추세였는데 막혔던 것 회수 (특히 하락=숏)
sub_dn, recov_dn = confusion(["DIR_DOWN"], "FN(숏) — 실제 하락추세")
sub_up, recov_up = confusion(["DIR_UP"], "FN(롱) — 실제 상승추세")
# 숏 정합성: 회수된 하락추세 바에서 4H EMA가 실제로 약세(=-1)였나 → 숏 TF 생성 가능
if len(recov_dn):
    align = (recov_dn.ema4 == -1).mean()*100
    print(f"   ↳ 회수된 하락추세 바 중 4H EMA 약세(숏 TF 생성가능) 비율: {align:.0f}%")

# FP: chop을 잘못 승격
sub_ch = df[df.fwd == "CHOP"]
fp_old = (sub_ch.old == "TRENDING").mean()*100
fp_new = (sub_ch.new == "TRENDING").mean()*100
print(f"\n■ FP 통제: 실제 CHOP {len(sub_ch)}건 중 TRENDING 오승격률  OLD {fp_old:.1f}% → NEW {fp_new:.1f}%")
print(f"   (낮을수록 좋음 · NEW가 OLD 대비 +{fp_new-fp_old:.1f}%p)")

# 종합 정밀도: NEW가 새로 TRENDING으로 만든 바들의 forward가 실제 추세였나(정밀도)
new_promoted = df[(df.new=="TRENDING") & (df.old.isin(TFBLOCK))]
if len(new_promoted):
    prec = new_promoted.fwd.isin(["DIR_UP","DIR_DOWN"]).mean()*100
    chop_rate = (new_promoted.fwd=="CHOP").mean()*100
    print(f"\n■ NEW 신규 승격 {len(new_promoted)}건의 forward 정밀도: 실제추세 {prec:.0f}% / 실제chop {chop_rate:.0f}%")
    print(f"   (실제추세↑·chop↓ 이면 'FN을 풀되 FP는 낮음'을 의미)")
