"""Regression contracts for canonical execution semantics (schema v4)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "analysis"))

import config
from wrf import calibration, detectors, engine, execution, levels, logger, notion_wrf, schema, veto
import labels


class ExecutionContractTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "plan_schema_version": 1,
            "decision_id": "decision-test-1",
            "decision_ts": "2026-01-01T00:00:00+00:00",
            "symbol": "TEST/USDT",
            "setup": "BO",
            "dir": "long",
            "price_basis": "decision_price",
            "entry": 100.0,
            "tp": 101.0,
            "sl": 99.0,
            "r_dist": 1.0,
            "rr": 1.0,
            "t_max": 1,
            "trail_dist": None,
            "same_bar_policy": "SL_FIRST",
            "trailing_bar_policy": "PRIOR_STOP_ONLY",
            "config_hash": "test-config",
            "code_sha": "test-code",
        }

    def test_absolute_plan_is_not_rebased_to_next_open(self):
        """A next-bar gap must not move a decision-time absolute TP/SL."""
        path = {"o": [0.02], "h": [0.021], "l": [0.019], "c": [0.02], "complete": True}
        out = execution.evaluate_plan_path(self.plan, path, 100.0)
        self.assertEqual(out["outcome"], "WIN")
        self.assertEqual(out["reason"], "TP_HIT")
        self.assertEqual(out["r_multiple"], 1.0)

    def test_live_and_offline_canonical_evaluator_are_identical(self):
        path = {"o": [0.02], "h": [0.021], "l": [0.019], "c": [0.02], "complete": True}
        candles = execution.path_to_absolute_ohlc(path, 100.0)
        self.assertIsNotNone(candles)
        self.assertEqual(execution.evaluate_plan(self.plan, candles), execution.evaluate_plan_path(self.plan, path, 100.0))

    def test_trailing_does_not_assume_same_bar_high_then_low(self):
        plan = dict(self.plan, tp=110.0, t_max=1, trail_dist=2.0)
        candles = pd.DataFrame({"open": [100.0], "high": [104.0], "low": [101.0], "close": [103.0]})
        out = execution.evaluate_plan(plan, candles)
        self.assertEqual(out["outcome"], "TIMEOUT")
        self.assertEqual(out["reason"], "EXPIRED_WIN")
        self.assertEqual(out["r_multiple"], 3.0)

    def test_notion_paper_wrapper_uses_canonical_absolute_plan(self):
        idx = pd.DatetimeIndex([pd.Timestamp("2026-01-01T01:00:00+00:00")])
        candles = pd.DataFrame({"open": [102.0], "high": [102.1], "low": [101.9], "close": [102.0]}, index=idx)
        out = notion_wrf._eval_canonical_signal("LONG", 100.0, 101.0, 99.0, 1, candles,
                                                 pd.Timestamp("2026-01-01T00:00:00+00:00"))
        self.assertEqual(out["status"], "WIN")
        self.assertEqual(out["reason"], "TP_HIT")
        self.assertEqual(out["r_mult"], 1.0)

    def test_schema_roundtrip_preserves_complete_execution_plan(self):
        candidate = {
            "setup": "TF", "dir": "long", "precond": True,
            "entry": 100.0, "tp": 101.0, "sl": 99.0, "r_dist": 1.0, "rr": 1.0, "t_max": 48,
            "trail_dist": 2.0, "p_hat": 0.60, "p_execution": 0.60, "p_source": "prior",
            "p_prior": 0.61, "p_cal": 0.62, "p_execution_prior": 0.60, "p_execution_cal": 0.61,
            "p_cal_source": "prior", "win_floor": 0.58, "C": 0.1, "L": 0.2, "F": 0.3,
            "confluence_n": 0, "veto": [], "size": 1.0, "fire": True, "shadow_band": False,
            "quarantine": [], "reason": "fixture", "decision_id": self.plan["decision_id"],
            "execution_plan": dict(self.plan, trail_dist=2.0),
        }
        row = schema.build_row({"symbol": "TEST/USDT", "ts": self.plan["decision_ts"], "p0": 100.0,
                                "raw": {}, "ctx": {}, "pct": {}, "feat": {}, "candidates": [candidate]})
        persisted = row["candidates"][0]
        self.assertEqual(row["execution_semantics"], "canonical_execution_plan_v1")
        self.assertEqual(persisted["execution_plan"], candidate["execution_plan"])
        self.assertEqual(persisted["trail_dist"], 2.0)
        self.assertEqual(persisted["decision_id"], self.plan["decision_id"])
        self.assertEqual(persisted["p_execution_prior"], 0.60)

    def test_candidate_dataset_uses_v4_execution_plan(self):
        # If labels rebased to o[0]=102 this would TIMEOUT; canonical absolute TP=101 must WIN.
        candidate = {
            "setup": "BO", "dir": "long", "entry": 100.0, "tp": 101.0, "sl": 99.0,
            "r_dist": 1.0, "rr": 1.0, "t_max": 1, "trail_dist": None,
            "p_hat": 0.60, "p_execution": 0.60, "p_source": "prior", "p_prior": 0.60,
            "p_cal": 0.60, "p_execution_prior": 0.60, "p_execution_cal": 0.60,
            "p_cal_source": "prior", "win_floor": 0.58, "C": 0.1, "L": 0.2, "F": 0.3,
            "confluence_n": 0, "veto": [], "quarantine": [], "fire": True,
            "execution_plan": self.plan, "decision_id": self.plan["decision_id"],
        }
        row = {
            "schema_version": 4, "execution_semantics": "canonical_execution_plan_v1",
            "snapshot_id": "TEST/USDT_2026-01-01T00:00:00+00:00", "ts": self.plan["decision_ts"],
            "symbol": "TEST/USDT", "p0": 100.0, "raw": {}, "ctx": {}, "candidates": [candidate],
            "path": {"o": [0.02], "h": [0.021], "l": [0.019], "c": [0.02], "complete": True},
        }
        df = labels.candidate_dataset([row])
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["tb_outcome"], "WIN")
        self.assertEqual(float(df.iloc[0]["tb_r"]), 1.0)
        self.assertEqual(df.iloc[0]["execution_semantics"], "canonical_execution_plan_v1")

    def test_decision_ledger_is_idempotent_per_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(config, "WRF_DECISION_LEDGER_DIR", tmp):
                self.assertTrue(logger.record_decision_event(self.plan, "ENGINE_APPROVED", "fixture"))
                self.assertFalse(logger.record_decision_event(self.plan, "ENGINE_APPROVED", "fixture"))
                self.assertTrue(logger.record_decision_event(self.plan, "LEDGER_CREATED", "fixture"))
                file = Path(tmp) / "TEST-USDT" / "2026-01.jsonl"
                lines = file.read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(lines), 2)

    def _engine_fixture(self, setup, rr, source, near_sl=False):
        feat = {
            "raw": {}, "pct": {},
            "ctx": {"regime_1h": "RANGING", "btc_macro": "CHOP", "allowed_setups": [setup]},
            "ts": "2026-01-01T00:00:00+00:00", "p0": 100.0,
            "df_1h": None, "df_4h": None, "df_1d": None, "measures": {},
        }
        candidate = {"setup": setup, "dir": "long", "C": 0.4, "L": 0.5, "F": 0.5,
                     "confluence_n": 0, "reason": "fixture"}
        if setup == "BO":
            candidate.update({"box_hi": 110.0, "box_lo": 100.0})
        level = {"entry": 100.0, "tp": 100.0 + rr * 2.0, "sl": 98.0,
                 "r_dist": 2.0, "rr": rr, "t_max": 36}
        pe = {"p_prior": 0.65 if setup == "BO" else 0.60,
              "p_cal": 0.65 if setup == "BO" else 0.60,
              "cal_source": source, "p_hat": 0.65 if setup == "BO" else 0.60,
              "source": source, "floor": 0.58, "fire_rights": "live"}
        with mock.patch.object(engine.features, "build_features", return_value=feat), \
             mock.patch.object(detectors, "detect_all", return_value=[candidate]), \
             mock.patch.object(levels, "compute_levels", return_value=level), \
             mock.patch.object(calibration, "load_table", return_value={}), \
             mock.patch.object(calibration, "evaluate", return_value=pe), \
             mock.patch.object(veto, "global_vetoes", return_value=[]), \
             mock.patch.object(veto, "evaluate", return_value=[]), \
             mock.patch.object(config, "WRF_SHADOW_SETUPS", set()), \
             mock.patch.object(config, "WRF_FIRE_RIGHTS_ENABLED", False), \
             mock.patch.object(config, "WRF_EV_GATE", not near_sl), \
             mock.patch.object(config, "WRF_BO_SL_NEAR", near_sl):
            return engine.run_engine("TEST/USDT", {}, {}, {}, btc_macro="CHOP")

    def test_calibrated_probability_cannot_bypass_negative_ev(self):
        out = self._engine_fixture("MR", rr=0.5, source="calibrated")
        self.assertEqual(len(out["candidates"]), 1)
        self.assertFalse(out["candidates"][0]["fire"])

    def test_bo_geometry_adjusts_and_persists_execution_probabilities(self):
        out = self._engine_fixture("BO", rr=2.0, source="prior", near_sl=True)
        rec = out["candidates"][0]
        self.assertEqual(rec["p_prior"], 0.65)
        self.assertEqual(rec["p_execution_prior"], 0.59)
        self.assertEqual(rec["p_execution"], rec["p_execution_prior"])
        self.assertEqual(rec["execution_plan"]["decision_id"], rec["decision_id"])

    def test_unavailable_notion_open_state_is_explicit(self):
        with mock.patch.object(notion_wrf, "enabled", return_value=False):
            self.assertIsNone(notion_wrf.has_open_signal("TEST/USDT", "long"))


if __name__ == "__main__":
    unittest.main()
