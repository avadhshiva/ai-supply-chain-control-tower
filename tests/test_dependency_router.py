from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.ai.dependency_engine import DEPENDENCY_ENGINE_VERSION
from app.api.router import api_router
from app.api.routers.ai import get_dependency_analysis
from app.api.schemas.ai import DependencyAnalysisResult
from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    OperationalRisk,
    OperationalRiskList,
    SupplierReliabilityOverview,
)
from app.services.dependency_analysis import build_dependency_analysis_from_analytics


class DependencyRouteRegistrationTests(unittest.TestCase):
    def test_dependency_analysis_route_registered_under_v1(self) -> None:
        paths = {route.path for route in api_router.routes}
        self.assertIn("/v1/ai/dependency-analysis", paths)


class DependencyAnalysisServiceTests(unittest.TestCase):
    def test_build_from_analytics_returns_expected_sections(self) -> None:
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
        risks = OperationalRiskList(
            items=[
                OperationalRisk(
                    risk_type="delivery",
                    label="SLA breaches on RT-001",
                    severity="high",
                    count=2,
                    score=50.0,
                    metric="breach_hours",
                )
            ]
        )

        result = build_dependency_analysis_from_analytics(inventory, deliveries, suppliers, risks)
        self.assertEqual(result.engine_version, DEPENDENCY_ENGINE_VERSION)
        self.assertIsInstance(result.cross_domain_pressure_summary.summary, str)
        self.assertIsInstance(result.dependency_chains, list)

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
        risks = OperationalRiskList(items=[])
        a = build_dependency_analysis_from_analytics(inventory, deliveries, suppliers, risks)
        b = build_dependency_analysis_from_analytics(inventory, deliveries, suppliers, risks)
        self.assertEqual(a.model_dump(), b.model_dump())


class DependencyRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_dependency_analysis_returns_response_model(self) -> None:
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
        risks = OperationalRiskList(
            items=[
                OperationalRisk(
                    risk_type="inventory",
                    label="Low stock for P-1",
                    severity="medium",
                    count=1,
                    score=10.0,
                    metric="stock_gap_units",
                )
            ]
        )
        expected = build_dependency_analysis_from_analytics(inventory, deliveries, suppliers, risks)

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
            patch(
                "app.api.routers.ai.analytics_reads.list_top_operational_risks",
                new=AsyncMock(return_value=risks),
            ),
        ):
            result = await get_dependency_analysis(db, operational_risk_limit=20)

        self.assertIsInstance(result, DependencyAnalysisResult)
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
        risks = OperationalRiskList(items=[])

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
            patch(
                "app.api.routers.ai.analytics_reads.list_top_operational_risks",
                new=AsyncMock(return_value=risks),
            ),
        ):
            result = await get_dependency_analysis(db)

        roundtrip = DependencyAnalysisResult.model_validate(result.model_dump())
        self.assertEqual(roundtrip.engine_version, DEPENDENCY_ENGINE_VERSION)
        for field in (
            roundtrip.cross_domain_pressure_summary.combined_pressure,
            roundtrip.cross_domain_pressure_summary.inventory_pressure,
        ):
            self.assertGreaterEqual(field, 0.0)
            self.assertLessEqual(field, 1.0)
