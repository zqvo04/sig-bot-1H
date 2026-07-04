"""C축 V5 설계 예비 프로브 — 탐색적 가설 생성 전용 (판정 하니스 아님).

docs/CAXIS_V5_DESIGN.md §3 수치의 재현 스크립트. 저장 스냅샷의 raw만으로
(무상태 재현 가능 필드) 리클레임 증거의 라벨-프리 방향 지속성을 잰다.

  Q1. 반전(MR/RV/BR) 후보의 저장 C 분포 — v1 포화 실측
  Q2. reclaim_n≥2 '상태' vs '신선 플립 이벤트' vs '이벤트+선행 반대레그'의
      h시간 후 방향적중(롱/숏 분리 — 단일레짐 베타 오염 감시)
  Q3. 부스트 활성 구간(reclaim≥2 ∧ slow구조 반대) 빈도

경고: 단일레짐(UPLEG 0) 표본의 다중조회다. 여기 수치로 채택 판정하지 않는다 —
판정은 사전등록 하니스(verify_caxis_v5.py, 설계 문서 §6)로만.

CLI: python analysis/audit/probe_caxis_v5.py
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

H = [12, 24, 48]


def load_rows() -> list:
    rows = []
    for fp in sorted(glob.glob(os.path.join(_ROOT, "data", "research", "*", "*.jsonl"))):
        for line in open(fp, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
            except json.JSONDecodeError:
                continue
            if s.get("schema_version") == 3 and s.get("raw") and s.get("p0"):
                rows.append(s)
    return rows


def reclaim_n(raw: dict, direction: str) -> int:
    """detectors._reclaim_n 재현(raw-only)."""
    sgn = 1 if direction == "long" else -1
    struct = (raw.get("bos") == sgn or raw.get("choch") == sgn
              or raw.get("bos_4h") == sgn or raw.get("choch_4h") == sgn)
    dv = raw.get("dist_vwap_atr")
    vwap = (dv is not None) and ((dv > 0) if sgn > 0 else (dv < 0))
    ema = raw.get("ema") == sgn
    return int(bool(struct)) + int(bool(vwap)) + int(bool(ema))


def slow_align(ctx: dict, raw: dict) -> float:
    """_ctx_struct_align 구가중(P1 제외) 재현."""
    m = {"UPLEG": 1.0, "DOWNLEG": -1.0, "CHOP": 0.0}.get((ctx or {}).get("btc_macro") or "CHOP", 0.0)
    b = {"BULL": 1.0, "BEAR": -1.0, "NEUTRAL": 0.0}.get((ctx or {}).get("bias_1d") or "NEUTRAL", 0.0)
    return (0.45 * m + 0.25 * b + 0.20 * float(raw.get("ema_4h") or 0)
            + 0.10 * float(raw.get("ema_1d_struct") or 0))


def _by_symbol(rows):
    by_sym = defaultdict(dict)
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (ValueError, TypeError):
            continue
        by_sym[r["symbol"]][ts] = r
    return by_sym


def _future(tsmap, tss, ts, h):
    cand = [t for t in tss if abs((t - ts).total_seconds() / 3600 - h) < 1.0]
    return tsmap[cand[0]] if cand else None


def q1(rows):
    c_vals = Counter()
    for r in rows:
        for c in r.get("candidates") or []:
            if c.get("setup") in ("MR", "RV", "BR") and c.get("C") is not None:
                c_vals[round(c["C"], 3)] += 1
    print(f"Q1. 반전(MR/RV/BR) 후보 저장 C 분포 (고유값 {len(c_vals)}개):")
    for v, n in sorted(c_vals.items()):
        print(f"   C={v:+.3f}: {n}")


def q2(by_sym):
    print("\nQ2. 리클레임 증거의 라벨-프리 방향 지속성 (방향별 분리):")
    variants = [
        ("state", "reclaim_n>=2 상태"),
        ("event", "신선 플립 이벤트(직전 2h 내 ev<2)"),
        ("event+leg", "이벤트 + 선행 반대레그(24h 중 50%+ 우세)"),
    ]
    for key, label in variants:
        print(f"  -- {label} --")
        for d in ("long", "short"):
            opp = "short" if d == "long" else "long"
            hits = {h: [] for h in H}
            nev = 0
            for _sym, tsmap in by_sym.items():
                tss = sorted(tsmap)
                for i, ts in enumerate(tss):
                    r = tsmap[ts]
                    if reclaim_n(r["raw"], d) < 2:
                        continue
                    if key in ("event", "event+leg"):
                        prev = [t for t in tss[max(0, i - 2):i]
                                if (ts - t).total_seconds() <= 7200]
                        if not prev or any(reclaim_n(tsmap[t]["raw"], d) >= 2 for t in prev):
                            continue
                    if key == "event+leg":
                        back = [t for t in tss if 0 < (ts - t).total_seconds() / 3600 <= 24]
                        if len(back) < 12:
                            continue
                        opp_dom = sum(1 for t in back if reclaim_n(tsmap[t]["raw"], opp) >= 2)
                        if opp_dom < len(back) * 0.5:
                            continue
                    nev += 1
                    for h in H:
                        fut = _future(tsmap, tss, ts, h)
                        if fut is None:
                            continue
                        ret = fut["p0"] / r["p0"] - 1.0
                        hits[h].append((ret > 0) if d == "long" else (ret < 0))
            line = f"    [{d}] 표본 {nev}"
            for h in H:
                a = hits[h]
                if a:
                    line += f" | +{h}h {sum(a) / len(a):.1%}(n={len(a)})"
            print(line)
    # 드리프트 대조 베이스라인
    print("  -- 베이스라인(무조건) --")
    for d in ("long", "short"):
        arr = []
        for _sym, tsmap in by_sym.items():
            tss = sorted(tsmap)
            for ts in tss:
                fut = _future(tsmap, tss, ts, 24)
                if fut is None:
                    continue
                ret = fut["p0"] / tsmap[ts]["p0"] - 1.0
                arr.append((ret > 0) if d == "long" else (ret < 0))
        if arr:
            print(f"    [{d}] +24h {sum(arr) / len(arr):.1%} (n={len(arr)})")


def q3(by_sym):
    boost = Counter()
    tot = 0
    for _sym, tsmap in by_sym.items():
        for _ts, r in tsmap.items():
            tot += 1
            for d in ("long", "short"):
                if reclaim_n(r["raw"], d) < 2:
                    continue
                sl = slow_align(r.get("ctx") or {}, r["raw"])
                if (sl < 0) if d == "long" else (sl > 0):
                    boost[d] += 1
    print("\nQ3. 부스트 활성 구간(reclaim>=2 ∧ slow구조 반대) 빈도:")
    for d in ("long", "short"):
        print(f"  [{d}] {boost[d]} / {tot} 스냅샷시간 ({boost[d] / max(1, tot):.1%})")


if __name__ == "__main__":
    rows = load_rows()
    print(f"로드: {len(rows)} 스냅샷")
    q1(rows)
    by_sym = _by_symbol(rows)
    q2(by_sym)
    q3(by_sym)
