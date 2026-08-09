"""2026-08 롤백 자기점검 — P̂이 다시 C/L/F에 반응하는지만 확인한다.

`python analysis/audit/verify_rollback_2026_08.py`

배경: prior 재적합 블록이 wC=wL=wF=0.0을 발행한 상태로 라이브가 그것을 소비해
P̂ = sigmoid(b0[setup])(셋업별 상수)로 붕괴했다. 재적합을 끄면 config 기울기
(1.1/1.3/1.2)로 폴백해 해상도가 돌아와야 한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src import config
from src.wrf import calibration


def main() -> None:
    table = calibration.load_table()
    refit = (table or {}).get("prior_refit") or {}
    print(f"table prior_refit: wC={refit.get('wC')} wL={refit.get('wL')} wF={refit.get('wF')}")
    print(f"WRF_PRIOR_REFIT_ENABLED={config.WRF_PRIOR_REFIT_ENABLED}")

    for setup in ("TF", "BO", "MR", "RV"):
        lo = calibration.prior_p_hat(setup, 0.2, 0.2, 0.2, table)
        hi = calibration.prior_p_hat(setup, 0.9, 0.9, 0.9, table)
        print(f"  {setup}: P̂(0.2,0.2,0.2)={lo:.4f}  P̂(0.9,0.9,0.9)={hi:.4f}  Δ={hi-lo:+.4f}")
        assert hi - lo > 0.05, f"{setup}: P̂이 C/L/F에 반응하지 않는다(기울기 붕괴)"

    for name in ("WRF_REV_CTX_V2", "WRF_CTX_RECLAIM_BOOST", "WRF_REV_RECLAIM_KILL",
                 "WRF_CTX_FAST_STRUCT", "WRF_TF_TRAIL"):
        assert getattr(config, name) is False, f"{name}이 롤백되지 않았다"

    print("OK")


if __name__ == "__main__":
    main()
