"""
analysis_engine.py — 분석 엔진 (1h Bot v3.0)
────────────────────────────────────────────────────────────────────
[v3.0 신규 분석 함수 9개]

① analyze_smart_money_divergence(top_trader_ls, retail_ls)
   고래 vs 개인 LS 괴리 → 스마트머니 방향 포착

② analyze_oi_matrix(oi_data, price_change_4h)
   OI변화 × 가격변화 4분면 → 추세 성격 분류

③ analyze_funding_history(funding_hist)
   64h 펀딩비 추세·전환·누적 극단 분석

④ analyze_candle_pattern_1d(df_1d)
   일봉 캔들 패턴 (가중치 2배)

⑤ analyze_candle_pattern_4h(df_4h)
   4h 캔들 패턴 (가중치 1.4배)

⑥ analyze_mtf_momentum(df_1h, df_4h, df_1d)
   RSI 기울기 기반 3TF 모멘텀 정합

⑧ detect_weekly_levels(df_1d, current_price)
   전주 고/저가 + 전일 키레벨 S/R

⑨ analyze_1d_ema_structure(df_1d, current_price)
   1d EMA20/50/200 구조 + 이격 분석
────────────────────────────────────────────────────────────────────
"""
import logging
from typing import Optional
import numpy as np
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import config

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# 1. 기본 유틸
# ══════════════════════════════════════════════════════════════════

