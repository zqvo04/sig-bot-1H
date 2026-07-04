"""오프라인 파생 라벨 카탈로그 (schema v3).

경로(path)에서 라벨을 파생한다 — 수집 시 박제하지 않는다.
  · tb_win[setup]  : 후보 tp/sl/t_max로 triple-barrier 재생 = 승률 정답
  · ret_Hh / exret_Hh : 원시수익 / BTC초과수익(베타둔감 1차 라벨)
  · mfe_k / mae_k  : 경로형 최대유리/최대불리
  · path_eff       : 경로 효율
  · class          : 초과수익·데드존 기준 방향중립 분류(UP/FLAT/DOWN)

triple-barrier·exret(BTC초과)가 1차 라벨(비정상성 함정 차단). 원시수익은 보조.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_dataset import _entry_ref, fwd_ret, mfe_mae, path_efficiency  # noqa: E402

try:  # 임계 일관성(calibrate 경유 시 src 가 sys.path 에 있음). 부재 시 기본값.
    import config
except ImportError:  # pragma: no cover
    config = None

_HORIZONS = (4, 12, 24, 48, 72)
_DEAD_ZONE = 0.005  # exret 데드존 ±0.5% → FLAT (베타 잡음 흡수)


def _cfg(name: str, default):
    return getattr(config, name, default) if config is not None else default


def _recon_pctb_map(rows: list) -> dict:
    """path에서 완성봉 종가를 복원해 심볼별 %b 시계열을 만든다 → {(symbol, ts): %b}.

    행 ts=T의 path는 'T 이후' 봉들의 상대값(o/c/h/l ÷ p0)이므로
      close(봉 K) = p0(행 K−1h) × (1 + c[0](행 K−1h))
    가 완성봉 종가의 정확한 복원이다(경로는 완성 후 재캡처돼 최종값). 여기에 라이브
    `_bb_pctb_prev`와 동일한 rolling(period).mean/std(ddof=1)로 %b를 계산한다.
    ★ 직전 행의 raw.bb_pctb를 그대로 쓰면 안 된다 — 그 값은 봉 형성 초기(:05)
    스냅샷이라 완성봉 %b와 다르다(라이브 발화 19건 대조: 복원 19/19 일치·기록값 5건 불일치).
    """
    period = _cfg("BOLLINGER_PERIOD", 20)
    std = _cfg("BOLLINGER_STD", 2.0)
    by_sym: dict = {}
    for r in rows:
        path, p0 = r.get("path") or {}, r.get("p0")
        c = path.get("c") or []
        ts = pd.to_datetime(r.get("ts"), utc=True, errors="coerce")
        if c and p0 and ts is not None and not pd.isna(ts):
            by_sym.setdefault(r.get("symbol"), {})[ts + timedelta(hours=1)] = \
                float(p0) * (1.0 + float(c[0]))
    out = {}
    for sym, closes in by_sym.items():
        s = pd.Series(closes).sort_index()
        if len(s) < period:
            continue
        mid = s.rolling(period).mean()
        sd = s.rolling(period).std()
        lower = mid - std * sd
        rng = (mid + std * sd) - lower
        pb = (s - lower) / rng.replace(0, float("nan"))
        for ts, v in pb.items():
            if v == v:  # NaN 가드
                out[(sym, ts)] = float(v)
    return out


def split_band_reversal(rows: list) -> list:
    """[Phase A] 소급 재분류 — 과거 JSONL의 밴드반전 후보(setup='RV')를 setup='BR'로.

    JSONL 후보에는 디텍터 출처(reason)가 저장되지 않아, 밴드반전의 무장조건(직전
    완성봉 %b 밴드 외곽 → 현재봉 밴드 안 복귀; 직전 %b 부재 시 밴드터치 폴백 —
    라이브 `_detect_band_reversal`과 동일)을 재유도해 판별한다.
      · 직전 완성봉 %b는 path 복원(_recon_pctb_map)이 1차, 직전 행 raw.bb_pctb가
        2차 폴백(복원 불가 구간), 둘 다 없으면 밴드터치 폴백(라이브와 동일).
      · setup='BR' 후보가 이미 있는 행(셋업 분리 후 적재분)은 원본이 권위 — 건너뜀.
        (분리 후에는 무장 ∧ RV허용레짐 ⟹ BR 후보가 반드시 존재하므로 안전.)
      · 무장 시 해당 방향 RV 후보 중 '마지막' 것이 밴드반전 — 디텍터 실행 순서
        (_detect_rv → _detect_band_reversal)가 candidates 배열에 보존되기 때문.
      · 멱등(재적용 무해)·원본 파일 불변(메모리 재라벨만). 라이브 경로는 이 함수를
        호출하지 않는다(candidate_dataset 전용).
    검증(2026-07): 라이브 발화 26건 대조 — JSONL에 후보가 기록된 21건 전부 일치
    (BR 16 / RV 4 / MR 1), 나머지 5건은 동시각 재실행 멱등충돌로 후보 자체가 미적재.
    """
    bb_hi = _cfg("WRF_D_BBPCTB_HI", 0.80)
    bb_lo = _cfg("WRF_D_BBPCTB_LO", 0.20)
    require_re = _cfg("WRF_D_REQUIRE_REENTRY", True)

    recon = _recon_pctb_map(rows)
    # 2차 폴백: (symbol, ts) → 기록된 raw.bb_pctb (형성 초기값 — 복원 불가 시에만)
    bb_map = {}
    for r in rows:
        ts = pd.to_datetime(r.get("ts"), utc=True, errors="coerce")
        bb = (r.get("raw") or {}).get("bb_pctb")
        if ts is not None and not pd.isna(ts) and bb is not None:
            bb_map[(r.get("symbol"), ts)] = float(bb)

    for r in rows:
        cands = r.get("candidates") or []
        if not cands or any(c.get("setup") == "BR" for c in cands):
            continue
        cur = (r.get("raw") or {}).get("bb_pctb")
        if cur is None:
            continue
        cur = float(cur)
        ts = pd.to_datetime(r.get("ts"), utc=True, errors="coerce")
        prev = None
        if ts is not None and not pd.isna(ts):
            key = (r.get("symbol"), ts - timedelta(hours=1))
            prev = recon.get(key, bb_map.get(key))
        use_re = require_re and prev is not None
        armed = {
            "short": (prev >= bb_hi and cur < bb_hi) if use_re else (cur >= bb_hi),
            "long": (prev <= bb_lo and cur > bb_lo) if use_re else (cur <= bb_lo),
        }
        for direction, is_armed in armed.items():
            if not is_armed:
                continue
            rvs = [c for c in cands
                   if c.get("setup") == "RV" and c.get("dir") == direction]
            if rvs:
                rvs[-1]["setup"] = "BR"
    return rows


def _trailing_barrier(path: dict, direction: str, sl_frac: float, trail_frac: float,
                      t_max: int) -> dict:
    """[P2] 무상태 트레일링 익절 재생 — 고정 TP 대신 HWM∓trail_frac 샹들리에 스톱.

    초기 스톱=진입∓sl_frac, 이후 유리방향 HWM에서 trail_frac 거리로 단조 상향(롱)/하향(숏).
    청산 R = (청산가−진입)/sl_frac(리스크 1단위). outcome: WIN(양수잠금)/LOSS(초기스톱 이하)/
    TIMEOUT(t_max 실현). levels.py WRF_TF_TRAIL과 동일 규칙 → 라이브(주석)·오프라인(채점) 정합."""
    h = path.get("h") or []
    l = path.get("l") or []
    c = path.get("c") or []
    if not c or sl_frac <= 0 or trail_frac <= 0:
        return None
    base = 1.0 + _entry_ref(path)
    long = direction.lower() == "long"
    n = min(len(c), int(t_max))
    init_stop = base * (1 - sl_frac) if long else base * (1 + sl_frac)
    stop = init_stop
    hwm = base                       # 유리방향 극값(롱=고점/숏=저점)
    for i in range(n):
        hi = 1.0 + (h[i] if i < len(h) else c[i])
        lo = 1.0 + (l[i] if i < len(l) else c[i])
        if long:
            hwm = max(hwm, hi)
            stop = max(stop, hwm - trail_frac * base)   # 단조 상향(래칫)
            if lo <= stop:
                r = (stop / base - 1.0) / sl_frac
                return {"outcome": "WIN" if r > 0 else "LOSS", "exit_h": i + 1,
                        "r_multiple": r, "tb_win": 1 if r > 0 else 0}
        else:
            hwm = min(hwm, lo)
            stop = min(stop, hwm + trail_frac * base)    # 단조 하향(래칫)
            if hi >= stop:
                r = (1.0 - stop / base) / sl_frac
                return {"outcome": "WIN" if r > 0 else "LOSS", "exit_h": i + 1,
                        "r_multiple": r, "tb_win": 1 if r > 0 else 0}
    if len(c) < n:
        return None
    if not path.get("complete") and len(c) < int(t_max):
        return None
    exit_rel = c[n - 1]
    realized = (1.0 + exit_rel) / base - 1.0
    if not long:
        realized = -realized
    return {"outcome": "TIMEOUT", "exit_h": n,
            "r_multiple": realized / sl_frac if sl_frac > 0 else 0.0, "tb_win": None}


def triple_barrier(path: dict, direction: str, sl_frac: float, tp_frac: float,
                   t_max: int, sl_priority: bool = True,
                   trail_frac: float = None) -> dict:
    """배리어 재생: TP/SL/타임스톱. 반환 {outcome, exit_h, r_multiple, tb_win}.

    outcome ∈ {WIN, LOSS, TIMEOUT}. tb_win = 1(WIN)/0(LOSS)/None(TIMEOUT=스크래치).
    sl_frac·tp_frac = 진입가 대비 양수 거리(비율). t_max = 최대 보유 캔들 수.
    경로 미성숙(t_max 이전에 미터치 & 경로 미완성)이면 None 반환.
    [P2] trail_frac(>0) 지정 시 고정 TP 대신 트레일링(_trailing_barrier)으로 채점.
    """
    if trail_frac is not None and trail_frac > 0:
        return _trailing_barrier(path, direction, sl_frac, trail_frac, t_max)
    o = path.get("o") or []
    h = path.get("h") or []
    l = path.get("l") or []
    c = path.get("c") or []
    if not c or sl_frac <= 0 or tp_frac <= 0:
        return None
    e = _entry_ref(path)
    base = 1.0 + e
    long = direction.lower() == "long"
    tp_lvl = base * (1 + tp_frac) if long else base * (1 - tp_frac)
    sl_lvl = base * (1 - sl_frac) if long else base * (1 + sl_frac)
    n = min(len(c), int(t_max))
    for i in range(n):
        hi = 1.0 + (h[i] if i < len(h) else c[i])
        lo = 1.0 + (l[i] if i < len(l) else c[i])
        sl_hit = (lo <= sl_lvl) if long else (hi >= sl_lvl)
        tp_hit = (hi >= tp_lvl) if long else (lo <= tp_lvl)
        if sl_hit and tp_hit:
            win = (not sl_priority)
            return {"outcome": "WIN" if win else "LOSS", "exit_h": i + 1,
                    "r_multiple": (tp_frac / sl_frac) if win else -1.0,
                    "tb_win": 1 if win else 0}
        if sl_hit:
            return {"outcome": "LOSS", "exit_h": i + 1, "r_multiple": -1.0, "tb_win": 0}
        if tp_hit:
            return {"outcome": "WIN", "exit_h": i + 1,
                    "r_multiple": tp_frac / sl_frac, "tb_win": 1}
    # t_max 도달 — 타임스톱. 경로가 t_max만큼 확보됐는가?
    if len(c) < n:
        return None  # 아직 t_max 미성숙
    if not path.get("complete") and len(c) < int(t_max):
        return None
    exit_rel = c[n - 1]
    realized = (1.0 + exit_rel) / base - 1.0
    if not long:
        realized = -realized
    return {"outcome": "TIMEOUT", "exit_h": n,
            "r_multiple": realized / sl_frac if sl_frac > 0 else 0.0, "tb_win": None}


def build_btc_ret_map(rows: list) -> dict:
    """BTC 행에서 {ts → {h: ret_h}} 맵을 만들어 exret(초과수익) 계산에 쓴다."""
    m = {}
    for r in rows:
        if r.get("symbol") != "BTC/USDT":
            continue
        path = r.get("path")
        if not path or not path.get("c"):
            continue
        m[r.get("ts")] = {h: fwd_ret(path, h, realistic=True) for h in _HORIZONS}
    return m


def exret(path: dict, ts: str, btc_map: dict, h: int) -> float:
    """BTC초과수익 = ret_h(symbol) − ret_h(BTC@동일ts). BTC 없으면 원시수익."""
    r = fwd_ret(path, h, realistic=True)
    if r is None:
        return None
    b = (btc_map.get(ts) or {}).get(h)
    return r - b if b is not None else r


def classify(exret_24h: float) -> str:
    """방향중립 클래스: exret 데드존 기준 UP/FLAT/DOWN."""
    if exret_24h is None:
        return None
    if exret_24h > _DEAD_ZONE:
        return "UP"
    if exret_24h < -_DEAD_ZONE:
        return "DOWN"
    return "FLAT"


def candidate_dataset(rows: list, sl_priority: bool = True):
    """v3 행 → 후보 단위 long-format 라벨 테이블 (calibrate/situation_report 입력).

    각 후보 1행: setup·dir·regime·btc_macro·C·L·F·p_hat·p_source·fire +
    파생라벨(tb_win·tb_outcome·exret_24h·class·mfe/mae·path_eff). 경로 없는 행 skip.
    [Phase A] 밴드반전 소급 재분류(RV→BR)를 먼저 적용 — 모든 오프라인 소비자
    (calibrate/backtest/situation_report)가 이 함수를 거치므로 단일 지점에서 일관.
    """
    rows = split_band_reversal(rows)
    btc_map = build_btc_ret_map(rows)
    recs = []
    for r in rows:
        if int(r.get("schema_version", 0)) < 3:
            continue  # v3 후보 스키마만
        path = r.get("path")
        if not path or not path.get("c"):
            continue
        ctx = r.get("ctx") or {}
        ts = r.get("ts")
        ex24 = exret(path, ts, btc_map, 24)
        cls = classify(ex24)
        peff = path_efficiency(path)
        for c in r.get("candidates", []):
            entry, tp, sl = c.get("entry"), c.get("tp"), c.get("sl")
            if not entry or not tp or not sl:
                continue
            long = c.get("dir") == "long"
            sl_frac = abs(entry - sl) / entry
            tp_frac = abs(tp - entry) / entry
            # [P2] 후보에 trail_dist가 실리면(WRF_TF_TRAIL) 트레일링으로 채점(고정 TP 무시)
            td = c.get("trail_dist")
            trail_frac = (abs(float(td)) / entry) if td else None
            tb = triple_barrier(path, c["dir"], sl_frac, tp_frac,
                                c.get("t_max", 48), sl_priority, trail_frac=trail_frac)
            mfe, mae = mfe_mae(path, k=c.get("t_max", 48))
            recs.append({
                "snapshot_id": r.get("snapshot_id"), "ts": ts, "symbol": r.get("symbol"),
                "setup": c.get("setup"), "dir": c.get("dir"),
                "regime_1h": ctx.get("regime_1h"), "regime_4h": ctx.get("regime_4h"),
                "bias_1d": ctx.get("bias_1d"), "btc_macro": ctx.get("btc_macro"),
                "fp_key": ctx.get("fp_key"),
                "cell": f"{c.get('setup')}|{ctx.get('regime_1h')}|{ctx.get('btc_macro')}",
                "C": c.get("C"), "L": c.get("L"), "F": c.get("F"),
                "confluence_n": c.get("confluence_n"),
                "p_hat": c.get("p_hat"), "p_source": c.get("p_source"),
                "p_prior": c.get("p_prior"), "p_cal": c.get("p_cal"),
                "p_cal_source": c.get("p_cal_source"),
                "win_floor": c.get("win_floor"), "rr": c.get("rr"),
                "fire": c.get("fire"), "veto_n": len(c.get("veto") or []),
                "quarantine_n": len(c.get("quarantine") or []),
                "tb_win": (tb or {}).get("tb_win"),
                "tb_outcome": (tb or {}).get("outcome"),
                "tb_exit_h": (tb or {}).get("exit_h"),
                "tb_r": (tb or {}).get("r_multiple"),
                "exret_24h": ex24, "class": cls,
                "mfe": mfe, "mae": mae, "path_eff": peff,
                "path_complete": bool(path.get("complete")),
            })
    df = pd.DataFrame(recs)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df = df.sort_values("ts").reset_index(drop=True)
    return df
