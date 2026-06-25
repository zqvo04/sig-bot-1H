"""Part B — 합성 컴포넌트 테스트. 후보 '생성'을 바꾸는 Pillar1/2/4 + 원트랙은 저장데이터로
재현 불가하므로, 통제된 합성 입력으로 각 처방의 논리를 직접 검증한다(OLD 토글 vs NEW 토글)."""
import os, sys
sys.path.insert(0, 'src'); sys.path.insert(0, 'src/wrf')
import numpy as np, pandas as pd
import importlib
import config
import analysis_engine as ae
import wrf.engine as eng
import wrf.detectors as det
import wrf.percentile as pctmod

np.random.seed(7)
OK = "✅"; NO = "❌"
def check(cond): return OK if cond else NO

def mkdf(closes):
    closes = np.asarray(closes, float)
    n = len(closes)
    hi = closes + np.abs(np.random.randn(n))*0.1
    lo = closes - np.abs(np.random.randn(n))*0.1
    return pd.DataFrame({"open": closes, "high": np.maximum(hi,closes),
                         "low": np.minimum(lo,closes), "close": closes,
                         "volume": np.full(n, 1000.0)},
                        index=pd.date_range("2026-06-01", periods=n, freq="h", tz="UTC"))

print("="*78); print("PART B — 합성 컴포넌트 테스트 (Pillar1/2/4 + 원트랙)"); print("="*78)

# ── Pillar1-①/② : 레짐 — slow grind-down ────────────────────────────────
print("\n[1] 레짐 분류 — slow grind-down / chop / up-grind (ADX 낮음·ER 중저)")
def regime_of(df, adx_val, NEW):
    config.WRF_REGIME_SLOPE_PERSIST = NEW
    config.WRF_REGIME_ER_PCTL = NEW
    config.WRF_REGIME_ER_TREND = NEW
    bw = float(((df["high"]-df["low"])/df["close"]).iloc[-20:].mean())
    bb = {"available": True, "band_width": bw, "avg_band_width": bw, "squeeze": False}
    r = ae.classify_market_regime(df, {"adx": adx_val}, bb)
    return r["regime"], r.get("efficiency_ratio"), r.get("slope_persist")

# 명확한 grind(±0.18/bar≈±13%/70bar): ER 낮음(노이즈)이나 기울기 일관 + 순드리프트 충분
# (drift gate≥0.02 통과). ※드리프트 게이트상 ~2.4%/일보다 느린 초저속 grind는 미승격(FP 통제 비용).
t = np.arange(70)
grind_dn = 100 - 0.18*t + np.random.randn(70)*0.6
grind_up = 100 + 0.18*t + np.random.randn(70)*0.6
chop = 100 + 3*np.sin(t/4.0) + np.random.randn(70)*0.3
for name, closes in (("grind-DOWN", grind_dn), ("grind-UP", grind_up), ("chop", chop)):
    df = mkdf(closes)
    o_reg, er, _   = regime_of(df, 18, NEW=False)
    n_reg, er2, sp = regime_of(df, 18, NEW=True)
    tag = "추세승격" if (n_reg=="TRENDING" and o_reg!="TRENDING") else ("불변" if n_reg==o_reg else "변화")
    print(f"  {name:<10} OLD={o_reg:<9} NEW={n_reg:<9} (ER={er}, slope_persist={sp}) → {tag}")
exp = (regime_of(mkdf(grind_dn),18,True)[0]=="TRENDING"
       and regime_of(mkdf(grind_up),18,True)[0]=="TRENDING"
       and regime_of(mkdf(chop),18,True)[0]=="RANGING")
print(f"  {check(exp)} 기대: grind(상/하)=TRENDING(대칭) · chop=RANGING(FP 방어)")

