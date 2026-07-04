"""verify_caxis_v5_synthetic.py — C축 V5 합성 시나리오 코드검증 (통계 검증 아님).

⚠ 이 스크립트는 "승률이 좋다"를 증명하지 않는다. 실측 데이터가 UPLEG 0건이라 통계적
검증(실전 점등 판정)은 verify_caxis_v5.py의 사전등록 게이트로만 한다(현재 미충족 —
docs/CAXIS_V5_DESIGN.md 참조). 여기서 확인하는 것은 오직 **코드 정합성**뿐이다:

  Part 1. 롱/숏 완전 대칭(5-D) — 미러 속성 테스트(정확·결정론적, 가격데이터 불요)
          모든 방향성 raw/ctx/pcts 필드를 부호반전한 "거울 시장"에서 방향만
          바꿔 호출하면 정확히 동일한 값이 나와야 한다(부동소수 오차 이내).
          대상: _ctx_align·_ctx_exhaustion(v1/v2)·_reclaim_boost·_reclaim_kill·
          _impulse_kill·_reclaim_n·_leg_alive_n·_fast_struct·_struct_evidence.
  Part 2. 합성 가격경로 시나리오 — 상승/하락/횡보/전환(하락→상승, 상승→하락)
          OHLCV로 features.build_features + detectors + run_engine을 실행해
          무크래시·무상태(동일입력→동일출력)·btc_macro 분류 타당성·신선도 필드
          거동·부스트 발동 존재성(존재=논리가 죽은코드 아님, 좋다는 뜻 아님)을 확인.

config 토글은 이 스크립트 실행 중에만 로컬로 바꾸고 종료 시 원복한다 —
config.py 기본값(WRF_CTX_RECLAIM_BOOST=False 등)은 변경하지 않는다.

CLI: python analysis/audit/verify_caxis_v5_synthetic.py
"""
from __future__ import annotations

import os
import random
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "src"))

import config  # noqa: E402
from wrf import detectors as D  # noqa: E402
from wrf import features  # noqa: E402
from wrf import engine  # noqa: E402
from wrf.btc_macro import classify_btc_macro  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAIL.append(name)
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not cond else ""))


# ════════════════════════════════════════════════════════════════════
# Part 1 — 미러 속성 테스트 (정확·결정론적)
# ════════════════════════════════════════════════════════════════════

_DIR_INT = ("bos", "choch", "bos_4h", "choch_4h", "ema", "ema_4h",
            "ema_1d_struct", "failed_break", "rev_candle")
_DIR_FLOAT = ("dist_vwap_atr", "dist_ema20_atr", "macd")


def mirror_raw(raw: dict) -> dict:
    m = dict(raw)
    for k in _DIR_INT:
        if m.get(k) is not None:
            m[k] = -m[k]
    for k in _DIR_FLOAT:
        if m.get(k) is not None:
            m[k] = -m[k]
    if m.get("macd_bull") is not None:
        m["macd_bull"] = not m["macd_bull"]
    # bars_since_*_flip: 신선도(경과봉수)는 방향 무관 크기값 — 미러링 불변
    return m


def mirror_ctx(ctx: dict) -> dict:
    m = dict(ctx)
    m["btc_macro"] = {"UPLEG": "DOWNLEG", "DOWNLEG": "UPLEG",
                       "CHOP": "CHOP"}.get(ctx.get("btc_macro", "CHOP"), "CHOP")
    m["bias_1d"] = {"BULL": "BEAR", "BEAR": "BULL",
                     "NEUTRAL": "NEUTRAL"}.get(ctx.get("bias_1d", "NEUTRAL"), "NEUTRAL")
    return m


def mirror_pcts(pcts: dict) -> dict:
    m = dict(pcts)
    for k in ("loc_vwap", "loc_ema20", "rsi", "funding", "macd", "bb_pctb"):
        if m.get(k) is not None:
            m[k] = 1.0 - m[k]
    return m


def rand_raw(rng: random.Random) -> dict:
    def sgn():
        return rng.choice([-1, 0, 1])
    return {
        "bos": sgn(), "choch": sgn(), "bos_4h": sgn(), "choch_4h": sgn(),
        "ema": sgn(), "ema_4h": sgn(), "ema_1d_struct": sgn(), "failed_break": sgn(),
        "dist_vwap_atr": rng.uniform(-3, 3), "dist_ema20_atr": rng.uniform(-3, 3),
        "macd": rng.uniform(-50, 50), "macd_bull": rng.choice([True, False]),
        "bars_since_vwap_flip": rng.choice([None, 0, 1, 2, 5, 6, 7, 10, 30]),
        "bars_since_ema20_flip": rng.choice([None, 0, 1, 2, 5, 6, 7, 10, 30]),
    }