def calculate_atr(df, period=None):
    if df is None or df.empty or "high" not in df.columns:
        return pd.Series(dtype=float)
    period = period or config.ATR_PERIOD
    high, low, close = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([high-low,(high-prev_close).abs(),(low-prev_close).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1.0/period, adjust=False).mean()

def get_atr_state(df):
    if df is None or len(df) < config.ATR_PERIOD + 5:
        return {"current":0.0,"pct":0.0,"expanding":False,"ratio":1.0}
    atr = calculate_atr(df)
    cur = float(atr.iloc[-1]); avg = float(atr.iloc[-20:].mean()) if len(atr)>=20 else float(atr.mean())
    price = float(df["close"].iloc[-1]); ratio = cur/avg if avg>0 else 1.0
    return {"current":round(cur,6),"pct":round(cur/price*100,4),"expanding":bool(ratio>1.3),"ratio":round(ratio,3)}

def _calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def check_volume_confirmation(df_1h, df_4h=None):
    _empty = {"confirmed":False,"strong":False,"ratio":0.0,"score":50.0,"current_vol":0.0,"avg_vol":0.0,"baseline_method":"none"}
    n = config.VOLUME_4H_BASELINE_CANDLES; req = n + 2
    if df_4h is not None and len(df_4h) >= req:
        avg_4h = float(df_4h["volume"].iloc[-(n+2):-2].mean()); baseline = avg_4h / 4
        if df_1h is None or len(df_1h) < 3: return _empty
        cur_vol = float(df_1h["volume"].iloc[-2]); method = f"4h_{n*4}h"
    else:
        lb = config.VOLUME_CONFIRM_LOOKBACK
        if df_1h is None or len(df_1h) < lb + 3: return _empty
        cur_vol = float(df_1h["volume"].iloc[-2]); baseline = float(df_1h["volume"].iloc[-(lb+2):-2].mean()); method = "1h_fallback"
    if baseline <= 0: return _empty
    ratio = cur_vol / baseline
    confirmed = ratio >= config.VOLUME_SPIKE_MULTIPLIER; strong = ratio >= config.VOLUME_STRONG_MULTIPLIER
    if   ratio <= 0:   score = 0.0
    elif ratio <= 0.5: score = (ratio/0.5)*25.0
    elif ratio <= 1.0: score = 25.0+((ratio-0.5)/0.5)*25.0
    elif ratio <= 1.5: score = 50.0+((ratio-1.0)/0.5)*20.0
    elif ratio <= 2.5: score = 70.0+((ratio-1.5)/1.0)*20.0
    else:              score = min(100.0, 90.0+(ratio-2.5)*4.0)
    return {"confirmed":confirmed,"strong":strong,"ratio":round(ratio,3),"score":round(min(100.0,max(0.0,score)),2),
            "current_vol":round(cur_vol,2),"avg_vol":round(baseline,2),"baseline_method":method}


# ══════════════════════════════════════════════════════════════════
# 2. RSI (멀티TF)
# ══════════════════════════════════════════════════════════════════

def calculate_rsi(df, period=None):
    period = period or config.RSI_PERIOD
    close = df["close"].astype(float); delta = close.diff()
    gain, loss = delta.clip(lower=0), (-delta).clip(lower=0)
    alpha = 1.0/period
    ag = gain.ewm(alpha=alpha,adjust=False).mean(); al = loss.ewm(alpha=alpha,adjust=False).mean()
    return (100 - (100/(1+ag/al.replace(0,np.nan)))).fillna(50)

def _rsi_to_score(v):
    if v<=20: ls=95
    elif v<=30: ls=85-(v-20)/10*10
    elif v<=50: ls=75-(v-30)/20*25
    elif v<=70: ls=50-(v-50)/20*30
    else: ls=max(5,20-(v-70)*1.5)
    return round(min(100,max(0,ls)),2), round(min(100,max(0,100-ls)),2)

def _detect_bull_div(df, rsi, lb=6):
    if df is None or len(df)<lb*2: return False
    c=df["close"].values; r=rsi.values
    return bool(c[-lb:].min()<c[-lb*2:-lb].min() and r[-lb:].min()>r[-lb*2:-lb].min())

def _detect_bear_div(df, rsi, lb=6):
    if df is None or len(df)<lb*2: return False
    c=df["close"].values; r=rsi.values
    return bool(c[-lb:].max()>c[-lb*2:-lb].max() and r[-lb:].max()<r[-lb*2:-lb].max())

def _detect_hidden_bull_div(df, rsi, lb=8):
    if df is None or len(df)<lb*2: return False
    c=df["close"].values; r=rsi.values
    return bool(c[-lb:].min()>c[-lb*2:-lb].min() and r[-lb:].min()<r[-lb*2:-lb].min())

def _detect_hidden_bear_div(df, rsi, lb=8):
    if df is None or len(df)<lb*2: return False
    c=df["close"].values; r=rsi.values
    return bool(c[-lb:].max()<c[-lb*2:-lb].max() and r[-lb:].max()>r[-lb*2:-lb].max())

def analyze_mtf_rsi(df_1h, df_4h, df_1d):
    def _get(df):
        if df is None or len(df)<config.RSI_PERIOD+1: return None
        return float(calculate_rsi(df).iloc[-1])
    v_1h=_get(df_1h); v_4h=_get(df_4h); v_1d=_get(df_1d)
    weights=[(v_1h,0.50),(v_4h,0.30),(v_1d,0.20)]
    available=[(v,w) for v,w in weights if v is not None]
    if not available: return _empty_rsi()
    total_w=sum(w for _,w in available); v_weighted=sum(v*w for v,w in available)/total_w
    v_entry=v_1h if v_1h is not None else v_weighted
    state=("oversold" if v_entry<=config.RSI_OVERSOLD else "overbought" if v_entry>=config.RSI_OVERBOUGHT else "neutral")
    long_score_raw,short_score_raw=_rsi_to_score(v_weighted)
    pls=(v_4h is not None and v_4h>58 and v_1h is not None and v_1h<40)
    plw=(v_4h is not None and v_4h>52 and v_1h is not None and v_1h<44 and not pls)
    plm=(v_4h is not None and v_4h>48 and v_1h is not None and v_1h<42 and not pls and not plw)
    pl=pls or plw or plm
    pss=(v_4h is not None and v_4h<42 and v_1h is not None and v_1h>60)
    psw=(v_4h is not None and v_4h<48 and v_1h is not None and v_1h>56 and not pss)
    psm=(v_4h is not None and v_4h<52 and v_1h is not None and v_1h>58 and not pss and not psw)
    ps=pss or psw or psm
    macro_bull=v_1d is not None and v_1d>52; macro_bear=v_1d is not None and v_1d<48
    pla=(14 if pls else 9 if plw else 5 if plm else 0); psa=(14 if pss else 9 if psw else 5 if psm else 0)
    if pl: long_score_raw=min(100,long_score_raw+pla); short_score_raw=max(0,short_score_raw-pla)
    if ps: short_score_raw=min(100,short_score_raw+psa); long_score_raw=max(0,long_score_raw-psa)
    if macro_bull and long_score_raw>50: long_score_raw=min(100,long_score_raw+5)
    if macro_bear and short_score_raw>50: short_score_raw=min(100,short_score_raw+5)
    long_score=round(min(100,max(0,long_score_raw)),2); short_score=round(min(100,max(0,short_score_raw)),2)
    rsi_1h_s=calculate_rsi(df_1h) if df_1h is not None and len(df_1h)>=12 else None
    bull_div=bool(_detect_bull_div(df_1h,rsi_1h_s)) if rsi_1h_s is not None else False
    bear_div=bool(_detect_bear_div(df_1h,rsi_1h_s)) if rsi_1h_s is not None else False
    hbd=bool(_detect_hidden_bull_div(df_1h,rsi_1h_s)) if rsi_1h_s is not None and len(df_1h)>=16 else False
    hsd=bool(_detect_hidden_bear_div(df_1h,rsi_1h_s)) if rsi_1h_s is not None and len(df_1h)>=16 else False
    v1hs=f"{v_1h:.1f}" if v_1h else "N/A"; v4hs=f"{v_4h:.1f}" if v_4h else "N/A"; v1ds=f"{v_1d:.1f}" if v_1d else "N/A"
    pb_tag=((" ★눌림목롱(강)" if pls else " ★눌림목롱(약)" if plw else " ★눌림목롱(미)" if plm else "")+
            (" ★눌림목숏(강)" if pss else " ★눌림목숏(약)" if psw else " ★눌림목숏(미)" if psm else ""))
    div_tag=((" 📊히든롱" if hbd else "")+(" 📊히든숏" if hsd else ""))
    logger.info(f"[MTF-RSI] 1h:{v1hs} 4h:{v4hs} 1d:{v1ds} 가중:{v_weighted:.1f} [{state}] 롱:{long_score:.1f} 숏:{short_score:.1f}"+pb_tag+div_tag)
    return {"value":round(v_entry,2),"value_1h":round(v_4h,2) if v_4h else None,
            "value_4h":round(v_1d,2) if v_1d else None,"value_weighted":round(v_weighted,2),
            "state":state,"long_score":long_score,"short_score":short_score,
            "bullish_divergence":bull_div,"bearish_divergence":bear_div,"hidden_bull_div":hbd,"hidden_bear_div":hsd,
            "pullback_long":pl,"pullback_short":ps,"pullback_long_strong":pls,"pullback_long_weak":plw,"pullback_long_micro":plm,
            "pullback_short_strong":pss,"pullback_short_weak":psw,"pullback_short_micro":psm}

def _empty_rsi():
    return {"value":50.0,"value_1h":None,"value_4h":None,"value_weighted":50.0,"state":"neutral",
            "long_score":50.0,"short_score":50.0,"bullish_divergence":False,"bearish_divergence":False,
            "hidden_bull_div":False,"hidden_bear_div":False,"pullback_long":False,"pullback_short":False,
            "pullback_long_strong":False,"pullback_long_weak":False,"pullback_long_micro":False,
            "pullback_short_strong":False,"pullback_short_weak":False,"pullback_short_micro":False}


# ══════════════════════════════════════════════════════════════════
# 3. 볼린저밴드
# ══════════════════════════════════════════════════════════════════

def analyze_bollinger_bands(df):
    period=config.BOLLINGER_PERIOD; std_dev=config.BOLLINGER_STD
    if df is None or len(df)<period+1: return _empty_bb()
    close=df["close"].astype(float); mid=close.rolling(period).mean(); std=close.rolling(period).std()
    upper=mid+std_dev*std; lower=mid-std_dev*std
    bw_s=(upper-lower)/mid.replace(0,np.nan)
    cur_bw=float(bw_s.iloc[-1]) if not pd.isna(bw_s.iloc[-1]) else 0.0
    avg_bw=(float(bw_s.iloc[-50:].mean()) if len(bw_s)>=50 else float(bw_s.iloc[-20:].mean()) if len(bw_s)>=20 else cur_bw)
    squeeze=bool(cur_bw<avg_bw*config.REGIME_SQUEEZE_RATIO and avg_bw>0)
    c_close=float(close.iloc[-1]); c_upper=float(upper.iloc[-1]); c_lower=float(lower.iloc[-1]); c_mid=float(mid.iloc[-1])
    band_range=c_upper-c_lower
    if band_range<=0: return _empty_bb()
    pct_b=(c_close-c_lower)/band_range
    if   pct_b<=0.0:  ls,ss,state=92,8,"lower_breakout"
    elif pct_b<=0.15: ls,ss,state=82,18,"near_lower"
    elif pct_b<=0.35: ls,ss,state=65,35,"lower_zone"
    elif pct_b<=0.65: ls,ss,state=50,50,"middle"
    elif pct_b<=0.85: ls,ss,state=35,65,"upper_zone"
    elif pct_b<=1.0:  ls,ss,state=18,82,"near_upper"
    else:             ls,ss,state=8,92,"upper_breakout"
    pctb_s=(close-lower)/(upper-lower).replace(0,np.nan).fillna(0.5)
    lower_streak=upper_streak=0
    for pb in reversed(pctb_s.iloc[-10:].values):
        if pb<0.0: lower_streak+=1
        else: break
    for pb in reversed(pctb_s.iloc[-10:].values):
        if pb>1.0: upper_streak+=1
        else: break
    return {"long_score":ls,"short_score":ss,"pct_b":round(pct_b,4),"squeeze":squeeze,
            "state":state,"upper":round(c_upper,6),"lower":round(c_lower,6),"mid":round(c_mid,6),
            "band_width":round(cur_bw,6),"avg_band_width":round(avg_bw,6),
            "lower_streak":lower_streak,"upper_streak":upper_streak,"available":True}

def _empty_bb():
    return {"long_score":50,"short_score":50,"pct_b":0.5,"squeeze":False,"state":"unknown",
            "upper":0,"lower":0,"mid":0,"band_width":0,"avg_band_width":0,"lower_streak":0,"upper_streak":0,"available":False}


# ══════════════════════════════════════════════════════════════════
# 4. EMA
# ══════════════════════════════════════════════════════════════════

def _ema_direction(df):
    if df is None or len(df)<config.EMA_SLOW+1: return "neutral"
    close=df["close"].astype(float)
    ef=float(_calc_ema(close,config.EMA_FAST).iloc[-1]); es=float(_calc_ema(close,config.EMA_SLOW).iloc[-1])
    gap=abs(ef-es)/es if es>0 else 0
    if gap<0.0005: return "neutral"
    return "bullish" if ef>es else "bearish"

def calculate_ema_multiplier(ohlcv_dict, direction, regime="UNKNOWN"):
    tf_signals={"1h":_ema_direction(ohlcv_dict.get("1h")),"4h":_ema_direction(ohlcv_dict.get("4h")),"1d":_ema_direction(ohlcv_dict.get("1d"))}
    opposite="bearish" if direction=="long" else "bullish"
    reverse_count=sum(1 for s in tf_signals.values() if s==opposite)
    same_count=sum(1 for s in tf_signals.values() if s==("bullish" if direction=="long" else "bearish"))
    mult=config.REGIME_EMA_MULTIPLIERS.get(regime,config.EMA_MULTIPLIER).get(reverse_count,1.0)
    ema_dir="bullish" if same_count==3 and direction=="long" else "bearish" if same_count==3 and direction=="short" else "mixed"
    logger.info(f"[EMA배율/{direction.upper()}] {tf_signals} → ×{mult:.2f} [{regime}]")
    return {"tf_signals":tf_signals,"same_count":same_count,"reverse_count":reverse_count,"multiplier":mult,"direction":ema_dir,"regime":regime,
            "reason":f"EMA {same_count}/3 일치 (역:{reverse_count}개 → ×{mult:.2f}) [{regime}]"}


# ══════════════════════════════════════════════════════════════════
# 5. ADX
# ══════════════════════════════════════════════════════════════════

def calculate_adx(df, period=None):
    period=period or config.ADX_PERIOD
    _n={"adx":0.0,"plus_di":0.0,"minus_di":0.0,"trend_dir":"neutral","strength":"none","multiplier":1.0,"available":False}
    if df is None or len(df)<period*2+1: return _n
    high=df["high"].astype(float); low=df["low"].astype(float); close=df["close"].astype(float)
    prev_close=close.shift(1)
    tr=pd.concat([high-low,(high-prev_close).abs(),(low-prev_close).abs()],axis=1).max(axis=1)
    up=high-high.shift(1); dn=low.shift(1)-low
    pdm=up.where((up>dn)&(up>0),0.0); mdm=dn.where((dn>up)&(dn>0),0.0)
    a=1.0/period
    atr_e=tr.ewm(alpha=a,adjust=False).mean(); pe=pdm.ewm(alpha=a,adjust=False).mean(); me=mdm.ewm(alpha=a,adjust=False).mean()
    pdi=100*pe/atr_e.replace(0,np.nan); mdi=100*me/atr_e.replace(0,np.nan)
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan); adx=dx.ewm(alpha=a,adjust=False).mean()
    c_adx=round(float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0.0,2)
    c_pdi=round(float(pdi.iloc[-1]) if not pd.isna(pdi.iloc[-1]) else 0.0,2)
    c_mdi=round(float(mdi.iloc[-1]) if not pd.isna(mdi.iloc[-1]) else 0.0,2)
    if c_adx<config.ADX_NO_TREND: st,m="none",0.70
    elif c_adx<config.ADX_WEAK_TREND: st,m="weak",0.85
    elif c_adx<config.ADX_STRONG: st,m="normal",1.00
    else: st,m="strong",1.00
    td="bullish" if c_pdi>c_mdi else ("bearish" if c_mdi>c_pdi else "neutral")
    return {"adx":c_adx,"plus_di":c_pdi,"minus_di":c_mdi,"trend_dir":td,"strength":st,"multiplier":m,"available":True}


