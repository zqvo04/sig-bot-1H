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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_dataset import _entry_ref, fwd_ret, mfe_mae, path_efficiency  # noqa: E402

_HORIZONS = (4, 12, 24, 48, 72)
_DEAD_ZONE = 0.005  # exret 데드존 ±0.5% → FLAT (베타 잡음 흡수)


def triple_barrier(path: dict, direction: str, sl_frac: float, tp_frac: float,
                   t_max: int, sl_priority: bool = True) -> dict:
    """배리어 재생: TP/SL/타임스톱. 반환 {outcome, exit_h, r_multiple, tb_win}.

    outcome ∈ {WIN, LOSS, TIMEOUT}. tb_win = 1(WIN)/0(LOSS)/None(TIMEOUT=스크래치).
    sl_frac·tp_frac = 진입가 대비 양수 거리(비율). t_max = 최대 보유 캔들 수.
    경로 미성숙(t_max 이전에 미터치 & 경로 미완성)이면 None 반환.
    """
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
    """
    import pandas as pd

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
            tb = triple_barrier(path, c["dir"], sl_frac, tp_frac,
                                c.get("t_max", 48), sl_priority)
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
                "fire": c.get("fire"), "veto_n": len(c.get("veto") or []),
                "tb_win": (tb or {}).get("tb_win"),
                "tb_outcome": (tb or {}).get("outcome"),
                "tb_exit_h": (tb or {}).get("exit_h"),
                "exret_24h": ex24, "class": cls,
                "mfe": mfe, "mae": mae, "path_eff": peff,
                "path_complete": bool(path.get("complete")),
            })
    df = pd.DataFrame(recs)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df = df.sort_values("ts").reset_index(drop=True)
    return df