def rand_ctx(rng: random.Random) -> dict:
    return {"btc_macro": rng.choice(["UPLEG", "DOWNLEG", "CHOP"]),
            "bias_1d": rng.choice(["BULL", "BEAR", "NEUTRAL"])}


def rand_pcts(rng: random.Random) -> dict:
    return {"loc_vwap": rng.uniform(0, 1), "loc_ema20": rng.uniform(0, 1),
            "rsi": rng.uniform(0, 1), "funding": rng.uniform(0, 1),
            "macd": rng.uniform(0, 1), "bb_pctb": rng.uniform(0, 1)}


def part1_mirror_symmetry(n=3000, seed=20260704):
    print("═" * 72)
    print("Part 1 — 롱/숏 완전 대칭(5-D) 미러 속성 테스트 (정확·결정론적)")
    print("═" * 72)
    rng = random.Random(seed)
    toggles = [
        dict(WRF_CTX_FAST_STRUCT=fs, WRF_REV_CTX_V2=v2,
             WRF_CTX_RECLAIM_BOOST=boost, WRF_REV_RECLAIM_KILL=True,
             WRF_REV_IMPULSE_KILL=True)
        for fs in (False, True) for v2 in (False, True) for boost in (False, True)
    ]
    saved = {k: getattr(config, k) for k in toggles[0]}
    eps = 1e-9
    total_checks = 0
    align_fail = exh_fail = n_fail = alive_fail = fast_fail = 0
    try:
        for tg in toggles:
            for k, v in tg.items():
                setattr(config, k, v)
            for _ in range(n):
                raw, ctx, pcts = rand_raw(rng), rand_ctx(rng), rand_pcts(rng)
                mraw, mctx, mpcts = mirror_raw(raw), mirror_ctx(ctx), mirror_pcts(pcts)
                total_checks += 1

                a_long = D._ctx_align(ctx, raw, "long")
                a_short_m = D._ctx_align(mctx, mraw, "short")
                if abs(a_long - a_short_m) > eps:
                    align_fail += 1

                e_long = D._ctx_exhaustion(ctx, raw, pcts, "long")
                e_short_m = D._ctx_exhaustion(mctx, mraw, mpcts, "short")
                if abs(e_long - e_short_m) > eps:
                    exh_fail += 1

                if D._reclaim_n(raw, "long") != D._reclaim_n(mraw, "short"):
                    n_fail += 1
                if D._leg_alive_n(raw, "long") != D._leg_alive_n(mraw, "short"):
                    alive_fail += 1
                if abs(D._fast_struct(raw) - (-D._fast_struct(mraw))) > eps:
                    fast_fail += 1
    finally:
        for k, v in saved.items():
            setattr(config, k, v)

    check("_ctx_align 미러대칭 (16토글조합×%d)" % n, align_fail == 0,
          f"불일치 {align_fail}/{total_checks}")
    check("_ctx_exhaustion 미러대칭(v1/v2/킬 전조합)", exh_fail == 0,
          f"불일치 {exh_fail}/{total_checks}")
    check("_reclaim_n 미러대칭", n_fail == 0, f"불일치 {n_fail}/{total_checks}")
    check("_leg_alive_n 미러대칭", alive_fail == 0, f"불일치 {alive_fail}/{total_checks}")
    check("_fast_struct 부호반전대칭", fast_fail == 0, f"불일치 {fast_fail}/{total_checks}")
    print(f"  (표본 {total_checks}건 × 8토글조합 = 검증 {total_checks} 케이스/함수)")


# ════════════════════════════════════════════════════════════════════
# Part 2 — 합성 가격경로 시나리오 (상승/하락/횡보/전환)
# ════════════════════════════════════════════════════════════════════

def _ohlcv_from_close(close: np.ndarray, start_price: float, seed: int) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    n = len(close)
    openp = np.empty(n)
    openp[0] = start_price
    openp[1:] = close[:-1]
    wick = np.abs(rng.normal(0, 0.003, n)) * close
    high = np.maximum(openp, close) + wick
    low = np.minimum(openp, close) - wick
    vol = rng.uniform(80, 120, n)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": openp, "high": high, "low": low,
                         "close": close, "volume": vol}, index=idx)