# ══════════════════════════════════════════════════════════════════
# 6. 펀딩비 / LS / Taker / 청산
# ══════════════════════════════════════════════════════════════════

def analyze_funding_rate(funding_data):
    if funding_data is None:
        return {"rate":0.0,"rate_pct":0.0,"long_score":50.0,"short_score":50.0,"bias":"neutral","strength":"neutral","available":False}
    rate=float(funding_data.get("rate",0.0))
    if rate<=config.FUNDING_LONG_STRONG:
        ls=90+min(10,abs(rate-config.FUNDING_LONG_STRONG)/abs(config.FUNDING_LONG_STRONG)*10); ss=10; bias,st="long_favorable","strong"
    elif rate<=config.FUNDING_LONG_MILD:
        r=(rate-config.FUNDING_LONG_MILD)/(config.FUNDING_LONG_STRONG-config.FUNDING_LONG_MILD)
        ls=65+r*25; ss=35-r*25; bias,st="long_favorable","mild"
    elif rate>=config.FUNDING_SHORT_STRONG:
        ss=90+min(10,(rate-config.FUNDING_SHORT_STRONG)/config.FUNDING_SHORT_STRONG*10); ls=10; bias,st="short_favorable","strong"
    elif rate>=config.FUNDING_SHORT_MILD:
        r=(rate-config.FUNDING_SHORT_MILD)/(config.FUNDING_SHORT_STRONG-config.FUNDING_SHORT_MILD)
        ss=65+r*25; ls=35-r*25; bias,st="short_favorable","mild"
    else:
        t=rate/config.FUNDING_LONG_MILD if rate<0 else rate/config.FUNDING_SHORT_MILD
        ls=50-t*15; ss=50+t*15; bias,st="neutral","neutral"
    ls=round(min(100,max(0,ls)),2); ss=round(min(100,max(0,ss)),2)
    logger.info(f"[FundingRate] {rate*100:+.4f}% [{bias}] 롱:{ls:.1f} 숏:{ss:.1f}")
    return {"rate":rate,"rate_pct":round(rate*100,6),"long_score":ls,"short_score":ss,"bias":bias,"strength":st,"available":True}

def analyze_long_short_ratio(ls_data, regime_name="RANGING"):
    if not ls_data or not ls_data.get("available"):
        return {"long_score":50,"short_score":50,"bias":"neutral","long_pct":0.5,"short_pct":0.5,"available":False}
    lp=ls_data.get("long_pct",0.5); sp=ls_data.get("short_pct",0.5)
    if regime_name=="TRENDING":
        if lp>=0.60: ls,ss,bias=80,20,"long_momentum"
        elif lp>=0.52: ls,ss,bias=62,38,"long_lean"
        elif sp>=0.60: ls,ss,bias=20,80,"short_momentum"
        elif sp>=0.52: ls,ss,bias=38,62,"short_lean"
        else: ls,ss,bias=50,50,"neutral"
    else:
        if lp>=config.LS_LONG_EXTREME: ls,ss,bias=10,90,"short_extreme"
        elif lp>=config.LS_LONG_HIGH:
            r=(lp-config.LS_LONG_HIGH)/(config.LS_LONG_EXTREME-config.LS_LONG_HIGH); ss=70+r*20; ls=100-ss; bias="short_favorable"
        elif sp>=config.LS_SHORT_EXTREME: ls,ss,bias=90,10,"long_extreme"
        elif sp>=config.LS_SHORT_HIGH:
            r=(sp-config.LS_SHORT_HIGH)/(config.LS_SHORT_EXTREME-config.LS_SHORT_HIGH); ls=70+r*20; ss=100-ls; bias="long_favorable"
        else:
            t=(lp-0.5)*2; ss=50+t*10; ls=100-ss; bias="neutral"
    ls=round(min(100,max(0,ls)),2); ss=round(min(100,max(0,ss)),2)
    logger.info(f"[LS비율] 롱:{lp*100:.1f}% [{bias}/{regime_name}] 롱pt:{ls} 숏pt:{ss}")
    return {"long_score":ls,"short_score":ss,"bias":bias,"long_pct":lp,"short_pct":sp,"available":True}

def analyze_taker_volume(taker_data):
    if not taker_data or not taker_data.get("available"):
        return {"long_score":50.0,"short_score":50.0,"bias":"neutral","strength":"neutral","available":False}
    br=taker_data.get("buy_ratio",0.5); sr=taker_data.get("sell_ratio",0.5)
    bias=taker_data.get("bias","neutral"); strength=taker_data.get("strength","neutral")
    if br>=config.TAKER_STRONG_BUY: ls=85+(br-config.TAKER_STRONG_BUY)/(1-config.TAKER_STRONG_BUY)*10; ss=15
    elif br>=0.55: ls=65+(br-0.55)/(config.TAKER_STRONG_BUY-0.55)*20; ss=100-ls
    elif sr>=config.TAKER_STRONG_SELL: ss=85+(sr-config.TAKER_STRONG_SELL)/(1-config.TAKER_STRONG_SELL)*10; ls=15
    elif sr>=0.55: ss=65+(sr-0.55)/(config.TAKER_STRONG_SELL-0.55)*20; ls=100-ss
    else: ls=50+(br-0.5)*80; ss=100-ls
    ls=round(min(100,max(0,ls)),2); ss=round(min(100,max(0,ss)),2)
    logger.info(f"[Taker] 매수:{br*100:.1f}% [{bias}/{strength}] 롱:{ls:.1f} 숏:{ss:.1f}")
    return {"long_score":ls,"short_score":ss,"bias":bias,"strength":strength,"buy_ratio":br,"sell_ratio":sr,"available":True}

def analyze_liquidations(liq_data, df_1h=None):
    _empty={"long_score":50,"short_score":50,"signal":"none","is_large":False,
            "long_liq_proxy":0.0,"short_liq_proxy":0.0,"favorable_direction":None,"display_hint":None,"available":False}
    if df_1h is None or len(df_1h)<15: return _empty
    close=df_1h["close"].astype(float); high=df_1h["high"].astype(float)
    low=df_1h["low"].astype(float); open_=df_1h["open"].astype(float); volume=df_1h["volume"].astype(float)
    avg_vol=float(volume.iloc[-21:-1].mean()) if len(df_1h)>=21 else float(volume.iloc[:-1].mean())
    if avg_vol<=0: return _empty
    lls=sls=0.0
    for i in range(-5,0):
        c=float(close.iloc[i]); h=float(high.iloc[i]); l=float(low.iloc[i]); o=float(open_.iloc[i]); v=float(volume.iloc[i])
        cr=h-l
        if cr<1e-9: continue
        bt=max(o,c); bb_=min(o,c); lw=bb_-l; uw=h-bt
        vr=v/avg_vol
        if lw/cr>0.35 and vr>1.5: lls=max(lls,min(1.0,(lw/cr)*vr/2.0))
        if uw/cr>0.35 and vr>1.5: sls=max(sls,min(1.0,(uw/cr)*vr/2.0))
    price_chg=0.0
    if len(df_1h)>=7:
        p0=float(close.iloc[-7]); p1=float(close.iloc[-1])
        price_chg=abs(p1-p0)/p0 if p0>0 else 0.0
    is_large=price_chg>0.02 and (lls>0.25 or sls>0.25)
    signal="none"
    if lls>sls and lls>0.15: signal="long_liq_detected"
    elif sls>lls and sls>0.15: signal="short_liq_detected"
    ls,ss=50,50
    if signal=="long_liq_detected":
        ls=round(60+lls*30,2); ss=round(40-lls*10,2)
        if is_large: ls=min(100,ls+10)
    elif signal=="short_liq_detected":
        ss=round(60+sls*30,2); ls=round(40-sls*10,2)
        if is_large: ss=min(100,ss+10)
    _map={"long_liq_detected":("long","롱청산 감지 → 반등 기대"),"short_liq_detected":("short","숏청산 감지 → 되돌림 기대")}
    fav,hint=_map.get(signal,(None,None))
    return {"long_score":round(min(100,max(0,ls)),2),"short_score":round(min(100,max(0,ss)),2),
            "signal":signal,"is_large":is_large,"long_liq_proxy":round(lls,4),"short_liq_proxy":round(sls,4),
            "favorable_direction":fav,"display_hint":hint,"available":True}

