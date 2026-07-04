"""verify_p012.py — P0/P1/P2 반사실 A/B (오프라인 · 라이브 무수정 · 단일변수).

병목 3처방을 저장 스냅샷으로 반사실 채점한다. C축은 저장된 raw/ctx로 재유도(pct 미저장이라
raw-only 함수만 사용) → prior_p_hat 재계산 → 발사 재판정. 실현 R은 저장 tp/sl로 triple_barrier.
각 처방은 '나머지 OFF' 단일변수로 격리 측정한다(과적합·교란 차단).

  P0 (WRF_REV_RECLAIM_KILL) : 반전(MR/RV/BR) C에 리클레임-킬 적용 → 역행 FP 제거량/부수비용
  P1 (WRF_CTX_FAST_STRUCT)  : 추종(TF/BO) C 재유도(fast-struct) → 발사 변화·실현성능
  P2 (WRF_TF_TRAIL)         : TF 발사군 고정TP vs 트레일링 실현 R 비교(+P1로 열린 롱 포함)

주의: 표본은 DOWNLEG/CHOP 단일레짐·UPLEG 0건·72h 중첩(자기상관). 숏측(페이드 차단)만
검증 가능, 롱측(추종 개방)은 통계 확증 불가 — 부호·무악화 확인용. OOS 재검증 전제.

CLI: python analysis/audit/verify_p012.py
"""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "src", "wrf"))
sys.path.insert(0, os.path.join(_ROOT, "analysis"))

import config  # noqa: E402
import detectors as D  # noqa: E402
import calibration as CAL  # noqa: E402
import labels as LAB  # noqa: E402

_REV = {"MR", "RV", "BR"}
_CONT = {"TF", "BO"}
FLOOR = getattr(config, "WRF_WIN_FLOOR", 0.58)


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
            if s.get("schema_version") == 3 and (s.get("path") or {}).get("c"):
                rows.append(s)
    return LAB.split_band_reversal(rows)   # RV→BR 소급 재분류(라이브 정합)


def _fire(setup, C, L, F, rr, veto_n) -> tuple:
    """엔진 발사판정 재현(prior 경로): p_hat≥floor ∧ ¬veto ∧ EV게이트. (shadow·dedup은 상위서)"""
    p = CAL.prior_p_hat(setup, C, L, F)
    if veto_n > 0:
        return False, p
    if getattr(config, "WRF_EV_GATE", True):
        ev = p * rr - (1.0 - p)
        rr_ok = ev >= getattr(config, "WRF_EV_MIN", 0.15) and rr >= getattr(config, "WRF_EV_RR_FLOOR", 0.85)
    else:
        rr_ok = rr >= getattr(config, "WRF_MIN_RR", 1.5)
    return bool(p >= FLOOR and rr_ok), p


def eval_arm(rows, adjust_C=None):
    """한 arm의 발사집합을 라이브 정합으로 산출: shadow 셋업 제외 + 스냅샷내 (setup,dir) dedup
    (최고 p_hat만). adjust_C(c,raw,ctx)→C' 로 처방별 C 조정. 반환 {rowkey: {(setup,dir): (c,raw,path,tb)}}."""
    shadow = getattr(config, "WRF_SHADOW_SETUPS", set())
    fired = {}
    for ri, r in enumerate(rows):
        raw, ctx, path = r.get("raw") or {}, r.get("ctx") or {}, r.get("path") or {}
        best = {}
        for c in r.get("candidates") or []:
            if None in (c.get("C"), c.get("L"), c.get("F")):
                continue
            if c["setup"] in shadow:            # BR 등 섀도 강등 = 라이브 발사 안 함
                continue
            C = adjust_C(c, raw, ctx) if adjust_C else c["C"]
            f, p = _fire(c["setup"], C, c["L"], c["F"], c.get("rr", 2.0), len(c.get("veto") or []))
            if not f:
                continue
            k = (c["setup"], c["dir"])
            if k not in best or p > best[k][0]:
                best[k] = (p, c, raw, path)
        if best:
            fired[ri] = {k: (v[1], v[2], v[3]) for k, v in best.items()}
    return fired


def _fixed_r(c, path):
    entry, tp, sl = c.get("entry"), c.get("tp"), c.get("sl")
    if not entry or not tp or not sl:
        return None
    sl_frac = abs(entry - sl) / entry
    tp_frac = abs(tp - entry) / entry
    return LAB.triple_barrier(path, c["dir"], sl_frac, tp_frac, c.get("t_max", 48))


def _trail_r(c, path, raw):
    entry, sl = c.get("entry"), c.get("sl")
    atr_pct = raw.get("atr_pct")
    if not entry or not sl or not atr_pct:
        return None
    sl_frac = abs(entry - sl) / entry
    trail_frac = getattr(config, "WRF_TF_TRAIL_ATR", 3.0) * (atr_pct / 100.0)
    tmax = getattr(config, "WRF_TF_TRAIL_TMAX", 72)
    return LAB.triple_barrier(path, c["dir"], sl_frac, 99.0, tmax, trail_frac=trail_frac)


