from __future__ import annotations

from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from app.api.router import api_router
from app.api.routers.analytics import get_inventory_risk_summary
from app.api.schemas.analytics import InventoryRiskSummary


class AnalyticsRouteRegistrationTests(TestCase):
    def test_analytics_routes_are_registered_under_v1(self) -> None:
        paths = {route.path for route in api_router.routes}

        self.assertIn("/v1/analytics/inventory-risk-summary", paths)
        self.assertIn("/v1/analytics/low-stock-items", paths)
        self.assertIn("/v1/analytics/delayed-delivery-summary", paths)
        self.assertIn("/v1/analytics/supplier-reliability-overview", paths)
        self.assertIn("/v1/analytics/scenario-tag-distribution", paths)
        self.assertIn("/v1/analytics/top-operational-risks", paths)


class AnalyticsRouterTests(IsolatedAsyncioTestCase):
    async def test_inventory_risk_summary_returns_service_payload(self) -> None:
        db = object()
        payload = InventoryRiskSummary(
            total_items=12,
            low_stock_items=3,
            critical_items=2,
            overstocked_items=1,
            avg_stock_coverage_days=9.5,
        )

        with patch(
            "app.api.routers.analytics.analytics_reads.get_inventory_risk_summary",
            new=AsyncMock(return_value=payload),
        ) as service:
            result = await get_inventory_risk_summary(db)

        self.assertIs(result, payload)
        service.assert_awaited_once_with(db)