def classify_market_regime(df_1h, adx, bb):
    if df_1h is None or len(df_1h)<25 or not bb.get("available"):
        return {"regime":"UNKNOWN","threshold":64,"description":"데이터 부족","icon":"❓"}
    adx_val=adx.get("adx",0.0); bw=bb.get("band_width",0.0); avg_bw=bb.get("avg_band_width",bw)
    squeeze=bb.get("squeeze",False); bw_ratio=bw/avg_bw if avg_bw>0 else 1.0
    ma20_cross=0; er=1.0
    try:
        close=df_1h["close"].astype(float); ma20=close.rolling(20).mean()
        lb=min(40,len(close)-1)
        sc=close.iloc[-lb-1:].values; sm=ma20.iloc[-lb-1:].values
        for i in range(1,len(sc)):
            if pd.isna(sm[i]) or pd.isna(sm[i-1]): continue
            if (sc[i-1]>sm[i-1])!=(sc[i]>sm[i]): ma20_cross+=1
        seg=close.iloc[-lb:].values
        nc=abs(float(seg[-1])-float(seg[0])); tc=sum(abs(seg[i]-seg[i-1]) for i in range(1,len(seg)))
        er=round(nc/tc,4) if tc>0 else 1.0
    except: pass
    is_ranging=((ma20_cross>=2 and er<0.35) or er<0.15)
    if squeeze and adx_val<config.REGIME_TREND_ADX: regime,desc,icon="SQUEEZE",f"BB스퀴즈+ADX낮음({adx_val:.0f})","🔄"
    elif adx_val>=config.REGIME_STRONG_ADX and bw_ratio>=1.2: regime,desc,icon="EXPLOSIVE",f"ADX강({adx_val:.0f})+BB확장({bw_ratio:.1f}x)","💥"
    elif is_ranging: regime,desc,icon="RANGING",f"MA20교차{ma20_cross}회+ER:{er:.2f}(ADX:{adx_val:.0f})","↔️"
    elif adx_val>=config.REGIME_TREND_ADX: regime,desc,icon="TRENDING",f"ADX추세({adx_val:.0f})","📈"
    else: regime,desc,icon="RANGING",f"ADX낮음({adx_val:.0f})+BB평행","↔️"
    thr=config.REGIME_THRESHOLDS.get(regime,64)
    logger.info(f"[국면] {icon} {regime} — {desc} (임계:{thr}pt)")
    return {"regime":regime,"threshold":thr,"description":desc,"icon":icon,
            "adx":adx_val,"bw_ratio":round(bw_ratio,3),"squeeze":squeeze,"ma20_cross_count":ma20_cross,"efficiency_ratio":er}

def evaluate_gates(direction, funding, ls_ratio_result):
    fb=funding.get("bias","neutral"); lb_=ls_ratio_result.get("bias","neutral")
    pf=1.0; pr=None
    if direction=="long": fr_bad=(fb=="short_favorable"); ls_bad=(lb_ in ("short_favorable","short_extreme"))
    else: fr_bad=(fb=="long_favorable"); ls_bad=(lb_ in ("long_favorable","long_extreme"))
    if fr_bad and ls_bad: pf=config.GATE_PENALTY_DUAL; pr=f"펀딩비·롱숏 모두 {direction} 불리 ×{pf}"; logger.info(f"[Gate] ⚠️ {direction.upper()} 복합 패널티")
    elif fr_bad: pf=config.GATE_PENALTY_SINGLE; pr=f"펀딩비 불리 ×{pf}"
    elif ls_bad: pf=config.GATE_PENALTY_SINGLE; pr=f"롱숏비율 불리 ×{pf}"
    else: logger.info(f"[Gate] ✅ {direction.upper()} 통과")
    return {"passed":True,"funding_penalty":pf,"block_reason":None,"penalty_reason":pr}


# ══════════════════════════════════════════════════════════════════
# 7. SMC (FVG, BOS, Fibonacci)
# ══════════════════════════════════════════════════════════════════

def detect_fvg(df, lookback=30):
    _empty={"in_bullish_fvg":False,"in_bearish_fvg":False,"bullish_fvg_count":0,"bearish_fvg_count":0,"nearest_bullish_fvg":None,"nearest_bearish_fvg":None}
    if df is None or len(df)<5: return _empty
    try:
        lb=min(lookback,len(df)); high=df["high"].astype(float).values[-lb:]
        low=df["low"].astype(float).values[-lb:]; close=df["close"].astype(float).values[-lb:]
        current=close[-1]; bf=[]; bf2=[]
        for i in range(2,lb-2):
            if high[i-2]<low[i]: bf.append((high[i-2],low[i]))
            if low[i-2]>high[i]: bf2.append((high[i],low[i-2]))
        ab=[(b,t) for b,t in bf if current>=b*0.99]; ab2=[(b,t) for b,t in bf2 if current<=t*1.01]
        ibf=any(b<=current<=t for b,t in ab); ibf2=any(b<=current<=t for b,t in ab2)
        nb=(min(ab,key=lambda x:abs((x[0]+x[1])/2-current)) if ab else None)
        nb2=(min(ab2,key=lambda x:abs((x[0]+x[1])/2-current)) if ab2 else None)
        if ibf: logger.info("[FVG] ★ 강세 FVG 내부")
        if ibf2: logger.info("[FVG] ★ 약세 FVG 내부")
        return {"in_bullish_fvg":ibf,"in_bearish_fvg":ibf2,"bullish_fvg_count":len(ab),"bearish_fvg_count":len(ab2),
                "nearest_bullish_fvg":(round(nb[0],4),round(nb[1],4)) if nb else None,
                "nearest_bearish_fvg":(round(nb2[0],4),round(nb2[1],4)) if nb2 else None}
    except Exception as e:
        logger.warning(f"[FVG] 오류: {e}"); return _empty

def detect_bos_choch(df, lookback=60, n=3):
    _empty={"bos_bullish":False,"bos_bearish":False,"choch_bullish":False,"choch_bearish":False,"last_swing_high":None,"last_swing_low":None}
    if df is None or len(df)<max(20,n*4): return _empty
    try:
        lb=min(lookback,len(df)-1); highs=df["high"].astype(float).values[-lb:]
        lows=df["low"].astype(float).values[-lb:]; closes=df["close"].astype(float).values[-lb:]
        sh=[]; sl=[]
        for i in range(n,lb-n-1):
            wh=highs[max(0,i-n):i+n+1]; wl=lows[max(0,i-n):i+n+1]
            if len(wh)==2*n+1:
                if highs[i]==max(wh): sh.append((i,highs[i]))
                if lows[i]==min(wl):  sl.append((i,lows[i]))
        cc=closes[-1]; bb=bb2=cu=cd=False
        lsh=sh[-1][1] if sh else None; lsl=sl[-1][1] if sl else None
        if lsh and cc>lsh: bb=True
        if lsl and cc<lsl: bb2=True
        if not bb2 and len(sh)>=2 and sl:
            s1,s2=sh[-2],sh[-1]
            if s2[1]>s1[1]:
                il=[x for x in sl if s1[0]<x[0]<s2[0]]
                if il and cc<min(x[1] for x in il): cd=True
        if not bb and len(sl)>=2 and sh:
            sl1,sl2=sl[-2],sl[-1]
            if sl2[1]<sl1[1]:
                ih=[x for x in sh if sl1[0]<x[0]<sl2[0]]
                if ih and cc>max(x[1] for x in ih): cu=True
        if bb:  logger.info(f"[BOS/{lookback}c] ★ 상승 BOS")
        if bb2: logger.info(f"[BOS/{lookback}c] ★ 하락 BOS")
        if cu:  logger.info(f"[CHoCH/{lookback}c] ⚠️ 상승전환")
        if cd:  logger.info(f"[CHoCH/{lookback}c] ⚠️ 하락전환")
        return {"bos_bullish":bb,"bos_bearish":bb2,"choch_bullish":cu,"choch_bearish":cd,
                "last_swing_high":round(lsh,4) if lsh else None,"last_swing_low":round(lsl,4) if lsl else None}
    except Exception as e:
        logger.warning(f"[BOS/CHoCH] 오류: {e}"); return _empty