def _agg(fired: list) -> dict:
    """fired = [(tb, ...)] → 성능 dict. tb는 triple_barrier 반환(또는 None)."""
    dec = [t for t in fired if t and t.get("tb_win") is not None]
    res = [t for t in fired if t and t.get("r_multiple") is not None]
    rs = [t["r_multiple"] for t in res]
    pos = sum(r for r in rs if r > 0)
    neg = -sum(r for r in rs if r < 0)
    return {
        "n": len(fired),
        "decided": len(dec),
        "win%": round(100 * sum(t["tb_win"] for t in dec) / len(dec), 1) if dec else None,
        "expR": round(st.mean(rs), 3) if rs else None,
        "PF": round(pos / neg, 2) if neg > 0 else (float("inf") if pos > 0 else None),
        "sumR": round(sum(rs), 2) if rs else None,
    }


def _set_flags(**kw):
    for k, v in kw.items():
        setattr(config, k, v)


def _fired_flat(fired: dict) -> list:
    """eval_arm 결과 → [(ri,setup,dir,c,raw,path)] 평탄화."""
    out = []
    for ri, d in fired.items():
        for (setup, dr), (c, raw, path) in d.items():
            out.append((ri, setup, dr, c, raw, path))
    return out


def main():
    rows = load_rows()
    ncand = sum(1 for r in rows for c in (r.get("candidates") or [])
                if None not in (c.get("C"), c.get("L"), c.get("F")))
    stored_fire = sum(1 for r in rows for c in (r.get("candidates") or []) if c.get("fire"))
    print(f"로드: {len(rows)} 스냅샷 · {ncand} 후보 (schema3·경로보유)")
    print(f"플로어={FLOOR}  섀도={getattr(config,'WRF_SHADOW_SETUPS',set())}"
          f"  |  ⚠ UPLEG 0건·단일레짐 — 숏측만 확증, 롱측은 부호/무악화 확인용\n")

    _set_flags(WRF_REV_RECLAIM_KILL=False, WRF_CTX_FAST_STRUCT=False, WRF_TF_TRAIL=False)
    base = eval_arm(rows)
    base_flat = _fired_flat(base)
    base_keys = {(ri, s, d) for (ri, s, d, *_ ) in base_flat}
    print(f"[sanity] 저장 fire={stored_fire}  재현 fire(shadow제외·dedup)={len(base_flat)}  (일치 기대)")
    print(f"[기저] {_agg([_fixed_r(c, path) for (_, _, _, c, _, path) in base_flat])}\n")

    # ── P0: 반전 리클레임-킬 (단일변수) ─────────────────────────────
    print("═" * 70)
    print("P0 — 신선 리클레임 페이드 금지 (WRF_REV_RECLAIM_KILL) · 단일변수")
    print("═" * 70)
    for need in (2, 3):
        _set_flags(WRF_REV_RECLAIM_KILL=True, WRF_REV_RECLAIM_MIN=need,
                   WRF_CTX_FAST_STRUCT=False, WRF_TF_TRAIL=False)
        adj = lambda c, raw, ctx: (D._reclaim_kill(c["C"], raw, c["dir"]) if c["setup"] in _REV else c["C"])
        p0 = eval_arm(rows, adj)
        p0_flat = _fired_flat(p0)
        p0_keys = {(ri, s, d) for (ri, s, d, *_ ) in p0_flat}
        removed = base_keys - p0_keys
        rl = [(ri, s, d, c, path) for (ri, s, d, c, _, path) in base_flat if (ri, s, d) in removed]
        rwin = sum(1 for (_, _, _, c, path) in rl if (_fixed_r(c, path) or {}).get("tb_win") == 1)
        rloss = sum(1 for (_, _, _, c, path) in rl if (_fixed_r(c, path) or {}).get("tb_win") == 0)
        rmshort = sum(1 for (_, _, d, _, _) in rl if d == "short")
        print(f"  MIN={need}: 발사 {len(base_flat)}→{len(p0_flat)} "
              f"(제거 {len(removed)}: 숏 {rmshort} · 손절 {rloss}/익절 {rwin})")
        print(f"          {_agg([_fixed_r(c, path) for (_, _, _, c, _, path) in p0_flat])}")
    print("  주: 현행 라이브는 BR(밴드반전)이 이미 섀도강등 → 리클레임-확증 역행페이드 대부분이")
    print("      선차단됨. P0는 그 위에서 거의 무변경(중복). 아래는 BR-섀도 해제 반사실(P0 순효과 격리):")
    _saved_shadow = getattr(config, "WRF_SHADOW_SETUPS", {"BR"})
    _set_flags(WRF_SHADOW_SETUPS=set())          # BR 섀도 해제 → band-reversal 발사군 포함
    base_no = _fired_flat(eval_arm(rows))
    base_no_keys = {(ri, s, d) for (ri, s, d, *_ ) in base_no}
    _set_flags(WRF_REV_RECLAIM_KILL=True, WRF_REV_RECLAIM_MIN=2, WRF_CTX_FAST_STRUCT=False)
    adj = lambda c, raw, ctx: (D._reclaim_kill(c["C"], raw, c["dir"]) if c["setup"] in _REV else c["C"])
    p0_no = _fired_flat(eval_arm(rows, adj))
    p0_no_keys = {(ri, s, d) for (ri, s, d, *_ ) in p0_no}
    rl = [(c, path) for (ri, s, d, c, _, path) in base_no if (ri, s, d) in (base_no_keys - p0_no_keys)]
    print(f"    BR섀도OFF 기저 : n={len(base_no)}  {_agg([_fixed_r(c, path) for (_, _, _, c, _, path) in base_no])}")
    print(f"    +P0(MIN=2)     : n={len(p0_no)}  {_agg([_fixed_r(c, path) for (_, _, _, c, _, path) in p0_no])}")
    print(f"    제거 {len(rl)}건 실현: " + ", ".join(f"{(_fixed_r(c,path) or {}).get('outcome')}"
          f"({round((_fixed_r(c,path) or {}).get('r_multiple') or 0,2)})" for c, path in rl))
    _set_flags(WRF_SHADOW_SETUPS=_saved_shadow, WRF_REV_RECLAIM_KILL=False)
    print("  해석: 제거가 손절(FP)에 집중·익절 희생 0이면 순효과 +. 단 표본 극소(과신 금지).\n")

    # ── P1: 추종 fast-struct C 재유도 (단일변수) ────────────────────
    print("═" * 70)
    print("P1 — C축 fast-struct 주입 (WRF_CTX_FAST_STRUCT, 추종 TF/BO) · 단일변수")
    print("═" * 70)
    for fw in (0.15, 0.20, 0.25):
        _set_flags(WRF_CTX_FAST_STRUCT=True, WRF_CTX_FAST_W=fw,
                   WRF_REV_RECLAIM_KILL=False, WRF_TF_TRAIL=False)
        adj = lambda c, raw, ctx: (D._ctx_align(ctx, raw, c["dir"]) if c["setup"] in _CONT else c["C"])
        p1 = eval_arm(rows, adj)
        p1_flat = _fired_flat(p1)
        p1_keys = {(ri, s, d) for (ri, s, d, *_ ) in p1_flat}
        added = p1_keys - base_keys
        added_long = sum(1 for (_, _, d) in added if d == "long")
        print(f"  FAST_W={fw}: 발사 {len(base_flat)}→{len(p1_flat)} "
              f"(신규 {len(added)}, 롱 {added_long} / 이탈 {len(base_keys - p1_keys)})")
        print(f"            {_agg([_fixed_r(c, path) for (_, _, _, c, _, path) in p1_flat])}")
    print("  해석: 신규가 롱(추종)에 실리고 무악화면 부호 +(단, UPLEG 확증 전 섀도 유지).\n")

    # ── P2: TF 트레일링 vs 고정TP ───────────────────────────────────
    print("═" * 70)
    print("P2 — TF 추세 태우기: 고정TP vs 트레일링 실현 R (WRF_TF_TRAIL)")
    print("═" * 70)
    _set_flags(WRF_CTX_FAST_STRUCT=True, WRF_CTX_FAST_W=0.20,
               WRF_REV_RECLAIM_KILL=False, WRF_TF_TRAIL=True)
    adj = lambda c, raw, ctx: (D._ctx_align(ctx, raw, c["dir"]) if c["setup"] in _CONT else c["C"])
    p2 = eval_arm(rows, adj)
    tf = [(c, raw, path) for (_, s, _, c, raw, path) in _fired_flat(p2) if s == "TF"]
    print(f"  TF 발사군(P1 포함) n={len(tf)}")
    print(f"    고정 TP(2.5R) : {_agg([_fixed_r(c, path) for (c, _, path) in tf])}")
    print(f"    트레일링(k·ATR): {_agg([_trail_r(c, path, raw) for (c, raw, path) in tf])}")
    print("  해석: 트레일링 sumR/expR가 고정 대비 크면 스윙 몸통 회수 +(승률은 정의상 하락 가능).")

    _set_flags(WRF_REV_RECLAIM_KILL=False, WRF_CTX_FAST_STRUCT=False, WRF_TF_TRAIL=False)


if __name__ == "__main__":
    main()
