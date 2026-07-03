"""[Phase C-v3] 반전형 C축 개혁 반사실(counterfactual) 검증 — 순수 stdlib.

저장된 후보(precond 통과분)의 C만 교체해 발사집합·실현성능이 어떻게 바뀌는지 잰다.
라이브 코드 미변경(측정만). 비교 대상:

  cur     : 스토어된 C (v1 macro-echo)
  v2      : river 단독 — base + (1-base)·fade_align(_ctx_struct_align)  [기존 토글]
  stretch : loc_vwap 백분위 단독 (기각된 실험 — 대조군)
  v3      : 0.40·river + 0.30·stretch + 0.30·decel  ★개혁안(선험 고정 가중치)

성분 복원(전부 저장 raw/ctx에서 — 무상태·자기분포 백분위):
  river   = fade_align(0.45·macro + 0.25·bias + 0.20·ema_4h + 0.10·ema_1d_struct)
  stretch = to_axis(midrank_trailing(dist_vwap_atr, 200)), 롱=하방스트레치가 +
  decel   = to_axis(midrank_trailing(Δ(raw.macd) 1h, 200)), 롱=히스토그램 상승전환이 +
            (연속 1h 스냅샷에서만 Δ 산출 — 갭이면 중립 0.5)

한계: 라우팅/베토로 '기록조차 안 된' 후보는 복원 불가(bars 인프라 축적 후 해소) —
새 발사수는 하한 추정. 표본은 소수 독립사건(자기상관) — 판정이 아니라 방향 점검용.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "src", "wrf"))
import calibration as cal  # noqa: E402

FLOOR = 0.58
WIN = 200
BASE_V2 = 0.25          # WRF_REV_CTX_BASE (v2 재현용)
W_RIVER, W_STRETCH, W_DECEL = 0.40, 0.30, 0.30   # ★선험 고정 — 여기서 튜닝하지 않는다
REV_SETUPS = {"MR", "RV", "BR"}


def clip(x):
    return max(-1.0, min(1.0, x))


def to_axis(p):
    return clip((p - 0.5) * 2.0)


def midrank(series, v):
    arr = [x for x in series if x is not None]
    if v is None or len(arr) < 5:
        return 0.5
    lt = sum(1 for x in arr if x < v) / len(arr)
    le = sum(1 for x in arr if x <= v) / len(arr)
    return (lt + le) / 2.0


def entry_ref(path):
    o = path.get("o")
    return float(o[0]) if o else 0.0


def triple_barrier(path, direction, sl_frac, tp_frac, t_max, sl_priority=True):
    h = path.get("h") or []
    l = path.get("l") or []
    c = path.get("c") or []
    if not c or sl_frac <= 0 or tp_frac <= 0:
        return None
    base = 1.0 + entry_ref(path)
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
            return {"win": 1 if win else 0, "r": (tp_frac / sl_frac) if win else -1.0}
        if sl_hit:
            return {"win": 0, "r": -1.0}
        if tp_hit:
            return {"win": 1, "r": tp_frac / sl_frac}
    if len(c) < n:
        return None
    if not path.get("complete") and len(c) < int(t_max):
        return None
    realized = (1.0 + c[n - 1]) / base - 1.0
    if not long:
        realized = -realized
    return {"win": None, "r": realized / sl_frac if sl_frac > 0 else 0.0}


# ── 로드 ──────────────────────────────────────────────────────────────
def load_rows(data_dir=None):
    data_dir = data_dir or os.path.join(_ROOT, "data", "research")
    rows = []
    for fp in sorted(glob.glob(os.path.join(data_dir, "*", "*.jsonl"))):
        for line in open(fp, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            if "candidates" in r and "ctx" in r and (r.get("path") or {}).get("c"):
                rows.append(r)
    rows.sort(key=lambda r: (r["symbol"], r["ts"]))
    return rows


# ── 성분 복원 (심볼별 트레일링 — 룩어헤드 없음) ──────────────────────────
def build_components(rows):
    by_sym = defaultdict(list)
    for r in rows:
        by_sym[r["symbol"]].append(r)
    comp = {}
    for sym, rs in by_sym.items():
        dv = [(r.get("raw") or {}).get("dist_vwap_atr") for r in rs]
        macd = [(r.get("raw") or {}).get("macd") for r in rs]
        ts = [datetime.fromisoformat(r["ts"]) for r in rs]
        # Δmacd: 정확히 1h 연속 스냅샷에서만 (갭 → None)
        dm = [None]
        for i in range(1, len(rs)):
            if (macd[i] is not None and macd[i - 1] is not None
                    and ts[i] - ts[i - 1] == timedelta(hours=1)):
                dm.append(macd[i] - macd[i - 1])
            else:
                dm.append(None)
        for i, r in enumerate(rs):
            loc = midrank(dv[max(0, i - WIN):i], dv[i])
            dpc = midrank([x for x in dm[max(0, i - WIN):i]], dm[i])
            raw, ctx = r.get("raw") or {}, r.get("ctx") or {}
            m = {"UPLEG": 1.0, "DOWNLEG": -1.0, "CHOP": 0.0}.get(ctx.get("btc_macro", "CHOP"), 0.0)
            b = {"BULL": 1.0, "BEAR": -1.0, "NEUTRAL": 0.0}.get(ctx.get("bias_1d", "NEUTRAL"), 0.0)
            h4 = float(raw.get("ema_4h") or 0)
            ds = float(raw.get("ema_1d_struct") or 0)
            river = 0.45 * m + 0.25 * b + 0.20 * h4 + 0.10 * ds
            comp[id(r)] = {"loc": loc, "dpc": dpc, "river": river}
    return comp


def c_variant(variant, direction, cp):
    long = direction == "long"
    fade = cp["river"] if long else -cp["river"]
    stretch = -to_axis(cp["loc"]) if long else to_axis(cp["loc"])
    decel = to_axis(cp["dpc"]) if long else -to_axis(cp["dpc"])
    if variant == "v2":
        return clip(BASE_V2 + (1.0 - BASE_V2) * fade)
    if variant == "stretch":
        return clip(BASE_V2 + (1.0 - BASE_V2) * stretch)
    if variant == "v3":
        return clip(W_RIVER * fade + W_STRETCH * stretch + W_DECEL * decel)
    raise ValueError(variant)


# ── v4: 임펄스-페이드 킬 (cur 베이스 + 대칭 오버라이드) ────────────────────
# 사전등록(2026-07-03, 데이터 재관찰 전 예측 고정):
#   규칙: 페이드 대상 레그가 '살아있고'(자기 단기구조 ≥2/3 정렬: 1h EMA·MACD부호·
#         BOS/CHoCH) 동시에 극단 스트레치(자기분포 |to_axis(loc_vwap)| ≥ 0.6)면
#         C = min(C_cur, −0.5) — 신선 임펄스 페이드 금지(양방향 대칭).
#   예측: ① 07-01~02 랠리 숏(레그 alive + loc 0.9+) 제거 — cur 실측 전패 구간
#         ② 06-24 13~18h 칼 롱은 cur가 이미 차단 → 변화 없음(무영향)
#         ③ CHOP 완만 스트레치 반전 승리(ETH/HYPE 6월 롱, HYPE 07-01 롱)는 보존
#         ④ 새 발사 0 (열지 않고 닫기만 — 출혈 0)
IK_STRETCH_MIN = 0.6   # 사전 고정 — 본 파일에서 튜닝하지 않는다
IK_ALIVE_MIN = 2       # 3중 2 이상


def leg_alive_n(raw, direction):
    """페이드 대상(반대편) 레그의 단기 생존 신호 수(0~3). 결측은 비생존(보수: 킬 안 함)."""
    long = direction == "long"          # 롱 페이드 = 하락레그가 대상
    sgn = -1 if long else 1
    ema_alive = raw.get("ema") == sgn
    macd = raw.get("macd")
    macd_alive = (macd is not None) and ((macd < 0) if long else (macd > 0))
    struct_alive = raw.get("bos") == sgn or raw.get("choch") == sgn
    return int(ema_alive) + int(macd_alive) + int(struct_alive)


def c_v4(C_cur, direction, cp, raw):
    long = direction == "long"
    stretch = -to_axis(cp["loc"]) if long else to_axis(cp["loc"])
    if stretch >= IK_STRETCH_MIN and leg_alive_n(raw, direction) >= IK_ALIVE_MIN:
        return min(C_cur, -0.5)
    return C_cur


# ── 평가 ──────────────────────────────────────────────────────────────
def evaluate(rows, comp):
    fired = defaultdict(list)   # variant -> recs
    details = []                # 후보 단위 전 변형 기록(케이스 스터디용)
    for r in rows:
        cp = comp[id(r)]
        for c in (r.get("candidates") or []):
            setup, d = c["setup"], c["dir"]
            C, L, F = c.get("C"), c.get("L"), c.get("F")
            if None in (C, L, F):
                continue
            e, tp, sl = c.get("entry"), c.get("tp"), c.get("sl")
            if not (e and tp and sl):
                continue
            vn = len(c.get("veto") or [])
            qn = len(c.get("quarantine") or [])
            tb = triple_barrier(r["path"], d, abs(e - sl) / e, abs(tp - e) / e,
                                c.get("t_max", 48))
            raw = r.get("raw") or {}
            rec = {"sym": r["symbol"], "ts": r["ts"][5:16], "day": r["ts"][:10],
                   "setup": setup, "dir": d, "L": L, "F": F, "tb": tb,
                   "macro": (r.get("ctx") or {}).get("btc_macro"), "cp": cp,
                   "alive": leg_alive_n(raw, d)}
            for variant in ("cur", "v2", "stretch", "v3", "v4"):
                if setup not in REV_SETUPS or variant == "cur":
                    Cv = C
                elif variant == "v4":
                    Cv = c_v4(C, d, cp, raw)
                else:
                    Cv = c_variant(variant, d, cp)
                p = cal.prior_p_hat(setup, Cv, L, F)
                fire = bool(p >= FLOOR and vn == 0 and qn == 0)
                rec[f"C_{variant}"], rec[f"p_{variant}"], rec[f"fire_{variant}"] = Cv, p, fire
                if fire:
                    fired[variant].append(rec)
            details.append(rec)
    return fired, details


def summ(recs, tag):
    dec = [x for x in recs if x["tb"] and x["tb"]["win"] is not None]
    wins = sum(x["tb"]["win"] for x in dec)
    rs = [x["tb"]["r"] for x in recs if x["tb"]]
    wr = wins / len(dec) * 100 if dec else float("nan")
    er = sum(rs) / len(rs) if rs else float("nan")
    dl = sum(1 for x in recs if x["dir"] == "long")
    days = len({x["day"] for x in recs})
    print(f"  {tag:8s} n={len(recs):3d} (롱{dl:3d}/숏{len(recs)-dl:3d}, {days:2d}일) "
          f"| 결판{len(dec):3d} 승{wins:3d} 승률 {wr:5.1f}% 평균R {er:+.3f}")


def main():
    rows = load_rows()
    comp = build_components(rows)
    fired, details = evaluate(rows, comp)

    print(f"후보 재평가 대상 {len(details)}건 (경로 보유 스냅샷 {len(rows)}행)")
    print(f"v3 가중치(선험 고정): river {W_RIVER} / stretch {W_STRETCH} / decel {W_DECEL}\n")

    print("== 발사집합 실현성능 (변형별) ==")
    for v in ("cur", "v2", "stretch", "v3", "v4"):
        summ(fired[v], v)

    for tag in ("v3", "v4"):
        print(f"\n== {tag}가 새로 켠 후보 (cur 미발사 → {tag} 발사) ==")
        newly = [x for x in details if x[f"fire_{tag}"] and not x["fire_cur"]]
        for d in ("long", "short"):
            summ([x for x in newly if x["dir"] == d], f"신규{d[:1]}")
        print(f"== {tag}가 끈 후보 (cur 발사 → {tag} 미발사) — FP 제거 판정 ==")
        off = [x for x in details if x["fire_cur"] and not x[f"fire_{tag}"]]
        for d in ("long", "short"):
            summ([x for x in off if x["dir"] == d], f"제거{d[:1]}")
        for x in off:
            tb = x["tb"]
            res = "미결" if not tb or tb["win"] is None else ("WIN " if tb["win"] else "LOSS")
            print(f"     - {x['sym']:10s} {x['ts']} {x['setup']}/{x['dir'][:1]} "
                  f"loc={x['cp']['loc']:.2f} alive={x['alive']} C={x['C_cur']:+.2f} {res}")

    print("\n== 케이스 스터디: 06-24 캐피출레이션 (BTC 롱 후보, 시간순) ==")
    print("  ts          loc  dpc  river | C:cur → v3   p_v3   fire  결과")
    for x in details:
        if x["day"] != "2026-06-24" or x["dir"] != "long" or x["sym"] != "BTC/USDT":
            continue
        cp, tb = x["cp"], x["tb"]
        res = "미결" if not tb or tb["win"] is None else ("WIN " if tb["win"] else "LOSS")
        print(f"  {x['ts']}  {cp['loc']:.2f} {cp['dpc']:.2f} {cp['river']:+.2f} | "
              f"{x['C_cur']:+.2f} → {x['C_v3']:+.2f}  {x['p_v3']:.3f}  "
              f"{'🔥' if x['fire_v3'] else '  '}  {res}")

    print("\n== 케이스 스터디: 07-01~07-03 반등 (전 후보) ==")
    print("  sym          ts         set/dir  loc  dpc  river | C:cur → v3   p_v3  fire  결과")
    for x in details:
        if not x["day"].startswith("2026-07-0"):
            continue
        cp, tb = x["cp"], x["tb"]
        res = "미결" if not tb or tb["win"] is None else ("WIN " if tb["win"] else "LOSS")
        print(f"  {x['sym']:12s} {x['ts']} {x['setup']}/{x['dir'][:1]}  "
              f"{cp['loc']:.2f} {cp['dpc']:.2f} {cp['river']:+.2f} | "
              f"{x['C_cur']:+.2f} → {x['C_v3']:+.2f}  {x['p_v3']:.3f}  "
              f"{'🔥' if x['fire_v3'] else '  '}  {res}")

    print("\n⚠ 자기상관 표본(발생일 소수) — 방향 점검용. 최종 판정은 OOS 누적 후.")


if __name__ == "__main__":
    main()
