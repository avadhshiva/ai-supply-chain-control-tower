from __future__ import annotations

import unittest

from app.frontend.dashboard import (
    build_action_panel,
    build_intel_bundle,
    concentration_score,
    dominant_entity_detection,
    infer_root_causes,
    merge_executive_narrative_lines,
    prioritize_actions,
)


class ConcentrationTests(unittest.TestCase):
    def test_concentration_score_uniform_is_low(self) -> None:
        w = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}
        self.assertLess(concentration_score(w), 0.15)

    def test_concentration_score_single_is_one(self) -> None:
        self.assertEqual(concentration_score({"x": 5.0}), 1.0)


class DominantEntityTests(unittest.TestCase):
    def test_concentrated_delivery_routes(self) -> None:
        risks = [
            {
                "risk_type": "delivery",
                "label": "SLA breaches on RT-A",
                "severity": "critical",
                "count": 5,
                "score": 120.0,
                "metric": "breach_hours",
            },
            {
                "risk_type": "delivery",
                "label": "SLA breaches on RT-B",
                "severity": "high",
                "count": 4,
                "score": 90.0,
                "metric": "breach_hours",
            },
            {
                "risk_type": "delivery",
                "label": "SLA breaches on RT-C",
                "severity": "high",
                "count": 3,
                "score": 40.0,
                "metric": "breach_hours",
            },
        ]
        kpi_ctx = {"kpi_forecast": {"sla_breaches": {"state": "stable"}}}
        d = dominant_entity_detection(risk_items=risks, kpi_ctx=kpi_ctx, failed_deliveries=0)
        self.assertEqual(d["pattern"], "Concentrated risk")
        self.assertGreaterEqual(d["top_share"], 0.55)


class RootCauseAndActionsTests(unittest.TestCase):
    def test_infer_and_prioritize_are_deterministic(self) -> None:
        risks = [
            {
                "risk_type": "delivery",
                "label": "SLA breaches on RT-012",
                "severity": "critical",
                "count": 4,
                "score": 200.0,
                "metric": "breach_hours",
            },
            {
                "risk_type": "delivery",
                "label": "SLA breaches on RT-006",
                "severity": "critical",
                "count": 3,
                "score": 180.0,
                "metric": "breach_hours",
            },
            {
                "risk_type": "supplier",
                "label": "Low reliability: Acme Parts",
                "severity": "high",
                "count": 1,
                "score": 0.45,
                "metric": "reliability_gap",
            },
        ]
        kpi_ctx = {
            "worsening_domains": ["deliveries"],
            "improving_domains": [],
            "kpi_forecast": {
                "sla_breaches": {"state": "volatile", "caption": "elevated volatility"},
                "critical_inventory": {"state": "worsening"},
                "high_risk_suppliers": {"state": "worsening"},
                "critical_recommendations": {"state": "stable"},
            },
        }
        alerts = [
            {
                "id": "x",
                "category": "delivery",
                "severity": "high",
                "title": "Route pressure",
                "summary": "inventory and delivery coupling",
            }
        ]
        drivers = infer_root_causes(
            risk_items=risks,
            ai_alerts=alerts,
            kpi_ctx=kpi_ctx,
            critical_inventory=12,
            sla_breaches=40,
            high_risk_suppliers=5,
            critical_recommendations=2,
            delayed_delivery_summary={"failed_deliveries": 3},
            supplier_overview={"avg_reliability_score": 0.68},
        )
        self.assertTrue(any(d.get("driver_key") == "route_concentration" for d in drivers))
        dom = dominant_entity_detection(
            risk_items=risks,
            kpi_ctx=kpi_ctx,
            failed_deliveries=3,
        )
        actions = prioritize_actions(
            root_causes=drivers,
            dominant=dom,
            risk_items=risks,
            kpi_ctx=kpi_ctx,
        )
        self.assertLessEqual(len(actions), 5)
        self.assertTrue(any("Logistics" in a["owner"] for a in actions))

    def test_build_action_panel_escapes_html(self) -> None:
        html = build_action_panel(
            [
                {
                    "title": "Test <script>",
                    "owner": "Logistics & Co",
                    "impact": "High",
                    "urgency": "Immediate",
                }
            ]
        )
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)


class IntelBundleTests(unittest.TestCase):
    def test_build_intel_bundle_shape(self) -> None:
        bundle = build_intel_bundle(
            risk_items=[
                {
                    "risk_type": "delivery",
                    "label": "SLA breaches on RT-001",
                    "severity": "high",
                    "count": 2,
                    "score": 50.0,
                    "metric": "breach_hours",
                }
            ],
            ai_payload={"recommendations": []},
            kpi_ctx={"worsening_domains": [], "improving_domains": [], "kpi_forecast": {}},
            critical_inventory=0,
            sla_breaches=5,
            high_risk_suppliers=0,
            critical_recommendations=0,
            delayed_delivery_summary={"failed_deliveries": 0},
            supplier_overview={"avg_reliability_score": 0.9},
        )
        self.assertIn("dominant", bundle)
        self.assertIn("prioritized_actions", bundle)
        self.assertIsInstance(bundle["concentration_index"], float)


class NarrativeMergeTests(unittest.TestCase):
    def test_merge_respects_cap(self) -> None:
        dom = {
            "pattern": "Distributed risk",
            "detail": "Spread sample",
            "top_share": 0.3,
            "top_entities": [],
        }
        lines = merge_executive_narrative_lines(
            forecast_lines=["A", "B", "C"],
            dominant=dom,  # type: ignore[arg-type]
            root_summary=["S1"],
        )
        self.assertLessEqual(len(lines), 8)
        self.assertTrue(any("Distributed" in x for x in lines))


if __name__ == "__main__":
    unittest.main()