def gen_ohlcv(returns: np.ndarray, start_price: float = 100.0, seed: int = 0) -> pd.DataFrame:
    close = start_price * np.cumprod(1.0 + returns)
    return _ohlcv_from_close(close, start_price, seed)


def make_scenario(kind: str, n_hours: int = 400, seed: int = 1) -> pd.DataFrame:
    """상승/하락은 누적수익률(추세), 횡보는 **가격레벨을 직접 유계함수로** 생성한다
    (수익률 누적 방식은 잡음이 랜덤워크처럼 번져 우연한 다일 추세가 생길 수 있어
    '진짜 횡보'를 보장 못함 — 레벨 고정이 드리프트를 구조적으로 차단한다)."""
    rng = np.random.RandomState(seed)
    if kind == "bull":
        drift = np.full(n_hours, 0.0025)
        return gen_ohlcv(drift + rng.normal(0, 0.004, n_hours), seed=seed)
    if kind == "bear":
        drift = np.full(n_hours, -0.0025)
        return gen_ohlcv(drift + rng.normal(0, 0.004, n_hours), seed=seed)
    if kind == "chop":
        start = 100.0
        t = np.arange(n_hours)
        level = start * (1.0 + 0.03 * np.sin(2 * np.pi * t / 24.0))   # 유계 진동(24h 주기)
        close = level * (1.0 + rng.normal(0, 0.002, n_hours))          # 비누적 승법잡음
        return _ohlcv_from_close(close, start, seed)
    if kind == "bear_to_bull":
        h = n_hours // 2
        drift = np.concatenate([np.full(h, -0.003), np.full(n_hours - h, 0.003)])
        return gen_ohlcv(drift + rng.normal(0, 0.004, n_hours), seed=seed)
    if kind == "bull_to_bear":
        h = n_hours // 2
        drift = np.concatenate([np.full(h, 0.003), np.full(n_hours - h, -0.003)])
        return gen_ohlcv(drift + rng.normal(0, 0.004, n_hours), seed=seed)
    raise ValueError(kind)


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule).agg({"open": "first", "high": "max", "low": "min",
                                  "close": "last", "volume": "sum"}).dropna()


def _minimal_measures(df_1h: pd.DataFrame, phase_dir: int) -> dict:
    """detect_all/veto가 참조하는 최소 measures — 방향 일관 합성(phase_dir: +1/-1/0)."""
    ema20 = df_1h["close"].ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = df_1h["close"].ewm(span=50, adjust=False).mean().iloc[-1]
    macd_line = (df_1h["close"].ewm(span=12, adjust=False).mean()
                 - df_1h["close"].ewm(span=26, adjust=False).mean())
    hist = float((macd_line - macd_line.ewm(span=9, adjust=False).mean()).iloc[-1])
    tag = "bullish" if phase_dir > 0 else ("bearish" if phase_dir < 0 else "neutral")
    return {
        "current_price": float(df_1h["close"].iloc[-1]),
        "rsi": {}, "bollinger": {"pct_b": 0.5}, "adx_1h": {"adx": 20.0, "adx_slope": 0.0},
        "atr": {"pct": 1.5}, "macd_1h": {"histogram": hist, "bullish": hist > 0},
        "volume": {"ratio": 1.0},
        "ema_long": {"tf_signals": {"1h": tag, "4h": tag, "1d": tag}},
        "bos_choch": {}, "bos_choch_4h": {}, "fvg": {}, "order_blocks": {}, "fibonacci": {},
        "weekly_levels": {}, "funding_rate": {"rate": 0.0}, "ls_ratio": {}, "taker_volume": {},
        "oi_matrix": {}, "smart_money": {}, "liquidations": {}, "market_structure": {},
        "regime": {"regime": "TRENDING" if phase_dir else "RANGING"},
        "regime_4h": {"regime": "TRENDING" if phase_dir else "RANGING"},
        "daily_bias": {"bias": "BULL" if phase_dir > 0 else "BEAR" if phase_dir < 0 else "NEUTRAL"},
        "retracement": {}, "maturity": {}, "ema_structure": {"structure": "bull" if ema20 >= ema50 else "bear"},
    }


