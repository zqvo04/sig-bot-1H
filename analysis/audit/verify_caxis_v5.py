"""verify_caxis_v5.py — C축 V5 사전등록 검증 하니스 (docs/CAXIS_V5_DESIGN.md §6).

저장 스냅샷 반사실 A/B (오프라인·라이브 무수정). 두 파트:
  A. V5-R 3-way: 반전(MR/RV/BR) C를 v1(macro echo) / v2(구조주입) / v5lite(1H fast만
     주입, fr=0.20 P1 재사용)로 재계산 → IC·Brier·발사 재생(방향분리·시간분할).
  B. V5-B 부스트: 추종(TF/BO) 후보의 저장 C에 리클레임 부스트 max-클램프를 라이브
     규칙 그대로 적용(신선도는 연속 스냅샷의 dist 부호이력으로 근사) → "새로 열린
     발사"만 격리 채점 + 라벨-프리 이벤트 지속성.

──────────────────────────────────────────────────────────────────────
사전등록 판정 기준 — 결과 확인 후 변경 금지 (위반 시 결과 무효):
  [공통]
   G1 방향분리: 수용은 "각 방향 비열등 ∧ 합산 개선"만 (베타 아티팩트 차단).
   G2 UPLEG 게이트: fade-방향 채택 판정은 UPLEG 스냅샷 ≥300 ∧ UPLEG 반전 결판 ≥20
      충족 시에만 유효. 미달 → verdict=판정불가 (기준 완화 금지 — v2 게이트 승계).
  [V5-R 채택 — v1 대비]
   R1 IC 개선 ∧ 시간분할 양 구간 부호 일관   R2 Brier 비열등(Δ ≤ +0.005)
   R3 발사분 exp_R 비열등(방향별)             R4 발사빈도 ≥50% 유지     ∧ G2
  [V5-B 점등]
   B1 새로 열린 발사 결판 ≥8 (미달 = 판정불가·표본 계속 축적)
   B2 열린 발사: win% ≥ floor ∧ exp_R > 0 ∧ PF > 1
   B3 방향별(결판 ≥3인 방향): win% ≥ floor − 0.08
   B4 알트 열린 발사의 BTC초과 24h 수익 평균 > 0 (베타 상쇄 확인)
   B5 라벨-프리: boost_armed 이벤트 +24h 방향적중 > 무조건 베이스라인 (양방향)
──────────────────────────────────────────────────────────────────────
통계 주의: 표본은 자기상관(72h 중첩)·현재 단일레짐(UPLEG 0) — G2 미충족 동안
방향성 판정은 전부 "판정불가"가 정답이며 이 하니스는 그렇게 보고한다.

CLI: python analysis/audit/verify_caxis_v5.py
"""
from __future__ import annotations

import glob
import json
import math
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime

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
FR_LITE = 0.20            # v5lite fast 가중 — P1(WRF_CTX_FAST_W) 검증계수 재사용·고정
BOOST_MIN_DECIDED = 8     # B1
UPLEG_SNAP_MIN, UPLEG_DECIDED_MIN = 300, 20   # G2


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
    return LAB.split_band_reversal(rows)


def _fixed_r(c, path):
    entry, tp, sl = c.get("entry"), c.get("tp"), c.get("sl")
    if not entry or not tp or not sl:
        return None
    return LAB.triple_barrier(path, c["dir"], abs(entry - sl) / entry,
                              abs(tp - entry) / entry, c.get("t_max", 48))


def _fire(setup, C, L, F, rr, veto_n):
    p = CAL.prior_p_hat(setup, C, L, F)
    if veto_n > 0:
        return False, p
    ev = p * rr - (1.0 - p)
    return bool(p >= FLOOR and ev >= getattr(config, "WRF_EV_MIN", 0.15)
                and rr >= getattr(config, "WRF_EV_RR_FLOOR", 0.85)), p


def _agg(tbs):
    dec = [t for t in tbs if t and t.get("tb_win") is not None]
    rs = [t["r_multiple"] for t in tbs if t and t.get("r_multiple") is not None]
    pos = sum(r for r in rs if r > 0)
    neg = -sum(r for r in rs if r < 0)
    return {"n": len(tbs), "decided": len(dec),
            "win%": round(100 * sum(t["tb_win"] for t in dec) / len(dec), 1) if dec else None,
            "expR": round(st.mean(rs), 3) if rs else None,
            "PF": round(pos / neg, 2) if neg > 0 else (float("inf") if pos > 0 else None)}


