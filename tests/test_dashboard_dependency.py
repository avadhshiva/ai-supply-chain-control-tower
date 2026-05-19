from __future__ import annotations

import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.routers.ai import get_dependency_analysis
from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    OperationalRisk,
    OperationalRiskList,
    SupplierReliabilityOverview,
)
from app.frontend import dashboard
from app.frontend.dashboard import (
    _engine_version_meta,
    build_dependency_intelligence_panel_html,
    coerce_dependency_analysis_payload,
)


def _router_sample_payload() -> dict:
    """Same shape as GET /api/v1/ai/dependency-analysis (via router + analytics mocks)."""
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

    async def _fetch() -> dict:
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
        return result.model_dump()

    import asyncio

    return asyncio.run(_fetch())


class DependencyIntelligencePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._ROUTER_PAYLOAD = _router_sample_payload()

    def test_router_sample_payload_renders_four_columns(self) -> None:
        html = build_dependency_intelligence_panel_html(self._ROUTER_PAYLOAD)
        self.assertIn("dep-panel-wrap", html)
        self.assertIn("Fragile entities", html)
        self.assertIn("Concentration hotspots", html)
        self.assertIn("Dependency chains", html)
        self.assertIn("Cascading operational risk", html)
        self.assertIn("RT-001", html)
        self.assertIn("Supplier network", html)
        self.assertIn("Combined 17%", html)

    def test_panel_renders_four_columns(self) -> None:
        payload = {
            "engine_version": "deterministic-dependency-v1",
            "top_fragile_entities": [
                {
                    "entity_id": "RT-A",
                    "domain": "route",
                    "label": "RT-A",
                    "fragility_score": 0.82,
                    "blast_radius_score": 0.45,
                    "severity": "critical",
                }
            ],
            "concentration_hotspots": [
                {
                    "domain": "delivery",
                    "entity_id": "RT-A",
                    "label": "RT-A",
                    "concentration_index": 0.71,
                    "weight_share": 0.6,
                    "rank": 1,
                }
            ],
            "dependency_chains": [
                {
                    "chain_id": "chain:supplier_inventory_delivery",
                    "path": ["domain:supplier", "domain:inventory", "domain:delivery"],
                    "path_labels": ["Supplier network", "Inventory network", "Delivery network"],
                    "chain_pressure": 0.55,
                }
            ],
            "cascading_risk_statements": [
                {
                    "statement_id": "cascade:cross_domain",
                    "source_domain": "delivery",
                    "target_domains": ["inventory", "supplier"],
                    "severity": "high",
                    "statement": "Cross-domain pressure <script>alert(1)</script> detected.",
                    "chain_entities": ["RT-A"],
                }
            ],
            "cross_domain_pressure_summary": {
                "inventory_pressure": 0.25,
                "delivery_pressure": 0.4,
                "supplier_pressure": 0.2,
                "combined_pressure": 0.35,
                "dominant_domain": "delivery",
                "summary": "Moderate cross-domain coupling.",
            },
        }
        html = build_dependency_intelligence_panel_html(payload)
        self.assertIn("dep-panel-wrap", html)
        self.assertIn("Fragile entities", html)
        self.assertIn("RT-A", html)

    def test_panel_escapes_html_in_statements(self) -> None:
        payload = {
            "engine_version": "v1",
            "top_fragile_entities": [],
            "concentration_hotspots": [],
            "dependency_chains": [],
            "cascading_risk_statements": [
                {
                    "statement": "Cross-domain pressure <script>alert(1)</script> detected.",
                    "severity": "high",
                    "source_domain": "delivery",
                }
            ],
        }
        html = build_dependency_intelligence_panel_html(payload)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)

    def test_none_payload_returns_empty_string(self) -> None:
        self.assertEqual(build_dependency_intelligence_panel_html(None), "")

    def test_empty_dict_still_renders_panel_shell(self) -> None:
        html = build_dependency_intelligence_panel_html({})
        self.assertIn("dep-panel-wrap", html)
        self.assertIn("No fragile entities flagged.", html)

    def test_empty_section_lists_still_render_columns(self) -> None:
        html = build_dependency_intelligence_panel_html(
            {
                "engine_version": "deterministic-dependency-v1",
                "top_fragile_entities": [],
                "concentration_hotspots": [],
                "dependency_chains": [],
                "cascading_risk_statements": [],
                "cross_domain_pressure_summary": {
                    "summary": "Pressure only.",
                    "combined_pressure": 0.2,
                },
            }
        )
        self.assertIn("dep-panel-wrap", html)
        self.assertIn("Pressure only.", html)
        self.assertIn("No fragile entities flagged.", html)

    def test_legacy_alias_keys_are_accepted(self) -> None:
        html = build_dependency_intelligence_panel_html(
            {
                "engine_version": "deterministic-dependency-v1",
                "fragile_entities": [
                    {
                        "entity_id": "P-9",
                        "domain": "product",
                        "label": "P-9",
                        "fragility_score": 0.5,
                        "blast_radius_score": 0.3,
                        "severity": "medium",
                    }
                ],
                "concentration_hotspots": [],
                "dependency_chains": [],
                "cascading_risks": [
                    {
                        "statement": "Legacy cascade key.",
                        "severity": "low",
                        "source_domain": "inventory",
                    }
                ],
            }
        )
        self.assertIn("P-9", html)
        self.assertIn("Legacy cascade key.", html)

    def test_coerce_unwraps_data_wrapper(self) -> None:
        inner = {
            "engine_version": "deterministic-dependency-v1",
            "top_fragile_entities": [{"entity_id": "X", "label": "X", "domain": "route"}],
            "concentration_hotspots": [],
            "dependency_chains": [],
            "cascading_risk_statements": [],
        }
        coerced = coerce_dependency_analysis_payload({"data": inner})
        self.assertIsNotNone(coerced)
        assert coerced is not None
        html = build_dependency_intelligence_panel_html(coerced)
        self.assertIn("X", html)