def check_fibonacci_levels(df):
    _empty={"in_golden_pocket_long":False,"near_key_level_long":False,"long_retracement":None,
            "in_golden_pocket_short":False,"near_key_level_short":False,"short_retracement":None,"swing_high":None,"swing_low":None}
    if df is None or len(df)<config.FIB_LOOKBACK//2: return _empty
    try:
        lb=min(config.FIB_LOOKBACK,len(df)); closes=df["close"].astype(float).values[-lb:]
        highs=df["high"].astype(float).values[-lb:]; lows=df["low"].astype(float).values[-lb:]
        cur=closes[-1]; end=lb-5
        shi=int(np.argmax(highs[:end])); sli=int(np.argmin(lows[:end]))
        sh=highs[shi]; sl=lows[sli]
        slfl=min(lows[:shi+1]) if shi>0 else sl; shfs=max(highs[:sli+1]) if sli>0 else sh
        lr_range=sh-slfl; sr_range=shfs-sl
        lr=sr=None
        if lr_range/sh>=config.FIB_MIN_SWING_PCT and cur<sh: lr=(sh-cur)/lr_range
        if sr_range/shfs>=config.FIB_MIN_SWING_PCT and cur>sl: sr=(cur-sl)/sr_range
        TOL=config.FIB_TOLERANCE
        gpl=lr is not None and 0.618<=lr<=0.650; gps=sr is not None and 0.618<=sr<=0.650
        nl=lr is not None and any(abs(lr-l)<=TOL for l in [0.382,0.500,0.786]) and not gpl
        ns=sr is not None and any(abs(sr-l)<=TOL for l in [0.382,0.500,0.786]) and not gps
        if gpl: logger.info(f"[피보] ★ 롱 황금포켓 {lr*100:.1f}%")
        if gps: logger.info(f"[피보] ★ 숏 황금포켓 {sr*100:.1f}%")
        return {"in_golden_pocket_long":gpl,"near_key_level_long":nl,"long_retracement":round(lr*100,1) if lr else None,
                "in_golden_pocket_short":gps,"near_key_level_short":ns,"short_retracement":round(sr*100,1) if sr else None,
                "swing_high":round(sh,4),"swing_low":round(sl,4)}
    except Exception as e:
        logger.warning(f"[피보] 오류: {e}"); return _empty


# ══════════════════════════════════════════════════════════════════
# 8. 캔들 패턴 (TF별)
# ══════════════════════════════════════════════════════════════════

def analyze_candle_pattern(df, tf_label="1h"):
    """tf_label: "1h" | "4h" | "1d" — 로그 구분용"""
    _empty={"long_score":50,"short_score":50,"patterns":[],"bearish_pin":False,"bullish_pin":False,
            "bearish_engulf":False,"bullish_engulf":False,"consecutive_bear":False,"consecutive_bull":False}
    if df is None or len(df)<4: return _empty
    try:
        c=df["close"].astype(float).values; o=df["open"].astype(float).values
        h=df["high"].astype(float).values; l=df["low"].astype(float).values
        body=np.abs(c-o); upper=h-np.maximum(c,o); lower=np.minimum(c,o)-l; rng=h-l
        min_rng=float(np.mean(rng[-20:]))*0.3; cr=rng[-1]
        bp  =(cr>min_rng and upper[-1]>body[-1]*2.0 and lower[-1]<upper[-1]*0.3 and c[-1]<o[-1])
        blp =(cr>min_rng and lower[-1]>body[-1]*2.0 and upper[-1]<lower[-1]*0.3 and c[-1]>o[-1])
        be  =(c[-1]<o[-1] and c[-2]>o[-2] and o[-1]>=c[-2]*0.999 and c[-1]<=o[-2]*1.001 and body[-1]>body[-2])
        ble =(c[-1]>o[-1] and c[-2]<o[-2] and o[-1]<=c[-2]*1.001 and c[-1]>=o[-2]*0.999 and body[-1]>body[-2])
        cb  =all(c[-i]<o[-i] for i in range(1,4)); cb2=all(c[-i]>o[-i] for i in range(1,4))
        doji=body[-1]<cr*0.10 if cr>0 else False
        patterns=[]; ss_,ls_=50,50
        if bp:  ss_+=20; patterns.append(f"베어핀({tf_label})")
        if be:  ss_+=18; patterns.append(f"베어인걸({tf_label})")
        if cb and not bp: ss_+=8; patterns.append(f"연속음봉3({tf_label})")
        if blp: ls_+=20; patterns.append(f"불핀({tf_label})")
        if ble: ls_+=18; patterns.append(f"불인걸({tf_label})")
        if cb2 and not blp: ls_+=8; patterns.append(f"연속양봉3({tf_label})")
        if doji: ss_*=0.85; ls_*=0.85; patterns.append(f"도지({tf_label})")
        if patterns: logger.info(f"[캔들패턴/{tf_label}] {patterns}")
        return {"long_score":round(min(100,max(0,ls_)),2),"short_score":round(min(100,max(0,ss_)),2),
                "patterns":patterns,"bearish_pin":bp,"bullish_pin":blp,"bearish_engulf":be,"bullish_engulf":ble,
                "consecutive_bear":cb,"consecutive_bull":cb2}
    except Exception as e:
        logger.warning(f"[캔들패턴/{tf_label}] 오류: {e}"); return _empty


# ══════════════════════════════════════════════════════════════════
# 9. 시장 구조 / 거래량 다이버전스
# ══════════════════════════════════════════════════════════════════

def analyze_market_structure(df):
    _empty={"long_score":50,"short_score":50,"lower_high":False,"higher_low":False,"failed_breakout":False,"failed_breakdown":False}
    if df is None or len(df)<30: return _empty
    try:
        highs=df["high"].astype(float).values; lows=df["low"].astype(float).values; closes=df["close"].astype(float).values
        sh=[]; sl=[]
        for i in range(3,len(highs)-3):
            if highs[i]==max(highs[i-3:i+4]): sh.append(highs[i])
            if lows[i] ==min(lows[i-3:i+4]):  sl.append(lows[i])
        lh=hl=fb=fbd=False; T=config.MARKET_STRUCT_SWING_THRESHOLD
        if len(sh)>=2: lh=sh[-1]<sh[-2]*(1-T)
        if len(sl)>=2: hl=sl[-1]>sl[-2]*(1+T)
        lb=20; rh=max(highs[-lb:-3]); m5=max(highs[-6:-1]); cur=closes[-1]
        if m5>=rh*0.99 and cur<rh*0.98: fb=True
        rl=min(lows[-lb:-3]); m5l=min(lows[-6:-1])
        if m5l<=rl*1.01 and cur>rl*1.02: fbd=True
        ss_=50+(10 if lh else 0)+(16 if fb else 0); ls_=50+(10 if hl else 0)+(16 if fbd else 0)
        sigs=[s for s,v in [("LH",lh),("HL",hl),("돌파실패",fb),("붕괴실패",fbd)] if v]
        if sigs: logger.info(f"[시장구조] {sigs}")
        return {"long_score":round(min(100,max(0,ls_)),2),"short_score":round(min(100,max(0,ss_)),2),
                "lower_high":lh,"higher_low":hl,"failed_breakout":fb,"failed_breakdown":fbd}
    except Exception as e:
        logger.warning(f"[시장구조] 오류: {e}"); return _empty

def analyze_vol_price_divergence(df):
    _empty={"long_score":50,"short_score":50,"bearish_vol_div":False,"bullish_vol_div":False}
    if df is None or len(df)<20: return _empty
    try:
        closes=df["close"].astype(float).values[-20:]; volumes=df["volume"].astype(float).values[-20:]; half=10
        pc,cc=closes[:half],closes[half:]; pv,cv=volumes[:half],volumes[half:]
        phi=int(np.argmax(pc)); chi=int(np.argmax(cc)); plo=int(np.argmin(pc)); clo=int(np.argmin(cc))
        PT=1+config.VOL_DIV_PRICE_THRESHOLD; VB=config.VOL_DIV_BULL_VOLUME_RATIO; VBR=config.VOL_DIV_BEAR_VOLUME_RATIO
        bvd=(cc[chi]>pc[phi]*PT and cv[chi]<pv[phi]*VBR); buvd=(cc[clo]<pc[plo]*(2-PT) and cv[clo]>pv[plo]*VB)
        ss_=50+(18 if bvd else 0); ls_=50+(18 if buvd else 0)
        if bvd:  logger.info("[거래량다이버] ★ 신고가+거래량감소 — 숏")
        if buvd: logger.info("[거래량다이버] ★ 신저가+거래량증가 — 롱")
        return {"long_score":round(min(100,max(0,ls_)),2),"short_score":round(min(100,max(0,ss_)),2),
                "bearish_vol_div":bvd,"bullish_vol_div":buvd}
    except Exception as e:
        logger.warning(f"[거래량다이버] 오류: {e}"); return _empty


# ══════════════════════════════════════════════════════════════════
# [v3.0] ① 스마트머니 LS 다이버전스
# ══════════════════════════════════════════════════════════════════

