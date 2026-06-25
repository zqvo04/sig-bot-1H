"""schema v3 — 매시간 학습데이터 1행 빌더 (JSONL).

한 시간 = 1행. 라벨은 박제하지 않고 경로에서 오프라인 파생. 멱등키 =
symbol + 봉시각. path는 처음 null, 4h부터 증분, 72h 완성 시 complete=true.

row = {snapshot_id, ts, symbol, schema_version, p0, raw, ctx, candidates[], meta, path}
"""
from __future__ import annotations

try:
    import config
except ImportError:  # pragma: no cover
    from src import config  # type: ignore


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
        }
        for c in engine_out.get("candidates", [])
    ]
    return {
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
