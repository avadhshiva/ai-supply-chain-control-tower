from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.ai.recovery_simulator import RECOVERY_ENGINE_VERSION
from app.api.router import api_router
from app.api.routers.ai import get_recovery_scenarios
from app.api.schemas.ai import RecoveryScenariosResult
from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    SupplierReliabilityOverview,
)
from app.services.recovery_scenarios import build_recovery_scenarios_from_analytics


class RecoveryScenariosRouteRegistrationTests(unittest.TestCase):
    def test_recovery_scenarios_route_registered_under_v1(self) -> None:
        paths = {route.path for route in api_router.routes}
        self.assertIn("/v1/ai/recovery-scenarios", paths)


class RecoveryScenariosServiceTests(unittest.TestCase):
    def test_build_from_analytics_returns_three_strategies(self) -> None:
        inventory = InventoryRiskSummary(
            total_items=50,
            low_stock_items=5,
            critical_items=3,
            overstocked_items=1,
            avg_stock_coverage_days=8.0,
        )
        deliveries = DelayedDeliverySummary(
            total_deliveries=100,
            delayed_deliveries=12,
            failed_deliveries=4,
            sla_breaches=10,
            avg_delay_hours=36.0,
        )
        suppliers = SupplierReliabilityOverview(
            total_suppliers=20,
            high_risk_suppliers=4,
            reliable_suppliers=12,
            avg_reliability_score=0.68,
            avg_on_time_delivery_rate=0.72,
            avg_lead_time_days=7.0,
        )

        result = build_recovery_scenarios_from_analytics(inventory, deliveries, suppliers)
        self.assertEqual(result.engine_version, RECOVERY_ENGINE_VERSION)
        self.assertEqual([s.kind for s in result.strategies], ["conservative", "balanced", "aggressive"])

    def test_build_from_analytics_is_deterministic(self) -> None:
        inventory = InventoryRiskSummary(
            total_items=10,
            low_stock_items=1,
            critical_items=2,
            overstocked_items=0,
            avg_stock_coverage_days=5.0,
        )
        deliveries = DelayedDeliverySummary(
            total_deliveries=20,
            delayed_deliveries=2,
            failed_deliveries=1,
            sla_breaches=3,
            avg_delay_hours=12.0,
        )
        suppliers = SupplierReliabilityOverview(
            total_suppliers=8,
            high_risk_suppliers=2,
            reliable_suppliers=5,
            avg_reliability_score=0.75,
            avg_on_time_delivery_rate=0.80,
            avg_lead_time_days=6.0,
        )
        a = build_recovery_scenarios_from_analytics(inventory, deliveries, suppliers)
        b = build_recovery_scenarios_from_analytics(inventory, deliveries, suppliers)
        self.assertEqual(a.model_dump(), b.model_dump())


class RecoveryScenariosRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_recovery_scenarios_returns_response_model(self) -> None:
        inventory = InventoryRiskSummary(
            total_items=25,
            low_stock_items=4,
            critical_items=2,
            overstocked_items=0,
            avg_stock_coverage_days=9.0,
        )
        deliveries = DelayedDeliverySummary(
            total_deliveries=40,
            delayed_deliveries=5,
            failed_deliveries=2,
            sla_breaches=6,
            avg_delay_hours=24.0,
        )
        suppliers = SupplierReliabilityOverview(
            total_suppliers=10,
            high_risk_suppliers=3,
            reliable_suppliers=6,
            avg_reliability_score=0.70,
            avg_on_time_delivery_rate=0.74,
            avg_lead_time_days=5.0,
        )
        expected = build_recovery_scenarios_from_analytics(inventory, deliveries, suppliers)

        db = object()
        with (
            patch(
                "app.api.routers.ai.analytics_reads.get_inventory_risk_summary",
                new=AsyncMock(return_value=inventory),
            ),
            patch(
                "app.api.routers.ai.analytics_reads.get_delayed_delivery_summary",
                new=AsyncMock(return_value=deliveries),
            ),
            patch(
                "app.api.routers.ai.analytics_reads.get_supplier_reliability_overview",
                new=AsyncMock(return_value=suppliers),
            ),
        ):
            result = await get_recovery_scenarios(db)

        self.assertIsInstance(result, RecoveryScenariosResult)
        self.assertEqual(result.model_dump(), expected.model_dump())

    async def test_response_validates_against_schema(self) -> None:
        inventory = InventoryRiskSummary(
            total_items=1,
            low_stock_items=0,
            critical_items=1,
            overstocked_items=0,
            avg_stock_coverage_days=None,
        )
        deliveries = DelayedDeliverySummary(
            total_deliveries=1,
            delayed_deliveries=0,
            failed_deliveries=0,
            sla_breaches=0,
            avg_delay_hours=None,
        )
        suppliers = SupplierReliabilityOverview(
            total_suppliers=1,
            high_risk_suppliers=0,
            reliable_suppliers=1,
            avg_reliability_score=None,
            avg_on_time_delivery_rate=None,
            avg_lead_time_days=None,
        )

        db = object()
        with (
            patch(
                "app.api.routers.ai.analytics_reads.get_inventory_risk_summary",
                new=AsyncMock(return_value=inventory),
            ),
            patch(
                "app.api.routers.ai.analytics_reads.get_delayed_delivery_summary",
                new=AsyncMock(return_value=deliveries),
            ),
            patch(
                "app.api.routers.ai.analytics_reads.get_supplier_reliability_overview",
                new=AsyncMock(return_value=suppliers),
            ),
        ):
            result = await get_recovery_scenarios(db)

        roundtrip = RecoveryScenariosResult.model_validate(result.model_dump())
        self.assertEqual(roundtrip.engine_version, RECOVERY_ENGINE_VERSION)
        self.assertEqual(len(roundtrip.strategies), 3)
        for strategy in roundtrip.strategies:
            self.assertGreater(strategy.recovery_horizon_days, 0)
            self.assertGreaterEqual(strategy.confidence, 0.0)
            self.assertLessEqual(strategy.confidence, 1.0)
            self.assertTrue(strategy.operational_tradeoff_note)
            self.assertGreaterEqual(len(strategy.operational_assumptions), 1)

    def test_service_reflects_sla_and_inventory_pressure(self) -> None:
        base_inv = InventoryRiskSummary(
            total_items=100,
            low_stock_items=0,
            critical_items=2,
            overstocked_items=0,
            avg_stock_coverage_days=8.0,
        )
        base_del = DelayedDeliverySummary(
            total_deliveries=100,
            delayed_deliveries=0,
            failed_deliveries=2,
            sla_breaches=6,
            avg_delay_hours=None,
        )
        base_sup = SupplierReliabilityOverview(
            total_suppliers=20,
            high_risk_suppliers=3,
            reliable_suppliers=10,
            avg_reliability_score=0.7,
            avg_on_time_delivery_rate=0.72,
            avg_lead_time_days=7.0,
        )
        base = build_recovery_scenarios_from_analytics(base_inv, base_del, base_sup)

        stressed_del = base_del.model_copy(update={"sla_breaches": 20, "failed_deliveries": 8})
        stressed = build_recovery_scenarios_from_analytics(base_inv, stressed_del, base_sup)
        self.assertGreater(
            stressed.strategies[1].projected_improvements.breach_reduction,
            base.strategies[1].projected_improvements.breach_reduction,
        )

        stressed_inv = base_inv.model_copy(update={"critical_items": 12})
        inv_stressed = build_recovery_scenarios_from_analytics(stressed_inv, base_del, base_sup)
        self.assertGreater(
            inv_stressed.strategies[1].projected_improvements.stockout_reduction,
            base.strategies[1].projected_improvements.stockout_reduction,
        )