def analyze_smart_money_divergence(top_trader_ls: dict, retail_ls: dict) -> dict:
    """
    고래(상위 트레이더) vs 개인(일반 계좌) LS 괴리 분석
    divergence = top_trader_long_pct - retail_long_pct
    양수: 고래가 개인보다 더 롱 → 롱 유리
    음수: 고래가 개인보다 더 숏 → 숏 유리
    """
    _empty = {"available": False, "divergence": 0.0,
              "smart_direction": "neutral", "long_score_adj": 0, "short_score_adj": 0}

    if not top_trader_ls.get("available") or not retail_ls.get("available"):
        return _empty

    tt_long  = top_trader_ls.get("long_pct", 0.5)
    ret_long = retail_ls.get("long_pct",     0.5)
    div      = tt_long - ret_long

    if   div >  config.SMART_MONEY_DIV_STRONG:
        direction = "long"; ls_adj = config.BONUS_SMART_MONEY_STRONG; ss_adj = -config.BONUS_SMART_MONEY_STRONG
        logger.info(f"[스마트머니] 🐋 고래 강력 롱 포착 (괴리:{div:+.1%}) → 롱 유리 +{ls_adj}pt")
    elif div >  config.SMART_MONEY_DIV_MILD:
        direction = "long"; ls_adj = config.BONUS_SMART_MONEY_MILD; ss_adj = -config.BONUS_SMART_MONEY_MILD
        logger.info(f"[스마트머니] 🐋 고래 롱 경향 (괴리:{div:+.1%}) → 롱 +{ls_adj}pt")
    elif div < -config.SMART_MONEY_DIV_STRONG:
        direction = "short"; ss_adj = config.BONUS_SMART_MONEY_STRONG; ls_adj = -config.BONUS_SMART_MONEY_STRONG
        logger.info(f"[스마트머니] 🐋 고래 강력 숏 포착 (괴리:{div:+.1%}) → 숏 유리 +{ss_adj}pt")
    elif div < -config.SMART_MONEY_DIV_MILD:
        direction = "short"; ss_adj = config.BONUS_SMART_MONEY_MILD; ls_adj = -config.BONUS_SMART_MONEY_MILD
        logger.info(f"[스마트머니] 🐋 고래 숏 경향 (괴리:{div:+.1%}) → 숏 +{ss_adj}pt")
    else:
        direction = "neutral"; ls_adj = ss_adj = 0
        logger.debug(f"[스마트머니] 중립 (괴리:{div:+.1%})")

    return {
        "available":       True,
        "divergence":      round(div, 4),
        "top_trader_long": round(tt_long, 4),
        "retail_long":     round(ret_long, 4),
        "smart_direction": direction,
        "long_score_adj":  ls_adj,
        "short_score_adj": ss_adj,
    }


# ══════════════════════════════════════════════════════════════════
# [v3.0] ② OI 변화 × 가격 방향 매트릭스
# ══════════════════════════════════════════════════════════════════

def analyze_oi_matrix(oi_data: dict, df_1h) -> dict:
    """
    OI 변화 × 4H 가격 변화 4분면:
      가격↑ OI↑ → 신규 매수 진입 (강한 상승)   → 롱 확증 +10pt
      가격↓ OI↑ → 신규 매도 진입 (강한 하락)   → 숏 확증 +10pt
      가격↑ OI↓ → 숏 커버링 (약한 반등)        → 중립 / 롱 소폭 +3pt
      가격↓ OI↓ → 롱 청산 소진 (바닥 가능)     → 반전 롱 기대 +6pt
    """
    _empty = {"available": False, "quadrant": "neutral",
              "long_score_adj": 0, "short_score_adj": 0,
              "oi_change_pct": 0.0, "price_change_pct": 0.0}

    if not oi_data.get("available") or df_1h is None or len(df_1h) < 5:
        return _empty

    oi_chg   = oi_data.get("oi_change_pct", 0.0)
    oi_avail = oi_data.get("oi_4h_ago", 0) > 0

    # 4H 가격 변화
    try:
        p_now = float(df_1h["close"].iloc[-1])
        p_4h  = float(df_1h["close"].iloc[-5])
        price_chg = (p_now - p_4h) / p_4h if p_4h > 0 else 0.0
    except Exception:
        return _empty

    PT = config.OI_PRICE_CHANGE_THRESHOLD
    OT = config.OI_CHANGE_THRESHOLD

    price_up   = price_chg >  PT
    price_down = price_chg < -PT
    oi_up      = oi_chg    >  OT and oi_avail
    oi_down    = oi_chg    < -OT and oi_avail

    ls_adj = ss_adj = 0; quadrant = "neutral"

    if price_up and oi_up:
        quadrant = "trend_long"
        ls_adj   = config.BONUS_OI_TREND_CONFIRM
        ss_adj   = -config.BONUS_OI_TREND_CONFIRM
        logger.info(f"[OI매트릭스] 💹 가격↑+OI↑ → 신규매수 진입 (강한 상승) 롱+{ls_adj}pt")

    elif price_down and oi_up:
        quadrant = "trend_short"
        ss_adj   = config.BONUS_OI_TREND_CONFIRM
        ls_adj   = -config.BONUS_OI_TREND_CONFIRM
        logger.info(f"[OI매트릭스] 📉 가격↓+OI↑ → 신규매도 진입 (강한 하락) 숏+{ss_adj}pt")

    elif price_down and oi_down:
        quadrant = "reversal_long"
        ls_adj   = config.BONUS_OI_REVERSAL_SIGNAL
        logger.info(f"[OI매트릭스] 🔄 가격↓+OI↓ → 롱 청산 소진 (바닥 가능) 롱+{ls_adj}pt")

    elif price_up and oi_down:
        quadrant = "weak_bounce"
        ls_adj   = 3
        logger.debug(f"[OI매트릭스] 가격↑+OI↓ → 숏커버링 (약한 반등)")

    else:
        logger.debug(f"[OI매트릭스] 중립 (가격:{price_chg:+.2%} OI:{oi_chg:+.2%})")

    return {
        "available":       True,
        "quadrant":        quadrant,
        "long_score_adj":  ls_adj,
        "short_score_adj": ss_adj,
        "oi_change_pct":   round(oi_chg,   4),
        "price_change_pct":round(price_chg, 4),
    }


# ══════════════════════════════════════════════════════════════════
# [v3.0] ③ 펀딩비 히스토리 추세
# ══════════════════════════════════════════════════════════════════

def analyze_funding_history_trend(funding_hist: dict) -> dict:
    """
    64h 펀딩비 히스토리 분석:
      - 전환점 (음→양, 양→음): 심리 전환 신호
      - 연속 극단값: 과열 → 역방향 유리
      - 추세 방향: 롱/숏 소폭 조정
    """
    _empty = {"available": False, "long_score_adj": 0, "short_score_adj": 0,
              "signal": "neutral", "detail": ""}

    if not funding_hist.get("available"):
        return _empty

    flip    = funding_hist.get("flip")
    consec  = funding_hist.get("consecutive_extreme", 0)
    trend   = funding_hist.get("trend", "neutral")
    rates   = funding_hist.get("rates", [])
    current = rates[0] if rates else 0.0

    ls_adj = ss_adj = 0; signal = "neutral"; detail = ""

    # 전환점: 음→양 (롱 과열 시작) → 숏 유리
    if flip == "neg_to_pos":
        ss_adj = config.BONUS_FUNDING_FLIP
        signal = "flip_short"
        detail = f"펀딩 음→양 전환 → 롱과열 시작 신호 숏+{ss_adj}pt"
        logger.info(f"[펀딩추세] {detail}")

    # 전환점: 양→음 (숏 과열 시작) → 롱 유리
    elif flip == "pos_to_neg":
        ls_adj = config.BONUS_FUNDING_FLIP
        signal = "flip_long"
        detail = f"펀딩 양→음 전환 → 숏과열 시작 신호 롱+{ls_adj}pt"
        logger.info(f"[펀딩추세] {detail}")

    # 연속 극단 양수 (4회 이상) → 롱 과열 → 숏 유리
    elif consec >= 4 and current > 0:
        ss_adj = config.BONUS_FUNDING_EXTREME_ACCUM
        signal = "extreme_long_heat"
        detail = f"펀딩 {consec}회 연속 극단 양수 → 롱과열 누적 숏+{ss_adj}pt"
        logger.info(f"[펀딩추세] {detail}")

    # 연속 극단 음수 → 숏 과열 → 롱 유리
    elif consec >= 4 and current < 0:
        ls_adj = config.BONUS_FUNDING_EXTREME_ACCUM
        signal = "extreme_short_heat"
        detail = f"펀딩 {consec}회 연속 극단 음수 → 숏과열 누적 롱+{ls_adj}pt"
        logger.info(f"[펀딩추세] {detail}")

    # 추세 방향 소폭 반영
    elif trend == "rising" and current > 0:
        ss_adj = 3; signal = "rising_long_bias"
        detail = f"펀딩 상승 추세 (롱편향 강화 중) 숏+3pt"
    elif trend == "falling" and current < 0:
        ls_adj = 3; signal = "falling_short_bias"
        detail = f"펀딩 하락 추세 (숏편향 강화 중) 롱+3pt"

    return {
        "available":       True,
        "long_score_adj":  ls_adj,
        "short_score_adj": ss_adj,
        "signal":          signal,
        "detail":          detail,
    }