def _ic(pairs):
    """point-biserial 상관(C vs tb_win). pairs=[(C, win01)]."""
    if len(pairs) < 5:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = st.mean(xs), st.mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


# ════════════════════════════════════════════════════════════════════
# Part A — V5-R 3-way (반전 C 재계산)
# ════════════════════════════════════════════════════════════════════

def _rev_c(arm, ctx, raw, pcts, direction):
    """반전 C를 arm(v1|v2|v5lite)으로 재계산. 킬 토글은 라이브 기본값 그대로(전 arm 공통)."""
    if arm in ("v1", "v2"):
        old = getattr(config, "WRF_REV_CTX_V2", False)
        config.WRF_REV_CTX_V2 = (arm == "v2")
        try:
            return D._ctx_exhaustion(ctx, raw, pcts, direction)
        finally:
            config.WRF_REV_CTX_V2 = old
    # v5lite: fade_align = (1-fr)·(±macro) + fr·(±fast_struct) — envelope 구설계 보존
    base = getattr(config, "WRF_REV_CTX_BASE", 0.25)
    ev = D._struct_evidence(ctx, raw)
    sgn = 1 if direction == "long" else -1
    align = (1 - FR_LITE) * sgn * ev["m"] + FR_LITE * sgn * ev["fast"]
    C = max(-1.0, min(1.0, base + (1.0 - base) * align))
    return D._reclaim_kill(D._impulse_kill(C, raw, pcts, direction), raw, direction)