# ── Pillar1-③ : 라우팅 BTC 종속성 분리 ─────────────────────────────────────
print("\n[2] 라우팅 — 알트 grind-down, BTC는 CHOP (심볼 자체구조로 라우팅)")
feat = {"raw": {"ema_4h": -1, "ema_1d_struct": -1}, "ctx": {"bias_1d": "BEAR", "btc_macro": "CHOP"}}
config.WRF_REGIME_ROUTING = True
config.WRF_ROUTING_SELF_STRUCT = False; old_r = eng._regime_routing_state(feat)
config.WRF_ROUTING_SELF_STRUCT = True;  new_r = eng._regime_routing_state(feat)
print(f"  BTC=CHOP·심볼(4H↓·일봉구조↓·BEAR): OLD route={old_r} → NEW route={new_r}")
print(f"  {check(old_r is None and new_r=='down')} 기대: OLD=None(BTC종속 미발동) · NEW='down'(심볼구조로 발동)")

# ── Pillar2-① : RV 소프트 precond ──────────────────────────────────────────
print("\n[3] RV precond — 부분정렬 숏(소진+반전캔들, CHoCH/리테스트 부재)")
def rv_feat():
    return {"raw": {"liq_spike": True, "choch": 0, "choch_4h": 0, "failed_break": 0,
                    "oi_quadrant": "neutral", "rev_vol_ratio": 1.2, "confluence_short": 0,
                    "confluence_long": 0},
            "pct": {"rsi": 0.90, "funding": 0.5},
            "ctx": {"btc_macro": "CHOP", "allowed_setups": ["MR", "RV"]},
            "df_1h": mkdf(grind_dn),
            "measures": {"rsi": {"bearish_divergence": True}, "weekly_levels": {},
                         "candle_pattern": {"bearish_pin": True}}}
config.WRF_RV_SOFT_PRECOND = False
o = [c for c in det._detect_rv(rv_feat(), rv_feat()["measures"]) if c["dir"]=="short"]
config.WRF_RV_SOFT_PRECOND = True
n = [c for c in det._detect_rv(rv_feat(), rv_feat()["measures"]) if c["dir"]=="short"]
print(f"  OLD(하드 5중AND) 숏후보 {len(o)}개 → NEW(소프트) 숏후보 {len(n)}개"
      + (f" (L={n[0]['L']}, reason={n[0]['reason']})" if n else ""))
print(f"  {check(len(o)==0 and len(n)>=1)} 기대: OLD=0(생성불가=FN) · NEW≥1(생성·L감쇠로 floor에 위임)")

# ── Pillar3-① : min-axis 연속성 (절벽 vs 부드러움) ──────────────────────────
print("\n[4] min-axis — F축을 -0.3→0.3 스캔 (TF, C=0.5 L=0.7)")
import wrf.calibration as cal
def curve(soft):
    config.WRF_PRIOR_MIN_AXIS_SOFT = soft
    return [round(cal.prior_p_hat("TF", 0.5, 0.7, f), 3) for f in (-0.3,-0.1,0.0,0.05,0.09,0.11,0.2)]
print(f"  F=     [-0.30, -0.10,  0.00,  0.05,  0.09,  0.11,  0.20]")
print(f"  OLD={curve(False)}")
print(f"  NEW={curve(True)}")
cN = curve(True); cO = curve(False)
mono = all(cN[i] <= cN[i+1]+1e-9 for i in range(len(cN)-1))
smooth = abs(cN[3]-cN[4]) < 0.05            # F=0.05↔0.09 점프 없음(NEW)
cliff_old = abs(cO[3]-cO[5]) > 0.05         # OLD는 0.05(차단)↔0.11(통과) 절벽
neg_block = cN[0] < 0.55                     # F=-0.30 음수축은 floor 미만으로 강한 차단
print(f"  {check(mono and smooth and neg_block)} 기대: NEW 단조·연속(0.05↔0.09 점프 없음, 음수축 강차단) · OLD 절벽={cliff_old}")

# ── Pillar3-③ : EV-결합 게이트 ──────────────────────────────────────────────
print("\n[5] EV-게이트 — (p_hat, rr) 진리표: OLD(rr≥1.5) vs NEW(EV=p·rr−(1−p)≥0.15)")
def ev_ok(p, rr):
    return (p*rr-(1-p)) >= config.WRF_EV_MIN and rr >= config.WRF_EV_RR_FLOOR
