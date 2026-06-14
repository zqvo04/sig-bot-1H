"""
build_dataset.py — 학습 데이터 로더 & 파생 라벨 (오프라인 전용)
────────────────────────────────────────────────────────────────────
data/research/{SYMBOL}/{YYYY-MM}.jsonl 의 상태 스냅샷 + 72h 경로를
평탄한 pandas DataFrame으로 변환하고, 경로(path)에서 라벨을 사후 파생한다.

설계 원칙(LEARNING_DATA_DESIGN.md):
  · 라벨은 수집 시 박제하지 않고 여기서 경로로부터 계산 → 정의를 바꿔도 재수집 불필요
  · 피처는 점수 산출 이전의 원시 지표(L1)만. 봇 점수/임계값(meta)은 참고용으로만 로드
  · 절대가 금지: 경로는 기준가 p0 대비 상대변화율(o/c/h/l), ATR 단위 변환은 atr_pct로

경로 포맷(v2): path = {n, o[], c[], h[], l[], complete, ...}
  · o[0] = '다음 봉 시가' 상대값 → 현실적 진입 체결 기준(P2)
  · 구버전(o 없음)도 안전 처리: 진입 기준 p0(=봉 close)로 폴백

CLI:
  python analysis/build_dataset.py                # 요약 출력
  python analysis/build_dataset.py --out ds.parquet
  python analysis/build_dataset.py --min-n 24     # 경로 24캔들 이상만
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from typing import Iterable, Optional

import pandas as pd

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DEFAULT_DIR = os.path.join(_ROOT, "data", "research")


# ════════════════════════════════════════════════════════════════════
# 로드
# ════════════════════════════════════════════════════════════════════

def load_snapshots(data_dir: str = _DEFAULT_DIR,
                   symbols: Optional[Iterable[str]] = None) -> list[dict]:
    """JSONL 전체를 dict 리스트로 로드. symbols=None이면 모든 심볼."""
    rows: list[dict] = []
    for fp in sorted(glob.glob(os.path.join(data_dir, "*", "*.jsonl"))):
        sym_slug = os.path.basename(os.path.dirname(fp))
        if symbols and sym_slug not in {s.replace("/", "-") for s in symbols}:
            continue
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


# ════════════════════════════════════════════════════════════════════
# 경로 → 파생 라벨
# ════════════════════════════════════════════════════════════════════

def _entry_ref(path: dict) -> float:
    """현실적 진입 기준(상대값). 다음 봉 시가 o[0]가 있으면 그것, 없으면 0(=p0)."""
    o = path.get("o")
    if o:
        return float(o[0])
    return 0.0


def fwd_ret(path: dict, h: int, realistic: bool = True) -> Optional[float]:
    """진입 후 h시간 종가 수익률. realistic=True면 다음 봉 시가 진입 기준."""
    c = path.get("c") or []
    if len(c) < h:
        return None
    close_rel = c[h - 1]
    if realistic:
        e = _entry_ref(path)
        return (1.0 + close_rel) / (1.0 + e) - 1.0
    return close_rel


def mfe_mae(path: dict, k: Optional[int] = None, realistic: bool = True):
    """첫 k캔들 구간의 최대유리(MFE)·최대불리(MAE) 변동. (long 관점 부호)."""
    h = path.get("h") or []
    l = path.get("l") or []
    if not h or not l:
        return None, None
    if k:
        h, l = h[:k], l[:k]
    e = _entry_ref(path) if realistic else 0.0
    mfe = (1.0 + max(h)) / (1.0 + e) - 1.0
    mae = (1.0 + min(l)) / (1.0 + e) - 1.0
    return mfe, mae


def time_to_extreme(path: dict):
    """고점/저점 도달 시간(캔들 수, 1-indexed)."""
    h = path.get("h") or []
    l = path.get("l") or []
    tt_peak = (h.index(max(h)) + 1) if h else None
    tt_trough = (l.index(min(l)) + 1) if l else None
    return tt_peak, tt_trough


def path_efficiency(path: dict) -> Optional[float]:
    """경로 효율 |순이동| / Σ|구간변화|. 1=일방향, 0=왕복."""
    c = path.get("c") or []
    if len(c) < 2:
        return None
    travel = sum(abs(c[i] - c[i - 1]) for i in range(1, len(c))) + abs(c[0])
    return abs(c[-1]) / travel if travel > 0 else None


def simulate_tp_sl(path: dict, direction: str, sl: float, tp: float,
                   sl_priority: bool = True) -> Optional[dict]:
    """경로 위에서 TP/SL 재생. sl/tp는 진입가 대비 양수 거리(비율, 예 0.02=2%).

    진입가 = 다음 봉 시가(o[0]) 기준. 반환: {result, exit_h, r_multiple} 또는 None(미성숙).
    """
    o = path.get("o") or []
    h = path.get("h") or []
    l = path.get("l") or []
    c = path.get("c") or []
    if not c:
        return None
    e = _entry_ref(path)               # 진입 상대값(p0 대비)
    base = 1.0 + e                      # 진입 절대비
    long = direction.lower() == "long"
    tp_lvl = base * (1 + tp) if long else base * (1 - tp)
    sl_lvl = base * (1 - sl) if long else base * (1 + sl)
    n = len(c)
    for i in range(n):
        hi = 1.0 + (h[i] if i < len(h) else c[i])
        lo = 1.0 + (l[i] if i < len(l) else c[i])
        sl_hit = (lo <= sl_lvl) if long else (hi >= sl_lvl)
        tp_hit = (hi >= tp_lvl) if long else (lo <= tp_lvl)
        if sl_hit and tp_hit:
            return {"result": "LOSS" if sl_priority else "WIN",
                    "exit_h": i + 1, "r_multiple": -1.0 if sl_priority else tp / sl}
        if sl_hit:
            return {"result": "LOSS", "exit_h": i + 1, "r_multiple": -1.0}
        if tp_hit:
            return {"result": "WIN", "exit_h": i + 1, "r_multiple": tp / sl}
    # 미터치 → 경로가 완성(complete)이면 만기 청산, 아니면 미성숙
    if not path.get("complete"):
        return None
    exit_rel = c[-1]
    realized = (1.0 + exit_rel) / base - 1.0
    if not long:
        realized = -realized
    return {"result": "WIN" if realized >= 0 else "LOSS",
            "exit_h": n, "r_multiple": realized / sl if sl > 0 else 0.0}


# ════════════════════════════════════════════════════════════════════
# 평탄 DataFrame
# ════════════════════════════════════════════════════════════════════

# 파생 라벨로 채울 표준 호라이즌(시간)
_LABEL_HORIZONS = (4, 12, 24, 48, 72)


def to_dataframe(rows: list[dict], min_n: int = 4,
                 require_path: bool = False) -> pd.DataFrame:
    """스냅샷 dict 리스트 → 평탄 DataFrame (피처 + 지문 + 파생 라벨).

    min_n: 경로 캔들 수가 이 미만이면 라벨은 NaN(피처는 유지).
    require_path: True면 사용 가능한 경로(n>=min_n) 행만 남김.
    """
    recs = []
    for r in rows:
        rec = {
            "snapshot_id": r.get("snapshot_id"),
            "ts": r.get("ts"),
            "symbol": r.get("symbol"),
            "feature_version": r.get("feature_version"),
            "p0": r.get("p0"),
        }
        # L1 피처
        for k, v in (r.get("f") or {}).items():
            rec[f"f_{k}"] = v
        # L2 지문
        for k, v in (r.get("fp") or {}).items():
            rec[f"fp_{k}"] = v
        # L3 참고 메타(학습 입력 아님 — 봇 로직 대조용)
        for k, v in (r.get("meta") or {}).items():
            if isinstance(v, (int, float, str, bool)) or v is None:
                rec[f"meta_{k}"] = v

        path = r.get("path")
        n = (path or {}).get("n", 0) if path else 0
        rec["path_n"] = n
        rec["path_complete"] = bool((path or {}).get("complete")) if path else False
        rec["path_expired"] = bool((path or {}).get("expired")) if path else False

        if path and n >= min_n and not path.get("expired"):
            for hh in _LABEL_HORIZONS:
                rec[f"ret_{hh}h"] = fwd_ret(path, hh, realistic=True)
            mfe72, mae72 = mfe_mae(path, k=72)
            rec["mfe_72h"], rec["mae_72h"] = mfe72, mae72
            mfe6, mae6 = mfe_mae(path, k=6)
            rec["mfe_6h"], rec["mae_6h"] = mfe6, mae6   # 진입 직후 6h(빠른 손절 진단)
            ttp, ttt = time_to_extreme(path)
            rec["tt_peak"], rec["tt_trough"] = ttp, ttt
            rec["path_eff"] = path_efficiency(path)
            atr = (r.get("f") or {}).get("atr_pct")
            if atr:
                r24 = rec.get("ret_24h")
                rec["ret_24h_atr"] = (r24 * 100.0 / atr) if r24 is not None else None
        elif require_path:
            continue
        recs.append(rec)

    df = pd.DataFrame(recs)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df = df.sort_values("ts").reset_index(drop=True)
    return df


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════

def _summary(df: pd.DataFrame) -> str:
    if df.empty:
        return "표본 0건 — data/research 에 스냅샷이 없습니다."
    lines = [
        f"총 스냅샷            : {len(df):,}행",
        f"심볼                : {dict(df['symbol'].value_counts())}",
        f"기간                : {df['ts'].min()} ~ {df['ts'].max()}",
        f"feature_version     : {sorted(df['feature_version'].dropna().unique().tolist())}",
        f"경로 캡처(부분+완성): {(df['path_n'] > 0).sum():,}행",
        f"경로 완성(72h)      : {df['path_complete'].sum():,}행",
        f"경로 유실(expired)  : {df['path_expired'].sum():,}행",
    ]
    if "ret_24h" in df and df["ret_24h"].notna().any():
        lab = df[df["ret_24h"].notna()]
        lines += [
            "",
            f"라벨 가능 표본      : {len(lab):,}행 (ret_24h 산출 가능)",
            f"24h 수익률 중앙값   : {lab['ret_24h'].median() * 100:+.2f}%",
            f"24h MFE/MAE 중앙값  : "
            f"{lab['mfe_72h'].median() * 100:+.2f}% / {lab['mae_72h'].median() * 100:+.2f}%",
        ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="학습 데이터 로더 & 요약")
    ap.add_argument("--dir", default=_DEFAULT_DIR, help="research 데이터 디렉터리")
    ap.add_argument("--min-n", type=int, default=4, help="라벨 산출 최소 경로 캔들 수")
    ap.add_argument("--require-path", action="store_true", help="경로 있는 행만")
    ap.add_argument("--out", help="저장 경로(.parquet/.csv)")
    args = ap.parse_args()

    rows = load_snapshots(args.dir)
    df = to_dataframe(rows, min_n=args.min_n, require_path=args.require_path)
    print(_summary(df))
    if args.out:
        if args.out.endswith(".parquet"):
            df.to_parquet(args.out, index=False)
        else:
            df.to_csv(args.out, index=False)
        print(f"\n저장: {args.out} ({len(df):,}행 × {len(df.columns)}열)")


if __name__ == "__main__":
    main()
