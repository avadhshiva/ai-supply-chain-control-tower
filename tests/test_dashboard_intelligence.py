from __future__ import annotations

import unittest

from app.frontend.dashboard import (
    build_action_panel,
    build_intel_bundle,
    build_recovery_scenarios_panel_html,
    concentration_score,
    dominant_entity_detection,
    infer_root_causes,
    merge_executive_narrative_lines,
    prioritize_actions,
    recovery_confidence_label,
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


class RecoveryScenariosPanelTests(unittest.TestCase):
    def test_confidence_label_thresholds(self) -> None:
        self.assertEqual(recovery_confidence_label(0.85), "High")
        self.assertEqual(recovery_confidence_label(0.55), "Medium")
        self.assertEqual(recovery_confidence_label(0.2), "Low")

    def test_build_recovery_panel_renders_three_cards(self) -> None:
        payload = {
            "engine_version": "deterministic-recovery-v1",
            "strategies": [
                {
                    "kind": "conservative",
                    "title": "Conservative stabilization",
                    "operational_assumptions": ["Assume lane cap 40%."],
                    "projected_improvements": {
                        "breach_reduction": 1.0,
                        "delay_reduction": 2.0,
                        "supplier_risk_reduction": 0.5,
                        "delivery_improvement": 0.1,
                        "stockout_reduction": 1.0,
                        "service_level_stabilization": 0.8,
                    },
                    "recovery_horizon_days": 12,
                    "confidence": 0.72,
                    "operational_tradeoff_note": "Lower disruption.",
                },
                {
                    "kind": "balanced",
                    "title": "Balanced recovery plan",
                    "operational_assumptions": ["Balanced lane intervention."],
                    "projected_improvements": {
                        "breach_reduction": 2.0,
                        "delay_reduction": 3.0,
                        "supplier_risk_reduction": 1.0,
                        "delivery_improvement": 0.2,
                        "stockout_reduction": 2.0,
                        "service_level_stabilization": 0.85,
                    },
                    "recovery_horizon_days": 10,
                    "confidence": 0.78,
                    "operational_tradeoff_note": "Coordinated owners.",
                },
                {
                    "kind": "aggressive",
                    "title": "Aggressive recovery push",
                    "operational_assumptions": ["Max intervention."],
                    "projected_improvements": {
                        "breach_reduction": 3.0,
                        "delay_reduction": 4.0,
                        "supplier_risk_reduction": 1.5,
                        "delivery_improvement": 0.25,
                        "stockout_reduction": 3.0,
                        "service_level_stabilization": 0.9,
                    },
                    "recovery_horizon_days": 8,
                    "confidence": 0.68,
                    "operational_tradeoff_note": "Higher cost.",
                },
            ],
        }
        html_out = build_recovery_scenarios_panel_html(payload)
        self.assertIn("recovery-card--conservative", html_out)
        self.assertIn("recovery-card--balanced", html_out)
        self.assertIn("recovery-card--aggressive", html_out)
        self.assertIn("High confidence", html_out)
        self.assertIn("12d horizon", html_out)
        self.assertIn("Lower disruption.", html_out)

    def test_build_recovery_panel_escapes_html(self) -> None:
        html_out = build_recovery_scenarios_panel_html(
            {
                "strategies": [
                    {
                        "kind": "balanced",
                        "title": "Test <script>",
                        "operational_assumptions": ['Lane <b>"A"</b>'],
                        "projected_improvements": {
                            "breach_reduction": 0,
                            "delay_reduction": 0,
                            "supplier_risk_reduction": 0,
                            "delivery_improvement": 0,
                            "stockout_reduction": 0,
                            "service_level_stabilization": 0.5,
                        },
                        "recovery_horizon_days": 5,
                        "confidence": 0.5,
                        "operational_tradeoff_note": "Tradeoff & cost",
                    }
                ]
            }
        )
        self.assertIn("&lt;script&gt;", html_out)
        self.assertNotIn("<script>", html_out)
        self.assertIn("Tradeoff &amp; cost", html_out)


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