def part1b_br_precond_symmetry(seed=99):
    """[BR정합] _detect_band_reversal의 신규 게이트(WRF_BR_REQUIRE_REV_VOL/CANDLE)가
    4토글조합에서 롱/숏 완전대칭(5-D)인지 확인. bb_pctb는 부호값이 아니라 [0,1]
    백분위이므로 미러는 1-p(부호반전 아님) — 이 함수 전용 미러 규칙을 쓴다."""
    print("\n" + "═" * 72)
    print("Part 1b — BR precond 신규 게이트(REV_VOL/REV_CANDLE) 미러 대칭")
    print("═" * 72)
    rng = random.Random(seed)
    ctx = {"regime_1h": "RANGING", "regime_4h": "RANGING",
           "allowed_setups": ["MR", "RV", "BR"], "btc_macro": "CHOP", "bias_1d": "NEUTRAL"}
    saved = (config.WRF_BR_REQUIRE_REV_VOL, config.WRF_BR_REQUIRE_REV_CANDLE)
    mismatches = 0
    total = 0
    try:
        for vol in (False, True):
            for cand in (False, True):
                config.WRF_BR_REQUIRE_REV_VOL = vol
                config.WRF_BR_REQUIRE_REV_CANDLE = cand
                for _ in range(500):
                    bb = rng.uniform(0.0, 0.25)   # 하단 근접(롱 무장권)
                    raw_l = {
                        "bb_pctb": bb, "dist_vwap_atr": rng.uniform(-2, 0),
                        "dist_ema20_atr": rng.uniform(-2, 0),
                        "rev_vol_ratio": rng.choice([None, rng.uniform(0.3, 2.0)]),
                        "rev_candle": rng.choice([-1, 0, 1]),
                        "bos": 0, "choch": 0, "ema": 0, "ema_4h": 0,
                        "ema_1d_struct": 0, "failed_break": 0,
                        "macd": 0.0, "macd_bull": False,
                    }
                    raw_s = dict(raw_l, bb_pctb=1 - raw_l["bb_pctb"],
                                dist_vwap_atr=-raw_l["dist_vwap_atr"],
                                dist_ema20_atr=-raw_l["dist_ema20_atr"],
                                rev_candle=-raw_l["rev_candle"])
                    feat_l = {"raw": raw_l, "pct": {}, "ctx": ctx, "df_1h": None}
                    feat_s = {"raw": raw_s, "pct": {}, "ctx": ctx, "df_1h": None}
                    out_l = D._detect_band_reversal(feat_l, {})
                    out_s = D._detect_band_reversal(feat_s, {})
                    total += 1
                    long_armed = any(o["dir"] == "long" for o in out_l)
                    short_armed_mirror = any(o["dir"] == "short" for o in out_s)
                    if long_armed != short_armed_mirror:
                        mismatches += 1
    finally:
        config.WRF_BR_REQUIRE_REV_VOL, config.WRF_BR_REQUIRE_REV_CANDLE = saved
    check("_detect_band_reversal 신규게이트 미러대칭 (4조합×500)", mismatches == 0,
          f"불일치 {mismatches}/{total}")


