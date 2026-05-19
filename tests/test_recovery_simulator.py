from __future__ import annotations

import unittest

from app.ai.recovery_simulator import (
    RECOVERY_ENGINE_VERSION,
    build_recovery_scenarios,
    explain_recovery_coefficients,
    simulate_inventory_rebalancing,
    simulate_lane_reroute,
    simulate_supplier_reallocation,
)


class LaneRerouteSimulationTests(unittest.TestCase):
    def test_zero_inputs_yield_zero_reductions(self) -> None:
        result = simulate_lane_reroute(0.0, 0.8, 10, 5)
        self.assertEqual(result.projected_breach_reduction, 0.0)
        self.assertEqual(result.projected_delay_reduction, 0.0)
        self.assertEqual(result.stabilization_horizon_days, 21)

    def test_full_coverage_reduces_breaches_deterministically(self) -> None:
        result = simulate_lane_reroute(1.0, 1.0, 20, 0)
        self.assertEqual(result.projected_breach_reduction, 18.0)
        self.assertEqual(result.projected_delay_reduction, 11.0)
        self.assertEqual(result.stabilization_horizon_days, 3)
        self.assertEqual(result.confidence_band.level, "high")

    def test_same_inputs_produce_identical_output(self) -> None:
        a = simulate_lane_reroute(0.5, 0.6, 8, 2)
        b = simulate_lane_reroute(0.5, 0.6, 8, 2)
        self.assertEqual(a.model_dump(), b.model_dump())


class SupplierReallocationSimulationTests(unittest.TestCase):
    def test_percent_and_ratio_inputs_are_equivalent(self) -> None:
        as_ratio = simulate_supplier_reallocation(4, 0.5, 0.7)
        as_percent = simulate_supplier_reallocation(4, 50.0, 0.7)
        self.assertEqual(as_ratio.model_dump(), as_percent.model_dump())

    def test_high_reliability_limits_risk_reduction(self) -> None:
        low_rel = simulate_supplier_reallocation(5, 0.8, 0.4)
        high_rel = simulate_supplier_reallocation(5, 0.8, 0.95)
        self.assertGreater(low_rel.projected_supplier_risk_reduction, high_rel.projected_supplier_risk_reduction)


class InventoryRebalancingSimulationTests(unittest.TestCase):
    def test_efficiency_improves_stockout_reduction(self) -> None:
        low = simulate_inventory_rebalancing(10, 0.3, 7.0)
        high = simulate_inventory_rebalancing(10, 0.9, 7.0)
        self.assertGreater(high.projected_stockout_reduction, low.projected_stockout_reduction)
        self.assertLess(high.projected_recovery_days, low.projected_recovery_days)

    def test_service_level_stabilization_is_bounded(self) -> None:
        result = simulate_inventory_rebalancing(3, 1.0, 0.0)
        self.assertGreaterEqual(result.projected_service_level_stabilization, 0.0)
        self.assertLessEqual(result.projected_service_level_stabilization, 1.0)


class BuildRecoveryScenariosTests(unittest.TestCase):
    _BASE_KWARGS = {
        "affected_route_share": 0.7,
        "reroute_success_rate": 0.75,
        "current_sla_breaches": 12,
        "failed_deliveries": 3,
        "high_risk_supplier_count": 4,
        "reallocation_percent": 60.0,
        "supplier_reliability_score": 0.68,
        "critical_inventory_count": 5,
        "transfer_efficiency": 0.8,
        "replenishment_delay_days": 6.0,
    }

    def test_returns_three_ordered_strategies(self) -> None:
        result = build_recovery_scenarios(**self._BASE_KWARGS)
        self.assertEqual(result.engine_version, RECOVERY_ENGINE_VERSION)
        kinds = [s.kind for s in result.strategies]
        self.assertEqual(kinds, ["conservative", "balanced", "aggressive"])

    def test_aggressive_beats_conservative_on_breach_reduction(self) -> None:
        result = build_recovery_scenarios(**self._BASE_KWARGS)
        conservative = result.strategies[0]
        aggressive = result.strategies[2]
        self.assertGreater(
            aggressive.projected_improvements.breach_reduction,
            conservative.projected_improvements.breach_reduction,
        )
        self.assertGreaterEqual(
            conservative.recovery_horizon_days,
            aggressive.recovery_horizon_days,
        )

    def test_strategies_include_required_fields(self) -> None:
        result = build_recovery_scenarios(**self._BASE_KWARGS)
        for strategy in result.strategies:
            self.assertTrue(strategy.title)
            self.assertGreaterEqual(len(strategy.operational_assumptions), 3)
            self.assertTrue(strategy.operational_tradeoff_note)
            self.assertGreater(strategy.recovery_horizon_days, 0)
            self.assertGreaterEqual(strategy.confidence, 0.0)
            self.assertLessEqual(strategy.confidence, 1.0)

    def test_build_is_deterministic(self) -> None:
        a = build_recovery_scenarios(**self._BASE_KWARGS)
        b = build_recovery_scenarios(**self._BASE_KWARGS)
        self.assertEqual(a.model_dump(), b.model_dump())


class RecoveryCoefficientsTests(unittest.TestCase):
    def test_explain_coefficients_returns_fixed_policy(self) -> None:
        coeffs = explain_recovery_coefficients()
        self.assertEqual(coeffs["lane_breach_mitigation"], 0.90)
        self.assertEqual(coeffs["inventory_stockout_mitigation"], 0.80)
