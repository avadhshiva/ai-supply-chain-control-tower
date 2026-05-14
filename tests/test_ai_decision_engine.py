from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.ai.decision_engine import build_recommendations
from app.api.router import api_router
from app.api.routers.ai import get_ai_recommendations
from app.api.schemas.ai import RecommendationsResponse
from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    OperationalRisk,
    OperationalRiskList,
    ScenarioTagBucket,
    ScenarioTagDistribution,
    SupplierReliabilityOverview,
)


class AiRouteRegistrationTests(unittest.TestCase):
    def test_ai_recommendations_route_registered_under_v1(self) -> None:
        paths = {route.path for route in api_router.routes}
        self.assertIn("/v1/ai/recommendations", paths)


class BuildRecommendationsTests(unittest.TestCase):
    def test_critical_inventory_overrides_low_stock_rule(self) -> None:
        inv = InventoryRiskSummary(
            total_items=100,
            low_stock_items=10,
            critical_items=2,
            overstocked_items=0,
            avg_stock_coverage_days=3.0,
        )
        dm = DelayedDeliverySummary(
            total_deliveries=50,
            delayed_deliveries=0,
            failed_deliveries=0,
            sla_breaches=0,
            avg_delay_hours=None,
        )
        sup = SupplierReliabilityOverview(
            total_suppliers=20,
            high_risk_suppliers=0,
            reliable_suppliers=15,
            avg_reliability_score=0.9,
            avg_on_time_delivery_rate=0.9,
            avg_lead_time_days=5.0,
        )
        scenarios = ScenarioTagDistribution(items=[])
        risks = OperationalRiskList(items=[])

        recs = build_recommendations(inv, dm, sup, scenarios, risks)
        ids = [r.id for r in recs]
        self.assertIn("inventory:critical_stock", ids)
        self.assertNotIn("inventory:low_stock", ids)

    def test_deterministic_sorting_and_delivery_failed_is_critical(self) -> None:
        inv = InventoryRiskSummary(
            total_items=10,
            low_stock_items=0,
            critical_items=0,
            overstocked_items=0,
            avg_stock_coverage_days=20.0,
        )
        dm = DelayedDeliverySummary(
            total_deliveries=10,
            delayed_deliveries=0,
            failed_deliveries=1,
            sla_breaches=0,
            avg_delay_hours=None,
        )
        sup = SupplierReliabilityOverview(
            total_suppliers=5,
            high_risk_suppliers=2,
            reliable_suppliers=2,
            avg_reliability_score=0.65,
            avg_on_time_delivery_rate=0.70,
            avg_lead_time_days=8.0,
        )
        scenarios = ScenarioTagDistribution(
            items=[
                ScenarioTagBucket(
                    scenario_tag="critical",
                    inventory_items=1,
                    delivery_metrics=0,
                    suppliers=0,
                    total=1,
                )
            ]
        )
        risks = OperationalRiskList(
            items=[
                OperationalRisk(
                    risk_type="delivery",
                    label="SLA breaches on R1",
                    severity="critical",
                    count=3,
                    score=12.0,
                    metric="breach_hours",
                )
            ]
        )

        recs = build_recommendations(inv, dm, sup, scenarios, risks)
        self.assertEqual(recs[0].severity, "critical")
        self.assertEqual(recs[0].category, "delivery")
        self.assertIn(recs[0].confidence, ("high", "medium", "low"))
        self.assertTrue(recs[0].simulation_insights)
        self.assertEqual(recs[0].owner, "Logistics Ops")

        severities = [r.severity for r in recs]
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        self.assertEqual(severities, sorted(severities, key=lambda s: rank[s]))


class AiRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_ai_recommendations_returns_response_model(self) -> None:
        inv = InventoryRiskSummary(
            total_items=1,
            low_stock_items=0,
            critical_items=0,
            overstocked_items=0,
            avg_stock_coverage_days=10.0,
        )
        dm = DelayedDeliverySummary(
            total_deliveries=1,
            delayed_deliveries=0,
            failed_deliveries=0,
            sla_breaches=0,
            avg_delay_hours=None,
        )
        sup = SupplierReliabilityOverview(
            total_suppliers=1,
            high_risk_suppliers=0,
            reliable_suppliers=1,
            avg_reliability_score=0.95,
            avg_on_time_delivery_rate=0.95,
            avg_lead_time_days=3.0,
        )
        scenarios = ScenarioTagDistribution(items=[])
        risks = OperationalRiskList(items=[])

        db = object()
        frozen = datetime(2026, 1, 1, tzinfo=timezone.utc)

        with (
            patch(
                "app.api.routers.ai.analytics_reads.get_inventory_risk_summary",
                new=AsyncMock(return_value=inv),
            ),
            patch(
                "app.api.routers.ai.analytics_reads.get_delayed_delivery_summary",
                new=AsyncMock(return_value=dm),
            ),
            patch(
                "app.api.routers.ai.analytics_reads.get_supplier_reliability_overview",
                new=AsyncMock(return_value=sup),
            ),
            patch(
                "app.api.routers.ai.analytics_reads.get_scenario_tag_distribution",
                new=AsyncMock(return_value=scenarios),
            ),
            patch(
                "app.api.routers.ai.analytics_reads.list_top_operational_risks",
                new=AsyncMock(return_value=risks),
            ),
            patch("app.api.routers.ai.datetime") as dt_mock,
        ):
            dt_mock.now.return_value = frozen
            result = await get_ai_recommendations(db, operational_risk_limit=5)

        self.assertIsInstance(result, RecommendationsResponse)
        self.assertTrue(str(result.engine_version).startswith("deterministic-rules-"))
        self.assertEqual(result.generated_at, frozen)
        self.assertEqual(result.recommendations, [])
