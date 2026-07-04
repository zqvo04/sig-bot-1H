"""BR precond 실패모드 진단 — 탐색적(재현 가능, 판정 아님).

BR(밴드반전) 섀도강등의 근본원인이 C축이 아니라 무장조건(precond) 자체인지 확인한다.
저장 BR 후보를 (1)거래량 게이트(TF/MR/RV가 이미 쓰는 `_rev_vol_ok`) (2)방향
(3)스트레치 깊이로 분해해 실패모드를 진단. 결과는 `WRF_BR_REQUIRE_REV_VOL`/
`WRF_BR_REQUIRE_REV_CANDLE`(둘 다 기본 OFF, detectors.py) 설계 근거가 됐다.

CLI: python analysis/audit/probe_br_precond.py
"""
import sys
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "src"))
sys.path.insert(0, os.path.join(_ROOT, "src", "wrf"))
sys.path.insert(0, os.path.join(_ROOT, "analysis"))

from build_dataset import load_snapshots  # noqa: E402
import labels as lab  # noqa: E402


def _agg(sub):
    dec = sub[sub["tb_win"].notna()]
    rs = sub["tb_r"].dropna()
    if not len(dec):
        return f"n={len(sub)} 결판=0"
    win = dec["tb_win"].mean() * 100
    exp = rs.mean() if len(rs) else None
    return f"n={len(sub)} 결판={len(dec)} win%={win:.1f} exp_R={exp:.3f}" if exp is not None \
        else f"n={len(sub)} 결판={len(dec)} win%={win:.1f}"


def main():
    rows = load_snapshots(os.path.join(_ROOT, "data", "research"))
    rows = lab.split_band_reversal(rows)
    meta = {r["snapshot_id"]: (r.get("raw") or {}, r.get("ctx") or {}) for r in rows}
    df = lab.candidate_dataset(rows)
    br = df[df["setup"] == "BR"].copy()
    br["rev_vol_ratio"] = br["snapshot_id"].map(
        lambda k: (meta.get(k, ({}, {}))[0] or {}).get("rev_vol_ratio"))
    br["dist_vwap_atr"] = br["snapshot_id"].map(
        lambda k: (meta.get(k, ({}, {}))[0] or {}).get("dist_vwap_atr"))

    print(f"BR 전체(precond 통과분, 발사무관): n={len(br)}")
    print("  outcome 분포:", br["tb_outcome"].value_counts().to_dict())
    print("  방향별:", br["dir"].value_counts().to_dict())

    print("\n① 거래량 게이트(rev_vol_ratio >= 1.0, TF/MR/RV와 동일 임계) 가상 적용 시:")
    ok = br[(br["rev_vol_ratio"].notna()) & (br["rev_vol_ratio"] >= 1.0)]
    bad = br[(br["rev_vol_ratio"].notna()) & (br["rev_vol_ratio"] < 1.0)]
    miss = br[br["rev_vol_ratio"].isna()]
    for name, sub in (("통과(>=1.0)", ok), ("탈락(<1.0)", bad), ("결측", miss)):
        print(f"  {name}: {_agg(sub)}")

    print("\n② 방향별 성능 (단일레짐 베타 감시 — 코드 대칭은 미러 속성 테스트로 별도 증명):")
    for d in ("long", "short"):
        print(f"  [{d}] {_agg(br[br['dir'] == d])}")

    print("\n③ 스트레치 깊이(|dist_vwap_atr|) 중앙값 기준 분할:")
    br2 = br[br["dist_vwap_atr"].notna()].copy()
    if len(br2):
        med = br2["dist_vwap_atr"].abs().median()
        deep = br2[br2["dist_vwap_atr"].abs() >= med]
        shallow = br2[br2["dist_vwap_atr"].abs() < med]
        print(f"  깊음(>=중앙값): {_agg(deep)}")
        print(f"  얕음(<중앙값): {_agg(shallow)}")

    print("\n④ 발사분(라이브 가정, fire=True)만 위 ①②③ 재적용:")
    brf = br[br["fire"] == True]  # noqa: E712
    print(f"  전체 발사분: {_agg(brf)}")
    okf = brf[(brf["rev_vol_ratio"].notna()) & (brf["rev_vol_ratio"] >= 1.0)]
    print(f"  발사분×거래량통과: {_agg(okf)}")


if __name__ == "__main__":
    main()