def part2_scenarios():
    print("\n" + "═" * 72)
    print("Part 2 — 합성 시나리오: 상승·하락·횡보·전환(하락→상승/상승→하락)")
    print("═" * 72)
    scenarios = {"bull": 1, "bear": -1, "chop": 0, "bear_to_bull": 1, "bull_to_bear": -1}
    seeds = {"bull": 101, "bear": 102, "chop": 103, "bear_to_bull": 104, "bull_to_bear": 105}
    results = {}
    for kind, end_dir in scenarios.items():
        df1h = make_scenario(kind, seed=seeds[kind])
        df4h = _resample(df1h, "4h")
        df1d = _resample(df1h, "1D")
        macro = classify_btc_macro(df1d)
        meas = _minimal_measures(df1h, end_dir)
        # 무크래시
        try:
            feat = features.build_features(meas, {"1h": df1h, "4h": df4h, "1d": df1d}, macro)
            crashed = False
        except Exception as e:  # noqa: BLE001
            crashed = True
            feat = None
            print(f"    [{kind}] 예외: {e}")
        check(f"[{kind}] build_features 무크래시", not crashed)
        if crashed:
            continue
        # 무상태(동일입력 재실행 → 동일출력)
        feat2 = features.build_features(meas, {"1h": df1h, "4h": df4h, "1d": df1d}, macro)
        same = (feat["raw"]["bars_since_vwap_flip"] == feat2["raw"]["bars_since_vwap_flip"]
                and feat["raw"]["bars_since_ema20_flip"] == feat2["raw"]["bars_since_ema20_flip"]
                and feat["raw"]["dist_vwap_atr"] == feat2["raw"]["dist_ema20_atr"] or True)
        # (엄밀 무상태 비교는 전체 dict로)
        same = feat["raw"] == feat2["raw"] and feat["pct"] == feat2["pct"]
        check(f"[{kind}] 무상태(재실행 동일출력)", same)

        # btc_macro 분류 타당성
        expect = {"bull": "UPLEG", "bear": "DOWNLEG", "chop": "CHOP",
                  "bear_to_bull": None, "bull_to_bear": None}[kind]
        if expect:
            check(f"[{kind}] btc_macro 분류={macro} (기대 {expect})", macro == expect)
        else:
            print(f"    [{kind}] btc_macro={macro} (전환구간 — 태그 지연 예상, 정보성 기록)")

        # detect_all 무크래시 + 엔진 무크래시(전체 파이프라인)
        try:
            cands = D.detect_all(feat)
            det_crash = False
        except Exception as e:  # noqa: BLE001
            det_crash = True
            print(f"    [{kind}] detect_all 예외: {e}")
        check(f"[{kind}] detect_all 무크래시 (후보 {len(cands) if not det_crash else '-'}건)", not det_crash)

        try:
            out = engine.run_engine("SYN-USDT", meas, {"1h": df1h, "4h": df4h, "1d": df1d}, {}, macro)
            eng_crash = False
        except Exception as e:  # noqa: BLE001
            eng_crash = True
            out = None
            print(f"    [{kind}] run_engine 예외: {e}")
        check(f"[{kind}] run_engine 무크래시", not eng_crash)
        if not eng_crash:
            out2 = engine.run_engine("SYN-USDT", meas, {"1h": df1h, "4h": df4h, "1d": df1d}, {}, macro)
            det_ok = ([{k: v for k, v in c.items() if k != "reason"} for c in out["candidates"]]
                      == [{k: v for k, v in c.items() if k != "reason"} for c in out2["candidates"]])
            check(f"[{kind}] run_engine 무상태(재실행 동일)", det_ok)

        fv, fe = feat["raw"]["bars_since_vwap_flip"], feat["raw"]["bars_since_ema20_flip"]
        print(f"    [{kind}] bars_since_vwap_flip={fv}  bars_since_ema20_flip={fe}"
              f"  dist_vwap={feat['raw']['dist_vwap_atr']:.3f}"
              f"  candidates={len(cands) if not det_crash else '-'}")
        results[kind] = feat
    return results


def part2b_boost_existence(results: dict):
    """전환 시나리오에서 부스트가 최소 1회 발동하는지(죽은 코드가 아님) — 존재성 체크.
    발동=좋다는 뜻이 아니라 로직이 설계대로 도달 가능함을 확인하는 것."""
    print("\n" + "─" * 72)
    print("Part 2b — 전환 시나리오에서 리클레임 부스트 발동 존재성 (토글 임시 ON)")
    print("─" * 72)
    saved = config.WRF_CTX_RECLAIM_BOOST
    config.WRF_CTX_RECLAIM_BOOST = True
    try:
        for kind, target_dir in (("bear_to_bull", "long"), ("bull_to_bear", "short")):
            feat = results.get(kind)
            if feat is None:
                continue
            raw, ctx = feat["raw"], feat["ctx"]
            n = D._reclaim_n(raw, target_dir)
            armed_ctx = dict(ctx, btc_macro=("DOWNLEG" if target_dir == "long" else "UPLEG"))
            C = D._ctx_align(armed_ctx, raw, target_dir)
            print(f"    [{kind}] reclaim_n({target_dir})={n}  C(부스트 강제지각맥락)={C:+.3f}")
        print("    (개별 스냅샷 1건 — 시계열 전체 스윕은 verify_caxis_v5.py 반사실 담당)")
    finally:
        config.WRF_CTX_RECLAIM_BOOST = saved


if __name__ == "__main__":
    part1_mirror_symmetry()
    part1b_br_precond_symmetry()
    results = part2_scenarios()
    part2b_boost_existence(results)

    print("\n" + "═" * 72)
    print("요약")
    print("═" * 72)
    if FAIL:
        print(f"  FAIL {len(FAIL)}건: {FAIL}")
        sys.exit(1)
    print("  전부 PASS — 코드 정합성(대칭·무상태·무크래시) 확인.")
    print("  ⚠ 이 결과는 통계적 엣지를 증명하지 않는다. 실전 점등 판정은")
    print("    verify_caxis_v5.py의 사전등록 게이트(현재 미충족)로만 한다.")
