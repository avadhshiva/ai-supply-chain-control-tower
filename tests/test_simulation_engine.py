"""Unit tests for deterministic simulation and forecasting helpers."""

from __future__ import annotations

import unittest

from app.ai import simulation_engine as sim


class ProjectThresholdCrossingTests(unittest.TestCase):
    def test_projects_days_when_slope_positive(self) -> None:
        series = [0.05, 0.06, 0.07, 0.08, 0.09, 0.095, 0.10]
        out = sim.project_threshold_crossing(
            current_value=0.10,
            threshold=0.12,
            metric_series=series,
            higher_is_bad=True,
        )
        self.assertIsNotNone(out["days_to_cross"])
        self.assertGreaterEqual(int(out["days_to_cross"] or 0), 1)
        self.assertIn("escalation threshold", str(out["summary"]))

    def test_already_breached(self) -> None:
        out = sim.project_threshold_crossing(
            current_value=0.20,
            threshold=0.12,
            metric_series=[0.18, 0.19, 0.195, 0.198, 0.199, 0.2, 0.20],
            higher_is_bad=True,
        )
        self.assertTrue(bool(out["already_breached"]))

    def test_flat_slope_no_cross_within_horizon(self) -> None:
        flat = [0.08] * 7
        out = sim.project_threshold_crossing(
            current_value=0.08,
            threshold=0.12,
            metric_series=flat,
            higher_is_bad=True,
            max_horizon=30,
        )
        self.assertIsNone(out["days_to_cross"])


class SimulationWhatIfTests(unittest.TestCase):
    def test_delay_reduction_lowers_exposure(self) -> None:
        r = sim.simulate_delay_reduction(
            total_deliveries=100,
            delayed_deliveries=40,
            sla_breaches=25,
            delay_reduction_pct=0.30,
        )
        self.assertGreater(float(r["exposure_delta_pct"]), 0.0)
        self.assertLess(float(r["simulated_exposure"]), float(r["baseline_exposure"]))

    def test_supplier_recovery_deterministic(self) -> None:
        r = sim.simulate_supplier_recovery(
            high_risk_suppliers=6,
            total_suppliers=30,
            avg_reliability_score=0.72,
            reliability_improvement=0.05,
        )
        self.assertIn("lowers", str(r["summary"]))

    def test_inventory_replenishment_deterministic(self) -> None:
        r = sim.simulate_inventory_replenishment(
            low_stock_items=12,
            total_items=200,
            avg_stock_coverage_days=9.0,
            replenishment_acceleration_pct=0.20,
        )
        self.assertGreater(float(r["exposure_delta_pct"]), 0.0)


class ConfidenceScoreTests(unittest.TestCase):
    def test_high_confidence_dense_stable(self) -> None:
        level, score = sim.compute_confidence_score(
            evidence_count=6,
            metric_series=[10.0, 10.2, 10.1, 10.15, 10.2, 10.18, 10.2],
            cross_domain_agreement=True,
            volatility_state="stable",
        )
        self.assertEqual(level, "high")
        self.assertGreaterEqual(score, 0.72)

    def test_low_confidence_sparse_volatile(self) -> None:
        level, score = sim.compute_confidence_score(
            evidence_count=1,
            metric_series=[10.0, 18.0, 9.0, 17.0, 8.0, 16.0, 10.0],
            cross_domain_agreement=False,
            volatility_state="volatile",
        )
        self.assertIn(level, ("low", "medium"))
        self.assertLess(score, 0.72)


class TrendInferenceTests(unittest.TestCase):
    def test_infer_worsening(self) -> None:
        s = [0.1, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16]
        self.assertEqual(sim.infer_metric_trend_state(s, higher_is_bad=True), "worsening")


if __name__ == "__main__":
    unittest.main()