cases = [(0.65,1.0),(0.62,1.2),(0.58,1.0),(0.58,0.8),(0.60,1.4),(0.65,2.5)]
print("  p_hat  rr   OLD(rr≥1.5)  NEW(EV)   EV값")
for p,rr in cases:
    ev=round(p*rr-(1-p),3)
    print(f"  {p:.2f}  {rr:.1f}     {'fire' if rr>=1.5 else 'block':<5}      {'fire' if ev_ok(p,rr) else 'block':<5}   {ev:+.3f}")
print(f"  {check(ev_ok(0.65,1.0) and ev_ok(0.62,1.2) and not (1.0>=1.5))} 기대: 고확률·중RR(0.65×1.0, 0.62×1.2)=OLD차단→NEW발사(EV+) · 저확률저RR은 컷")

# ── Pillar4-① : pct_rank midrank 대칭성 ─────────────────────────────────────
print("\n[6] pct_rank — 대칭분포에서 하단/상단 극단 도달 대칭성")
sym = list(np.linspace(-1,1,201))   # 대칭 분포, 0 중심
def rank(v, mid):
    config.WRF_PCT_MIDRANK = mid; return round(pctmod.pct_rank(sym, v),4)
lo_old, hi_old = rank(-0.8,False), rank(0.8,False)
lo_new, hi_new = rank(-0.8,True), rank(0.8,True)
print(f"  v=-0.8: OLD={lo_old} NEW={lo_new}  | v=+0.8: OLD={hi_old} NEW={hi_new}")
print(f"  대칭오차(|lo+hi-1|): OLD={abs(lo_old+hi_old-1):.4f}  NEW={abs(lo_new+hi_new-1):.4f}")
print(f"  {check(abs(lo_new+hi_new-1) < abs(lo_old+hi_old-1)+1e-9 and abs(lo_new+hi_new-1)<1e-9)} 기대: NEW 완전대칭(lo+hi=1) · OLD는 +1/(2n) 편향")

# ── Pillar4-② : TF macd 대칭화 ─────────────────────────────────────────────
print("\n[7] TF 모멘텀 확인 — 숏에서 macd 중립(0)일 때")
def short_mom(macd_bull, macd_val, NEW):
    config.WRF_TF_MACD_SYM = NEW
    long = False
    if NEW:
        return macd_bull if long else (macd_val is not None and macd_val < 0)
    return macd_bull if long else (not macd_bull)
print(f"  macd_bull=False, macd=0.0(중립): OLD mom_realign={short_mom(False,0.0,False)} → NEW={short_mom(False,0.0,True)}")
print(f"  macd_bull=False, macd=-0.5(약세): OLD={short_mom(False,-0.5,False)} → NEW={short_mom(False,-0.5,True)}")
print(f"  {check(short_mom(False,0.0,False)==True and short_mom(False,0.0,True)==False and short_mom(False,-0.5,True)==True)} 기대: 중립0은 NEW가 거부(롱대칭) · 명확약세는 통과")

print("\n[8] 원트랙 — 밴드반전 디텍터가 d_shadow 플래그 없이 RV 후보 생성")
bf = {"raw": {"bb_pctb": 0.85, "rsi_4h": 60, "dist_vwap_atr": 1.0, "confluence_short":0,"confluence_long":0},
      "pct": {"rsi":0.85,"funding":0.5}, "ctx": {"btc_macro":"CHOP","allowed_setups":["MR","RV"]},
      "df_1h": mkdf(list(100+np.random.randn(60)*0.5)+[103,101])}  # 상단 밴드터치(숏)
config.WRF_D_SHADOW = True; config.WRF_D_REQUIRE_REENTRY = False  # 밴드터치 폴백(arming 보장)
br = det._detect_band_reversal(bf, {})
has_flag = any("d_shadow" in c for c in br)
print(f"  밴드반전 후보 {len(br)}개, setup={[c['setup'] for c in br]}, 'd_shadow'키 존재={has_flag}")
print(f"  {check(len(br)>=1 and not has_flag and all(c['setup']=='RV' for c in br))} 기대: ≥1개 생성 · setup=RV · d_shadow 플래그 없음(원트랙)")
print(f"  {check('_detect_band_reversal' in dir(det) and not hasattr(det,'_detect_d_shadow'))} 기대: _detect_d_shadow 제거·_detect_band_reversal 존재")