# ══════════════════════════════════════════════════════════════════
# [v3.0] ⑥ 멀티TF 모멘텀 정합
# ══════════════════════════════════════════════════════════════════

def analyze_mtf_momentum(df_1h, df_4h, df_1d) -> dict:
    """
    1h/4h/1d RSI 기울기 (4캔들) 기반 모멘텀 방향 일치도
    slope = rsi[-1] - rsi[-4] (4봉 기울기)
    MIN = MTF_MOMENTUM_RSI_SLOPE_MIN
    """
    _empty = {"available": False, "alignment": 0, "direction": "neutral",
              "long_score_adj": 0, "short_score_adj": 0,
              "slopes": {}}

    MIN = config.MTF_MOMENTUM_RSI_SLOPE_MIN

    def _slope(df):
        if df is None or len(df) < 8: return 0.0
        rsi = calculate_rsi(df)
        return float(rsi.iloc[-1] - rsi.iloc[-4])

    s1h = _slope(df_1h); s4h = _slope(df_4h); s1d = _slope(df_1d)

    def _dir(s):
        if s >  MIN: return "bull"
        if s < -MIN: return "bear"
        return "neutral"

    d1h = _dir(s1h); d4h = _dir(s4h); d1d = _dir(s1d)

    bull_cnt = [d1h,d4h,d1d].count("bull")
    bear_cnt = [d1h,d4h,d1d].count("bear")

    ls_adj = ss_adj = 0; direction = "neutral"; alignment = 0

    if bull_cnt == 3:
        ls_adj = config.BONUS_MTF_MOMENTUM_FULL; alignment = 3; direction = "bull"
        logger.info(f"[멀티TF모멘텀] ★★★ 3/3 상승 정합 → 롱+{ls_adj}pt")
    elif bull_cnt == 2 and bear_cnt == 0:
        ls_adj = config.BONUS_MTF_MOMENTUM_PARTIAL; alignment = 2; direction = "bull"
        logger.info(f"[멀티TF모멘텀] ★★ 2/3 상승 정합 → 롱+{ls_adj}pt")
    elif bear_cnt == 3:
        ss_adj = config.BONUS_MTF_MOMENTUM_FULL; alignment = -3; direction = "bear"
        logger.info(f"[멀티TF모멘텀] ★★★ 3/3 하락 정합 → 숏+{ss_adj}pt")
    elif bear_cnt == 2 and bull_cnt == 0:
        ss_adj = config.BONUS_MTF_MOMENTUM_PARTIAL; alignment = -2; direction = "bear"
        logger.info(f"[멀티TF모멘텀] ★★ 2/3 하락 정합 → 숏+{ss_adj}pt")
    else:
        logger.debug(f"[멀티TF모멘텀] 혼조 (1h:{d1h} 4h:{d4h} 1d:{d1d})")

    return {
        "available":       True,
        "alignment":       alignment,
        "direction":       direction,
        "long_score_adj":  ls_adj,
        "short_score_adj": ss_adj,
        "slopes":          {"1h":round(s1h,2),"4h":round(s4h,2),"1d":round(s1d,2)},
        "dirs":            {"1h":d1h,"4h":d4h,"1d":d1d},
    }


# ══════════════════════════════════════════════════════════════════
# [v3.0] ⑧ 주간 키레벨 S/R
# ══════════════════════════════════════════════════════════════════

def detect_weekly_levels(df_1d, current_price: float) -> dict:
    """
    전주 고/저가 + 전일 키레벨 → S/R 근접 여부
    df_1d: 최소 10개 일봉 필요
    """
    _empty = {"available": False, "near_level": False, "level_type": None,
              "level_price": None, "distance_pct": None,
              "long_score_adj": 0, "short_score_adj": 0}

    if df_1d is None or len(df_1d) < 10 or current_price <= 0:
        return _empty

    try:
        highs  = df_1d["high"].astype(float).values
        lows   = df_1d["low"].astype(float).values
        closes = df_1d["close"].astype(float).values

        # 전주(7일) 고/저가
        prev_week_high = float(np.max(highs[-9:-2]))
        prev_week_low  = float(np.min(lows[-9:-2]))
        prev_day_high  = float(highs[-2])
        prev_day_low   = float(lows[-2])
        prev_day_close = float(closes[-2])

        levels = [
            ("prev_week_high",  prev_week_high),
            ("prev_week_low",   prev_week_low),
            ("prev_day_high",   prev_day_high),
            ("prev_day_low",    prev_day_low),
            ("prev_day_close",  prev_day_close),
        ]

        TOL = config.WEEKLY_LEVEL_TOLERANCE

        for level_type, level_price in levels:
            dist = abs(current_price - level_price) / level_price
            if dist <= TOL:
                is_resistance = current_price < level_price
                ls_adj = ss_adj = 0
                if is_resistance:
                    ss_adj = config.BONUS_WEEKLY_KEY_LEVEL
                    logger.info(f"[주간레벨] ⚠️ {level_type}={level_price:.1f} 근접 저항 ({dist:.2%}) 숏+{ss_adj}pt")
                else:
                    ls_adj = config.BONUS_WEEKLY_KEY_LEVEL
                    logger.info(f"[주간레벨] ✅ {level_type}={level_price:.1f} 근접 지지 ({dist:.2%}) 롱+{ls_adj}pt")

                return {
                    "available":       True,
                    "near_level":      True,
                    "level_type":      level_type,
                    "level_price":     round(level_price, 4),
                    "distance_pct":    round(dist, 4),
                    "is_resistance":   is_resistance,
                    "long_score_adj":  ls_adj,
                    "short_score_adj": ss_adj,
                }

        return {"available": True, "near_level": False, "level_type": None,
                "level_price": None, "distance_pct": None, "long_score_adj": 0, "short_score_adj": 0}

    except Exception as e:
        logger.warning(f"[주간레벨] 오류: {e}")
        return _empty


# ══════════════════════════════════════════════════════════════════
# [v3.0] ⑨ 1D EMA 구조 스코어
# ══════════════════════════════════════════════════════════════════

def analyze_1d_ema_structure(df_1d, current_price: float) -> dict:
    """
    1d EMA20/50/200 구조 분석:
      강세: price > EMA20 > EMA50 > EMA200 → 임계값 완화
      약세: price < EMA20 < EMA50 < EMA200 → 역방향 임계값 강화
      EMA200 이격 15% 이상 → 평균회귀 위험 추가 패널티
    """
    _empty = {
        "available": False, "structure": "neutral",
        "ema20": None, "ema50": None, "ema200": None,
        "dist_from_200": None, "long_threshold_adj": 0, "short_threshold_adj": 0,
    }

    if df_1d is None or len(df_1d) < 60 or current_price <= 0:
        return _empty

    try:
        close = df_1d["close"].astype(float)
        ema20  = float(_calc_ema(close, 20).iloc[-1])
        ema50  = float(_calc_ema(close, 50).iloc[-1])
        ema200 = float(_calc_ema(close, 200).iloc[-1]) if len(df_1d) >= 200 else None

        dist200 = (current_price - ema200) / ema200 if ema200 else None

        bull_struct = (current_price > ema20 > ema50)
        if ema200: bull_struct = bull_struct and (ema50 > ema200)

        bear_struct = (current_price < ema20 < ema50)
        if ema200: bear_struct = bear_struct and (ema50 < ema200)

        lt_adj = st_adj = 0

        if bull_struct:
            structure = "bull"
            lt_adj = config.EMA_STRUCTURE_ALIGN_ADJ     # -5 (롱 완화)
            st_adj = config.EMA_STRUCTURE_AGAINST_ADJ   # +8 (역추세 숏 강화)
            logger.info(f"[1D-EMA구조] 📈 강세구조 price>{ema20:.0f}>EMA50 → 롱임계{lt_adj:+d}pt")

        elif bear_struct:
            structure = "bear"
            st_adj = config.EMA_STRUCTURE_ALIGN_ADJ     # -5 (숏 완화)
            lt_adj = config.EMA_STRUCTURE_AGAINST_ADJ   # +8 (역추세 롱 강화)
            logger.info(f"[1D-EMA구조] 📉 약세구조 price<{ema20:.0f}<EMA50 → 숏임계{st_adj:+d}pt")

        else:
            structure = "neutral"
            logger.debug(f"[1D-EMA구조] 중립 (price:{current_price:.0f} EMA20:{ema20:.0f} EMA50:{ema50:.0f})")

        # EMA200 이격 극단 패널티
        if dist200 is not None and abs(dist200) >= config.EMA_DISTANCE_EXTREME:
            if dist200 > 0:   # 위에서 너무 멀리
                lt_adj += config.EMA_DISTANCE_EXTREME_ADJ
                logger.info(f"[1D-EMA구조] ⚠️ EMA200 상방 {dist200:.0%} 이격 → 롱임계+{config.EMA_DISTANCE_EXTREME_ADJ}pt (평균회귀 위험)")
            else:             # 아래서 너무 멀리
                st_adj += config.EMA_DISTANCE_EXTREME_ADJ
                logger.info(f"[1D-EMA구조] ⚠️ EMA200 하방 {dist200:.0%} 이격 → 숏임계+{config.EMA_DISTANCE_EXTREME_ADJ}pt")

        return {
            "available":          True,
            "structure":          structure,
            "ema20":              round(ema20, 4),
            "ema50":              round(ema50, 4),
            "ema200":             round(ema200, 4) if ema200 else None,
            "dist_from_200":      round(dist200, 4) if dist200 is not None else None,
            "long_threshold_adj": lt_adj,
            "short_threshold_adj":st_adj,
        }

    except Exception as e:
        logger.warning(f"[1D-EMA구조] 오류: {e}")
        return _empty


