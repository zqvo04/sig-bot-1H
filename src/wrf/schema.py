"""schema v3 — 매시간 학습데이터 1행 빌더 (JSONL).

한 시간 = 1행. 라벨은 박제하지 않고 경로에서 오프라인 파생. 멱등키 =
symbol + 봉시각. path는 처음 null, 4h부터 증분, 72h 완성 시 complete=true.

row = {snapshot_id, ts, symbol, schema_version, p0, raw, ctx, candidates[], meta, path,
       [bars, pct]}  # bars/pct = 진입직전 캔들 윈도 + 백분위(옵션·precond 재실행용)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import config
except ImportError:  # pragma: no cover
    from src import config  # type: ignore


def _backward_bars(feat: dict) -> dict | None:
    """진입직전 1H 캔들 윈도(백워드)를 compact 상대포맷으로 인코딩.

    ohlc = p0(마지막 종가) 대비 비율, v = 윈도 평균 대비 비율(전역 스케일 상쇄 →
    vol/baseline·rev_vol 같은 '비율' 연산이 정확히 보존되며 컴팩트). 오프라인에서
    df_1h를 복원해 디텍터/precond를 재실행할 수 있게 한다. path(전방)는 거래량을
    저장하지 않으므로 이 윈도가 거래량 게이트 재현의 유일한 소스다.
    토글 OFF·데이터 부족·예외 시 None(스냅샷은 정상 기록 — 격리·안전)."""
    try:
        if not getattr(config, "WRF_RESEARCH_BARS", True):
            return None
        df = (feat or {}).get("df_1h")
        if df is None or len(df) == 0:
            return None
        n = int(getattr(config, "WRF_RESEARCH_BARS_N", 120))
        seg = df.iloc[-n:] if n > 0 else df
        p0 = float(seg["close"].iloc[-1])
        if not (p0 > 0):
            return None
        rnd = int(getattr(config, "RESEARCH_PATH_ROUND", 6))

        def rel(col):
            return [round(float(x) / p0 - 1.0, rnd) for x in seg[col].values]

        vmean = float(seg["volume"].mean()) if "volume" in seg else 0.0
        v = ([round(float(x) / vmean, 3) for x in seg["volume"].values]
             if vmean > 0 else [])
        return {"n": int(len(seg)), "o": rel("open"), "h": rel("high"),
                "l": rel("low"), "c": rel("close"), "v": v}
    except Exception as e:  # pragma: no cover
        logger.warning(f"[schema] 백워드 캔들 인코딩 실패(격리): {e}")
        return None


def build_row(engine_out: dict, legacy_meta: dict = None) -> dict:
    """engine 출력 → schema v3 JSONL 행. legacy_meta는 대조용(학습 입력 아님)."""
    symbol = engine_out["symbol"]
    ts = engine_out["ts"]
    candidates = [
        {
            "setup": c["setup"], "dir": c["dir"], "precond": c["precond"],
            "entry": c["entry"], "tp": c["tp"], "sl": c["sl"],
            "r_dist": c["r_dist"], "rr": c["rr"], "t_max": c["t_max"],
            "p_hat": c["p_hat"], "p_source": c["p_source"],
            "p_prior": c.get("p_prior"), "p_cal": c.get("p_cal"),
            "p_cal_source": c.get("p_cal_source"),
            "C": c["C"], "L": c["L"], "F": c["F"],
            "confluence_n": c["confluence_n"], "veto": c["veto"],
            "size": c["size"], "fire": c["fire"],
            "shadow_band": c.get("shadow_band", False),
            "quarantine": c.get("quarantine", []),
        }
        for c in engine_out.get("candidates", [])
    ]
    row = {
        "snapshot_id": f"{symbol}_{ts}",
        "ts": ts,
        "symbol": symbol,
        "schema_version": getattr(config, "WRF_SCHEMA_VERSION", 3),
        "p0": engine_out["p0"],
        "raw": engine_out["raw"],
        "ctx": engine_out["ctx"],
        "candidates": candidates,
        "meta": legacy_meta or {},
        "path": None,
    }
    # [테제B 검증 인프라] 진입직전 캔들 윈도 + 그 시점 pct 백분위(옵션·하위호환).
    # 오프라인에서 디텍터/precond를 재실행해 검증하기 위한 입력(발사 로직 무관).
    bars = _backward_bars(engine_out.get("feat"))
    if bars is not None:
        row["bars"] = bars
        row["pct"] = engine_out.get("pct") or {}
    return row