def part_a(rows):
    print("═" * 72)
    print("Part A — V5-R 3-way: 반전 C = v1(macro echo) / v2(구조) / v5lite(1H fast만)")
    print("═" * 72)
    shadow = getattr(config, "WRF_SHADOW_SETUPS", {"BR"})
    # 시간분할(전/후반) — IC 일관성용
    tss = sorted(r["ts"] for r in rows)
    mid = tss[len(tss) // 2]
    for arm in ("v1", "v2", "v5lite"):
        pairs_all, pairs_dir = [], {"long": [], "short": []}
        pairs_half = {"H1": [], "H2": []}
        briers = []
        fired_tbs, fired_dir = [], {"long": [], "short": []}
        for r in rows:
            raw, ctx, pcts, path = r["raw"], r.get("ctx") or {}, r.get("pct") or {}, r["path"]
            best = {}
            for c in r.get("candidates") or []:
                if c.get("setup") not in _REV or None in (c.get("C"), c.get("L"), c.get("F")):
                    continue
                C = _rev_c(arm, ctx, raw, pcts, c["dir"])
                tb = _fixed_r(c, path)
                if tb and tb.get("tb_win") is not None:
                    w = tb["tb_win"]
                    pairs_all.append((C, w))
                    pairs_dir[c["dir"]].append((C, w))
                    pairs_half["H1" if r["ts"] <= mid else "H2"].append((C, w))
                    briers.append((CAL.prior_p_hat(c["setup"], C, c["L"], c["F"]) - w) ** 2)
                if c["setup"] in shadow:
                    continue
                f, p = _fire(c["setup"], C, c["L"], c["F"], c.get("rr", 2.0),
                             len(c.get("veto") or []))
                if f:
                    k = ("RV" if c["setup"] == "BR" else c["setup"], c["dir"])
                    if k not in best or p > best[k][0]:
                        best[k] = (p, c, tb)
            for (_s, d), (_p, c, tb) in best.items():
                fired_tbs.append(tb)
                fired_dir[d].append(tb)
        ic = _ic(pairs_all)
        print(f"\n  [{arm}] IC={None if ic is None else round(ic, 3)}"
              f" (롱 {None if _ic(pairs_dir['long']) is None else round(_ic(pairs_dir['long']), 3)}"
              f" / 숏 {None if _ic(pairs_dir['short']) is None else round(_ic(pairs_dir['short']), 3)}"
              f" | 시간분할 H1 {None if _ic(pairs_half['H1']) is None else round(_ic(pairs_half['H1']), 3)}"
              f" / H2 {None if _ic(pairs_half['H2']) is None else round(_ic(pairs_half['H2']), 3)})"
              f"  Brier={round(st.mean(briers), 4) if briers else None} (n={len(pairs_all)})")
        print(f"       발사재생: 합산 {_agg(fired_tbs)}")
        print(f"                 롱 {_agg(fired_dir['long'])}")
        print(f"                 숏 {_agg(fired_dir['short'])}")
    print("\n  판정(R1~R4)은 G2(UPLEG) 충족 후에만 유효 — 아래 게이트 요약 참조.")


# ════════════════════════════════════════════════════════════════════
# Part B — V5-B 리클레임 부스트 반사실
# ════════════════════════════════════════════════════════════════════

def _flip_hist(by_sym):
    """연속 스냅샷의 dist 부호이력 → {(sym, ts): (fv, fe)} 근사(1h 간격, 갭이면 None)."""
    out = {}
    for sym, tsmap in by_sym.items():
        tss = sorted(tsmap)
        for i, ts in enumerate(tss):
            res = []
            for key in ("dist_vwap_atr", "dist_ema20_atr"):
                cur = (tsmap[ts]["raw"] or {}).get(key)
                if cur is None or cur == 0:
                    res.append(None)
                    continue
                bars = None
                for k in range(1, i + 1):
                    prev_ts, cur_ts = tss[i - k], tss[i - k + 1]
                    if (cur_ts - prev_ts).total_seconds() > 5400:   # 갭 → 이력 단절
                        break
                    x = (tsmap[prev_ts]["raw"] or {}).get(key)
                    if x is None:
                        break
                    if x * cur <= 0:
                        bars = k - 1
                        break
                res.append(bars)
            out[(sym, ts)] = tuple(res)
    return out


def _boost_c(C, ctx, raw, direction, fv, fe):
    """라이브 _reclaim_boost 규칙 재현(신선도만 오프라인 근사 주입)."""
    n = D._reclaim_n(raw, direction)
    if n < getattr(config, "WRF_REV_RECLAIM_MIN", 2):
        return C
    sgn = 1 if direction == "long" else -1
    k = getattr(config, "WRF_RECLAIM_FRESH_K", 6)
    dv, de = raw.get("dist_vwap_atr"), raw.get("dist_ema20_atr")
    fresh = ((fv is not None and fv <= k and (dv or 0) * sgn > 0)
             or (fe is not None and fe <= k and (de or 0) * sgn > 0))
    if not fresh:
        return C
    slow = D._slow_align(D._struct_evidence(ctx, raw))
    if not ((slow < 0) if direction == "long" else (slow > 0)):
        return C
    return max(C, 0.50 if n >= 3 else 0.25)


def part_b(rows, by_sym):
    print("\n" + "═" * 72)
    print("Part B — V5-B 리클레임 부스트(추종 TF/BO): 저장 C에 max-클램프 반사실 적용")
    print("═" * 72)
    flips = _flip_hist(by_sym)
    btc_map = LAB.build_btc_ret_map(rows)
    opened, opened_dir, opened_ex = [], {"long": [], "short": []}, []
    n_armed = n_cand = 0
    for r in rows:
        raw, ctx, path = r["raw"], r.get("ctx") or {}, r["path"]
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (ValueError, TypeError):
            continue
        fv, fe = flips.get((r["symbol"], ts), (None, None))
        # 라이브 raw에 계측 필드가 있으면(신규 데이터) 그것을 우선(정확) 사용
        fv = raw.get("bars_since_vwap_flip", fv)
        fe = raw.get("bars_since_ema20_flip", fe)
        for c in r.get("candidates") or []:
            if c.get("setup") not in _CONT or None in (c.get("C"), c.get("L"), c.get("F")):
                continue
            n_cand += 1
            f0, _ = _fire(c["setup"], c["C"], c["L"], c["F"], c.get("rr", 2.0),
                          len(c.get("veto") or []))
            C2 = _boost_c(c["C"], ctx, raw, c["dir"], fv, fe)
            if C2 == c["C"]:
                continue
            n_armed += 1
            f1, _ = _fire(c["setup"], C2, c["L"], c["F"], c.get("rr", 2.0),
                          len(c.get("veto") or []))
            if f1 and not f0:
                tb = _fixed_r(c, path)
                opened.append(tb)
                opened_dir[c["dir"]].append(tb)
                if "BTC" not in r["symbol"]:
                    ex = LAB.exret(path, r["ts"], btc_map, 24)
                    if ex is not None:
                        opened_ex.append(ex if c["dir"] == "long" else -ex)
    print(f"  추종 후보 {n_cand}건 중 부스트 발동 {n_armed}건 → 새로 열린 발사 {len(opened)}건")
    print(f"    합산 {_agg(opened)}")
    print(f"    롱   {_agg(opened_dir['long'])}")
    print(f"    숏   {_agg(opened_dir['short'])}")
    if opened_ex:
        print(f"    B4 알트 BTC초과(진입방향) 24h 평균: {st.mean(opened_ex):+.4f} (n={len(opened_ex)})")
    # ── B5 라벨-프리: boost_armed '이벤트' 지속성 (후보 무관 전 스냅샷) ──
    hits = {d: [] for d in ("long", "short")}
    base_hits = {d: [] for d in ("long", "short")}
    for sym, tsmap in by_sym.items():
        tss = sorted(tsmap)
        for ts in tss:
            r = tsmap[ts]
            raw, ctx = r["raw"], r.get("ctx") or {}
            fut = [t for t in tss if abs((t - ts).total_seconds() / 3600 - 24) < 1.0]
            if not fut:
                continue
            ret = tsmap[fut[0]]["p0"] / r["p0"] - 1.0
            fv, fe = flips.get((sym, ts), (None, None))
            for d in ("long", "short"):
                ok = (ret > 0) if d == "long" else (ret < 0)
                base_hits[d].append(ok)
                if _boost_c(-1.0, ctx, raw, d, fv, fe) > -1.0:   # armed 여부만 검사
                    hits[d].append(ok)
    print("  B5 라벨-프리 (+24h 방향적중, armed 이벤트 vs 무조건):")
    for d in ("long", "short"):
        a, b = hits[d], base_hits[d]
        print(f"    [{d}] armed {sum(a)/len(a):.1%}(n={len(a)}) vs 베이스 {sum(b)/len(b):.1%}(n={len(b)})"
              if a else f"    [{d}] armed 이벤트 0건")
    return opened, opened_dir, opened_ex, hits, base_hits


# ════════════════════════════════════════════════════════════════════

def main():
    rows = load_rows()
    by_sym = defaultdict(dict)
    for r in rows:
        try:
            by_sym[r["symbol"]][datetime.fromisoformat(r["ts"])] = r
        except (ValueError, TypeError):
            continue
    n_upleg = sum(1 for r in rows if (r.get("ctx") or {}).get("btc_macro") == "UPLEG")
    print(f"로드: {len(rows)} 스냅샷(경로 보유) | UPLEG {n_upleg}건 | floor={FLOOR}")
    g2 = n_upleg >= UPLEG_SNAP_MIN
    print(f"G2(UPLEG {UPLEG_SNAP_MIN}+): {'충족' if g2 else '미충족 → fade-방향 채택판정 전부 판정불가'}\n")

    part_a(rows)
    opened, opened_dir, opened_ex, hits, base_hits = part_b(rows, by_sym)

    print("\n" + "═" * 72)
    print("게이트 요약 (사전등록 — 기준 변경 금지)")
    print("═" * 72)
    print(f"  G2 UPLEG 게이트: {'PASS' if g2 else 'FAIL → V5-R(R1~R4) verdict=판정불가'}")
    dec = [t for t in opened if t and t.get("tb_win") is not None]
    if len(dec) < BOOST_MIN_DECIDED:
        print(f"  V5-B B1: 열린 발사 결판 {len(dec)} < {BOOST_MIN_DECIDED} → verdict=판정불가(표본 축적 계속)")
    else:
        a = _agg(opened)
        b2 = (a["win%"] or 0) >= FLOOR * 100 and (a["expR"] or -1) > 0 and (a["PF"] or 0) > 1
        print(f"  V5-B B2: {'PASS' if b2 else 'FAIL'} ({a})")
        for d in ("long", "short"):
            dd = [t for t in opened_dir[d] if t and t.get("tb_win") is not None]
            if len(dd) >= 3:
                w = sum(t["tb_win"] for t in dd) / len(dd)
                print(f"  V5-B B3[{d}]: {'PASS' if w >= FLOOR - 0.08 else 'FAIL'} (win {w:.1%}, n={len(dd)})")
        if opened_ex:
            print(f"  V5-B B4: {'PASS' if st.mean(opened_ex) > 0 else 'FAIL'}")
    for d in ("long", "short"):
        a, b = hits[d], base_hits[d]
        if a:
            ok = sum(a) / len(a) > sum(b) / len(b)
            print(f"  V5-B B5[{d}]: {'PASS' if ok else 'FAIL'} "
                  f"(armed {sum(a)/len(a):.1%} vs 베이스 {sum(b)/len(b):.1%}, n={len(a)})")
        else:
            print(f"  V5-B B5[{d}]: 판정불가(이벤트 0)")


if __name__ == "__main__":
    main()