# ══════════════════════════════════════════════════════════════════
# 일봉 바이어스
# ══════════════════════════════════════════════════════════════════

def analyze_daily_bias(df_1d):
    _neutral={"bias":"NEUTRAL","threshold_adj_long":0,"threshold_adj_short":0,"bull_count":0,"bear_count":0,"ema9":None,"ema21":None}
    if df_1d is None or len(df_1d)<10: return _neutral
    try:
        close=df_1d["close"].astype(float); open_=df_1d["open"].astype(float)
        pc=float(close.iloc[-2]); po=float(open_.iloc[-2]); cc=float(close.iloc[-1])
        e9=float(_calc_ema(close,9).iloc[-1]); e21=float(_calc_ema(close,21).iloc[-1])
        bull=[pc>po, e9>e21, cc>pc]; bear=[pc<po, e9<e21, cc<pc]
        bc=sum(bull); berc=sum(bear)
        if bc>=2: bias,al,as_="BULL",config.DAILY_BIAS_THRESHOLD_ADJ_ALIGN,config.DAILY_BIAS_THRESHOLD_ADJ_AGAINST
        elif berc>=2: bias,al,as_="BEAR",config.DAILY_BIAS_THRESHOLD_ADJ_AGAINST,config.DAILY_BIAS_THRESHOLD_ADJ_ALIGN
        else: bias,al,as_="NEUTRAL",0,0
        logger.info(f"[일봉바이어스] {bias} (강세:{bc}/3 약세:{berc}/3) | 롱임계:{al:+d}pt 숏임계:{as_:+d}pt")
        return {"bias":bias,"threshold_adj_long":al,"threshold_adj_short":as_,"bull_count":bc,"bear_count":berc,"ema9":round(e9,4),"ema21":round(e21,4)}
    except Exception as e:
        logger.warning(f"[일봉바이어스] 오류: {e}"); return _neutral


# ══════════════════════════════════════════════════════════════════
# 전체 분석 통합
# ══════════════════════════════════════════════════════════════════

def run_full_analysis(symbol, collected_data):
    import datetime
    logger.info(f"{chr(8213)*50}")
    logger.info(f"🔬 분석 [1H봇 v3.0]: {symbol}")

    ohlcv        = collected_data.get("ohlcv", {})
    ticker       = collected_data.get("ticker") or {}
    funding_data = collected_data.get("funding_rate")
    ls_raw       = collected_data.get("ls_ratio", {})
    taker_raw    = collected_data.get("taker_volume", {})
    liq_raw      = collected_data.get("liquidations", {})
    top_trader   = collected_data.get("top_trader_ls", {})
    oi_raw       = collected_data.get("oi_data", {})
    fund_hist    = collected_data.get("funding_history", {})

    df_1h = ohlcv.get("1h"); df_4h = ohlcv.get("4h"); df_1d = ohlcv.get("1d")
    price = ticker.get("last") or 0.0

    # ── 기본 분석 ────────────────────────────────────────────
    rsi     = analyze_mtf_rsi(df_1h, df_4h, df_1d)
    bb      = analyze_bollinger_bands(df_1h)
    adx_1h  = calculate_adx(df_1h)
    adx_4h  = calculate_adx(df_4h)
    funding = analyze_funding_rate(funding_data)
    regime  = classify_market_regime(df_1h, adx_1h, bb)
    regime_name = regime.get("regime","UNKNOWN")

    ls_ratio = analyze_long_short_ratio(ls_raw, regime_name)
    taker    = analyze_taker_volume(taker_raw)
    liq      = analyze_liquidations(liq_raw, df_1h)
    vol      = check_volume_confirmation(df_1h, df_4h=df_4h)
    atr      = get_atr_state(df_1h)

    candle_1h = analyze_candle_pattern(df_1h, "1h")
    ms        = analyze_market_structure(df_1h)
    vpd       = analyze_vol_price_divergence(df_1h)
    fvg       = detect_fvg(df_1h)
    bos_1h    = detect_bos_choch(df_1h, lookback=60, n=3)
    fib       = check_fibonacci_levels(df_1h)
    ema_long  = calculate_ema_multiplier(ohlcv, "long",  regime_name)
    ema_short = calculate_ema_multiplier(ohlcv, "short", regime_name)
    gate_long = evaluate_gates("long",  funding, ls_ratio)
    gate_short= evaluate_gates("short", funding, ls_ratio)

    # ── v2.0 분석 ────────────────────────────────────────────
    bb_4h        = analyze_bollinger_bands(df_4h)
    regime_4h    = classify_market_regime(df_4h, adx_4h, bb_4h)
    bos_4h       = detect_bos_choch(df_4h, lookback=30, n=2)
    daily_bias   = analyze_daily_bias(df_1d)

    # ── [v3.0] 신규 분석 ─────────────────────────────────────
    candle_4h    = analyze_candle_pattern(df_4h, "4h")
    candle_1d    = analyze_candle_pattern(df_1d, "1d")
    smart_money  = analyze_smart_money_divergence(top_trader, ls_raw)
    oi_matrix    = analyze_oi_matrix(oi_raw, df_1h)
    fund_trend   = analyze_funding_history_trend(fund_hist)
    mtf_momentum = analyze_mtf_momentum(df_1h, df_4h, df_1d)
    weekly_lvl   = detect_weekly_levels(df_1d, price)
    ema_struct   = analyze_1d_ema_structure(df_1d, price)

    # ── 요약 로그 ────────────────────────────────────────────
    logger.info(
        f"  MTF-RSI: 1h:{rsi['value']:.1f} 4h:{rsi.get('value_1h') or '-'} "
        f"1d:{rsi.get('value_4h') or '-'} [{rsi['state']}] | "
        f"BB:{bb['state']}(%B={bb['pct_b']:.2f}) | ADX:{adx_1h['adx']:.1f} | "
        f"1h국면:{regime_name} | Vol:{vol['ratio']:.2f}x | "
        f"Taker:{taker.get('bias','?')} | 청산:{liq.get('signal','none')}"
    )
    logger.info(
        f"  [v3.0] 스마트머니:{smart_money.get('smart_direction','?')}(괴리:{smart_money.get('divergence',0):+.1%}) | "
        f"OI매트릭스:{oi_matrix.get('quadrant','?')} | "
        f"펀딩추세:{fund_trend.get('signal','?')} | "
        f"모멘텀정합:{mtf_momentum.get('direction','?')}({mtf_momentum.get('alignment',0)}/3) | "
        f"1D-EMA:{ema_struct.get('structure','?')} | "
        f"주간레벨:{weekly_lvl.get('level_type','없음')}"
    )

    return {
        "symbol":           symbol,
        "current_price":    price,
        "rsi":              rsi,
        "bollinger":        bb,
        "ema_long":         ema_long,
        "ema_short":        ema_short,
        "adx_1h":           adx_1h,
        "adx_4h":           adx_4h,
        "funding_rate":     funding,
        "ls_ratio":         ls_ratio,
        "oi_change":        {"available": False},
        "taker_volume":     taker,
        "liquidations":     liq,
        "volume":           vol,
        "atr":              atr,
        "regime":           regime,
        "regime_4h":        regime_4h,
        "daily_bias":       daily_bias,
        "bos_choch":        bos_1h,
        "bos_choch_4h":     bos_4h,
        "gate_long":        gate_long,
        "gate_short":       gate_short,
        "candle_pattern":   candle_1h,
        "candle_pattern_4h":candle_4h,
        "candle_pattern_1d":candle_1d,
        "market_structure": ms,
        "vol_price_div":    vpd,
        "fvg":              fvg,
        "fibonacci":        fib,
        # [v3.0]
        "smart_money":      smart_money,
        "oi_matrix":        oi_matrix,
        "funding_trend":    fund_trend,
        "mtf_momentum":     mtf_momentum,
        "weekly_levels":    weekly_lvl,
        "ema_structure":    ema_struct,
        "analyzed_at":      datetime.datetime.utcnow().isoformat() + "Z",
    }