class DependencyDashboardWiringTests(unittest.TestCase):
    def test_engine_version_meta_does_not_double_prefix_v(self) -> None:
        self.assertEqual(
            _engine_version_meta({"engine_version": "deterministic-dependency-v1"}),
            "deterministic-dependency-v1",
        )
        self.assertIsNone(_engine_version_meta(None))

    def test_main_fetches_dependency_before_panel_render(self) -> None:
        main_src = inspect.getsource(dashboard.main)
        fetch_src = inspect.getsource(dashboard._fetch_dashboard_payloads)
        self.assertIn('"/ai/dependency-analysis', fetch_src)
        self.assertIn("_get_cached_dashboard_payloads()", main_src)
        coerce_at = main_src.index("dependency_raw = coerce_dependency_analysis_payload")
        panel_at = main_src.index("_dependency_intelligence_panel(")
        self.assertLess(coerce_at, panel_at)

    def test_dependency_panel_is_render_only(self) -> None:
        panel_src = inspect.getsource(dashboard._dependency_intelligence_panel)
        self.assertNotIn("_fetch_json", panel_src)
        self.assertNotIn("httpx.Client", panel_src)
        self.assertNotIn("No dependency intelligence returned.", panel_src)

    def test_panel_shows_unavailable_only_when_payload_none(self) -> None:
        mock_st = MagicMock()
        with patch.object(dashboard, "st", mock_st):
            dashboard._dependency_intelligence_panel(None)
        mock_st.caption.assert_called_once_with("Dependency intelligence unavailable.")
        panel_calls = [
            c[0][0] for c in mock_st.markdown.call_args_list if "dep-panel-wrap" in c[0][0]
        ]
        self.assertEqual(panel_calls, [])

    def test_panel_renders_html_when_payload_present(self) -> None:
        payload = _router_sample_payload()
        mock_st = MagicMock()
        with patch.object(dashboard, "st", mock_st):
            dashboard._dependency_intelligence_panel(payload)
        mock_st.caption.assert_not_called()
        panel_calls = [
            c[0][0] for c in mock_st.markdown.call_args_list if "dep-panel-wrap" in c[0][0]
        ]
        self.assertEqual(len(panel_calls), 1)
        self.assertIn("RT-001", panel_calls[0])
