from __future__ import annotations

import unittest

from app.frontend.dashboard_filters import (
    PRIORITY_DRILL_ENTITIES,
    alert_matches_filters,
    default_filter_state,
    discover_drill_targets,
    extract_filter_options,
    filter_risk_items,
    filters_are_active,
    risk_matches_filters,
)
from app.frontend.dashboard_graphs import (
    build_dependency_graph_from_payload,
    operational_pressure_series,
    period_labels,
)
from app.frontend.dashboard_ui import (
    build_entity_drilldown_context,
    metric_card_html,
    severity_chip_markup,
)


class DashboardFilterTests(unittest.TestCase):
    def test_default_filters_not_active(self) -> None:
        self.assertFalse(filters_are_active(default_filter_state()))

    def test_risk_severity_filter(self) -> None:
        row = {
            "risk_type": "delivery",
            "label": "SLA breaches on RT-001",
            "severity": "high",
            "count": 2,
            "score": 50.0,
        }
        filters = default_filter_state()
        filters["severity"] = "high"
        self.assertTrue(risk_matches_filters(row, filters))
        filters["severity"] = "critical"
        self.assertFalse(risk_matches_filters(row, filters))

    def test_route_filter(self) -> None:
        row = {
            "risk_type": "delivery",
            "label": "SLA breaches on RT-012",
            "severity": "critical",
            "count": 3,
            "score": 90.0,
        }
        filters = default_filter_state()
        filters["route"] = "RT-012"
        self.assertTrue(risk_matches_filters(row, filters))
        filters["route"] = "RT-001"
        self.assertFalse(risk_matches_filters(row, filters))

    def test_extract_filter_options_includes_routes_and_scenarios(self) -> None:
        opts = extract_filter_options(
            risk_items=[
                {
                    "risk_type": "delivery",
                    "label": "SLA breaches on RT-001",
                    "severity": "high",
                    "count": 1,
                    "score": 10.0,
                }
            ],
            ai_payload={"recommendations": []},
            scenarios={"items": [{"scenario_tag": "peak_demand", "inventory_items": 1}]},
        )
        self.assertIn("RT-001", opts["routes"])
        self.assertIn("peak_demand", opts["scenario_types"])

    def test_filter_risk_items_subset(self) -> None:
        items = [
            {"risk_type": "delivery", "label": "SLA breaches on RT-001", "severity": "high"},
            {"risk_type": "supplier", "label": "Low reliability: Brown Inc", "severity": "high"},
        ]
        filters = default_filter_state()
        filters["supplier"] = "Brown Inc"
        out = filter_risk_items(items, filters)
        self.assertEqual(len(out), 1)
        self.assertIn("Brown Inc", out[0]["label"])

    def test_alert_matches_supplier_filter(self) -> None:
        alert = {
            "severity": "high",
            "category": "supplier",
            "title": "Brown Inc reliability",
            "summary": "score below threshold",
        }
        filters = default_filter_state()
        filters["supplier"] = "Brown Inc"
        self.assertTrue(alert_matches_filters(alert, filters))


class DrilldownTests(unittest.TestCase):
    def test_discover_priority_entities(self) -> None:
        targets = discover_drill_targets(
            risk_items=[
                {
                    "risk_type": "delivery",
                    "label": "SLA breaches on RT-001",
                    "severity": "high",
                }
            ],
            ai_payload=None,
            dependency={
                "dependency_chains": [
                    {
                        "path_labels": ["Supplier network", "Inventory network", "Delivery network"],
                        "chain_pressure": 0.4,
                    }
                ]
            },
        )
        self.assertIn("RT-001", targets)
        self.assertTrue(any(t.lower() == "delivery network" for t in targets))

    def test_drilldown_context_includes_alerts_and_chains(self) -> None:
        ctx = build_entity_drilldown_context(
            "RT-012",
            risk_items=[
                {
                    "risk_type": "delivery",
                    "label": "SLA breaches on RT-012",
                    "severity": "critical",
                    "score": 80,
                }
            ],
            ai_payload={
                "recommendations": [
                    {
                        "severity": "high",
                        "title": "Route RT-012 pressure",
                        "summary": "breach cluster",
                    }
                ]
            },
            dependency={
                "dependency_chains": [
                    {
                        "path_labels": ["Inventory network", "Delivery network"],
                        "chain_pressure": 0.6,
                    }
                ]
            },
            intel_bundle={"prioritized_actions": []},
        )
        self.assertEqual(ctx["entity"], "RT-012")
        self.assertEqual(len(ctx["alerts"]), 1)
        self.assertEqual(len(ctx["chains"]), 1)
        self.assertTrue(ctx["metrics"])


class DashboardGraphTests(unittest.TestCase):
    def test_operational_pressure_series_length(self) -> None:
        series = operational_pressure_series(
            sla_breaches=10,
            critical_inventory=5,
            high_risk_suppliers=2,
            critical_recommendations=1,
        )
        self.assertEqual(len(series), 7)
        self.assertEqual(len(period_labels(len(series))), 7)

    def test_dependency_graph_builds_nodes_and_edges(self) -> None:
        nodes, edges = build_dependency_graph_from_payload(
            {
                "dependency_chains": [
                    {
                        "path_labels": ["Supplier network", "Inventory network", "Delivery network"],
                        "chain_pressure": 0.55,
                    }
                ],
                "top_fragile_entities": [],
            }
        )
        self.assertGreaterEqual(len(nodes), 3)
        self.assertGreaterEqual(len(edges), 2)


class DashboardUiHelperTests(unittest.TestCase):
    def test_severity_chip_escapes(self) -> None:
        html_out = severity_chip_markup("<script>")
        self.assertIn("&lt;script&gt;", html_out)

    def test_metric_card_html(self) -> None:
        html_out = metric_card_html(label="SLA breaches", value="42", subline="7-period trend")
        self.assertIn("dash-metric-card", html_out)
        self.assertIn("42", html_out)

    def test_priority_entities_constant(self) -> None:
        self.assertIn("Brown Inc", PRIORITY_DRILL_ENTITIES)


if __name__ == "__main__":
    unittest.main()
