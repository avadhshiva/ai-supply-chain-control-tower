from __future__ import annotations

import unittest

from app.ai.dependency_engine import (
    DEPENDENCY_ENGINE_VERSION,
    build_dependency_analysis,
    build_dependency_graph,
    compute_blast_radius,
    detect_concentration_hotspots,
    infer_cascading_risks,
    rank_fragile_entities,
    summarize_cross_domain_pressure,
)
from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    OperationalRisk,
    OperationalRiskList,
    SupplierReliabilityOverview,
)


def _sample_risks() -> OperationalRiskList:
    return OperationalRiskList(
        items=[
            OperationalRisk(
                risk_type="delivery",
                label="SLA breaches on RT-A",
                severity="critical",
                count=5,
                score=120.0,
                metric="breach_hours",
            ),
            OperationalRisk(
                risk_type="delivery",
                label="SLA breaches on RT-B",
                severity="high",
                count=3,
                score=80.0,
                metric="breach_hours",
            ),
            OperationalRisk(
                risk_type="inventory",
                label="Low stock for SKU-100",
                severity="high",
                count=2,
                score=45.0,
                metric="stock_gap_units",
            ),
            OperationalRisk(
                risk_type="supplier",
                label="Low reliability: Acme Parts",
                severity="high",
                count=1,
                score=0.45,
                metric="reliability_gap",
            ),
        ]
    )


def _sample_analytics() -> tuple[InventoryRiskSummary, DelayedDeliverySummary, SupplierReliabilityOverview]:
    return (
        InventoryRiskSummary(
            total_items=50,
            low_stock_items=8,
            critical_items=4,
            overstocked_items=1,
            avg_stock_coverage_days=6.0,
        ),
        DelayedDeliverySummary(
            total_deliveries=100,
            delayed_deliveries=15,
            failed_deliveries=3,
            sla_breaches=12,
            avg_delay_hours=28.0,
        ),
        SupplierReliabilityOverview(
            total_suppliers=20,
            high_risk_suppliers=5,
            reliable_suppliers=10,
            avg_reliability_score=0.68,
            avg_on_time_delivery_rate=0.72,
            avg_lead_time_days=7.0,
        ),
    )


class BuildDependencyGraphTests(unittest.TestCase):
    def test_graph_includes_domain_nodes_and_edges(self) -> None:
        pressures = {"inventory": 0.3, "delivery": 0.4, "supplier": 0.25}
        graph = build_dependency_graph(_sample_risks(), pressures)
        node_ids = {n.node_id for n in graph.nodes}
        self.assertIn("domain:inventory", node_ids)
        self.assertIn("domain:delivery", node_ids)
        self.assertIn("domain:supplier", node_ids)
        self.assertTrue(any(e.source_id == "domain:supplier" for e in graph.edges))

    def test_same_inputs_produce_identical_graph(self) -> None:
        pressures = {"inventory": 0.2, "delivery": 0.3, "supplier": 0.1}
        a = build_dependency_graph(_sample_risks(), pressures)
        b = build_dependency_graph(_sample_risks(), pressures)
        self.assertEqual(a.model_dump(), b.model_dump())


class BlastRadiusTests(unittest.TestCase):
    def test_blast_scores_are_bounded(self) -> None:
        pressures = {"inventory": 0.3, "delivery": 0.5, "supplier": 0.2}
        graph = build_dependency_graph(_sample_risks(), pressures)
        rankings = compute_blast_radius(graph)
        self.assertTrue(rankings)
        for row in rankings:
            self.assertGreaterEqual(row.blast_radius_score, 0.0)
            self.assertLessEqual(row.blast_radius_score, 1.0)

    def test_rankings_are_stable_and_descending(self) -> None:
        pressures = {"inventory": 0.3, "delivery": 0.5, "supplier": 0.2}
        graph = build_dependency_graph(_sample_risks(), pressures)
        first = compute_blast_radius(graph)
        second = compute_blast_radius(graph)
        self.assertEqual([r.model_dump() for r in first], [r.model_dump() for r in second])
        scores = [r.blast_radius_score for r in first]
        self.assertEqual(scores, sorted(scores, reverse=True))


class ConcentrationHotspotTests(unittest.TestCase):
    def test_hotspots_ordered_by_concentration_then_share(self) -> None:
        hotspots = detect_concentration_hotspots(_sample_risks())
        self.assertTrue(hotspots)
        for spot in hotspots:
            self.assertGreaterEqual(spot.concentration_index, 0.0)
            self.assertLessEqual(spot.concentration_index, 1.0)
            self.assertGreaterEqual(spot.weight_share, 0.0)
            self.assertLessEqual(spot.weight_share, 1.0)
        conc_values = [h.concentration_index for h in hotspots]
        self.assertEqual(conc_values, sorted(conc_values, reverse=True))

    def test_delivery_domain_has_rank_one_hotspot(self) -> None:
        hotspots = detect_concentration_hotspots(_sample_risks())
        delivery = [h for h in hotspots if h.domain == "delivery" and h.rank == 1]
        self.assertEqual(len(delivery), 1)
        self.assertEqual(delivery[0].entity_id, "RT-A")


class CascadingRiskTests(unittest.TestCase):
    def test_cross_domain_statement_when_multi_domain_pressure(self) -> None:
        pressures = {"inventory": 0.35, "delivery": 0.40, "supplier": 0.30}
        graph = build_dependency_graph(_sample_risks(), pressures)
        statements = infer_cascading_risks(graph, pressures, _sample_risks())
        ids = {s.statement_id for s in statements}
        self.assertIn("cascade:cross_domain", ids)

    def test_statements_are_deterministic(self) -> None:
        pressures = {"inventory": 0.35, "delivery": 0.40, "supplier": 0.30}
        graph = build_dependency_graph(_sample_risks(), pressures)
        a = infer_cascading_risks(graph, pressures, _sample_risks())
        b = infer_cascading_risks(graph, pressures, _sample_risks())
        self.assertEqual([s.model_dump() for s in a], [s.model_dump() for s in b])


class FragileEntityTests(unittest.TestCase):
    def test_fragile_entities_bounded_and_ranked(self) -> None:
        inv, deliv, sup = _sample_analytics()
        result = build_dependency_analysis(inv, deliv, sup, _sample_risks())
        fragile = result.top_fragile_entities
        self.assertTrue(fragile)
        for ent in fragile:
            self.assertGreaterEqual(ent.fragility_score, 0.0)
            self.assertLessEqual(ent.fragility_score, 1.0)
        scores = [e.fragility_score for e in fragile]
        self.assertEqual(scores, sorted(scores, reverse=True))


class CrossDomainPressureTests(unittest.TestCase):
    def test_pressure_summary_bounded(self) -> None:
        inv, deliv, sup = _sample_analytics()
        result = build_dependency_analysis(inv, deliv, sup, _sample_risks())
        summary = result.cross_domain_pressure_summary
        for field in (
            summary.inventory_pressure,
            summary.delivery_pressure,
            summary.supplier_pressure,
            summary.combined_pressure,
        ):
            self.assertGreaterEqual(field, 0.0)
            self.assertLessEqual(field, 1.0)
        self.assertIn(summary.dominant_domain, ("inventory", "delivery", "supplier"))


class BuildDependencyAnalysisTests(unittest.TestCase):
    def test_full_analysis_is_deterministic(self) -> None:
        inv, deliv, sup = _sample_analytics()
        risks = _sample_risks()
        a = build_dependency_analysis(inv, deliv, sup, risks)
        b = build_dependency_analysis(inv, deliv, sup, risks)
        self.assertEqual(a.model_dump(), b.model_dump())
        self.assertEqual(a.engine_version, DEPENDENCY_ENGINE_VERSION)

    def test_dependency_chains_have_consistent_paths(self) -> None:
        inv, deliv, sup = _sample_analytics()
        result = build_dependency_analysis(inv, deliv, sup, _sample_risks())
        for chain in result.dependency_chains:
            self.assertEqual(len(chain.path), len(chain.path_labels))
            self.assertGreaterEqual(chain.chain_pressure, 0.0)
            self.assertLessEqual(chain.chain_pressure, 1.0)

    def test_rank_fragile_entities_matches_top_list_subset(self) -> None:
        inv, deliv, sup = _sample_analytics()
        result = build_dependency_analysis(inv, deliv, sup, _sample_risks())
        pressures = {
            "inventory": result.cross_domain_pressure_summary.inventory_pressure,
            "delivery": result.cross_domain_pressure_summary.delivery_pressure,
            "supplier": result.cross_domain_pressure_summary.supplier_pressure,
        }
        graph = build_dependency_graph(_sample_risks(), pressures)
        blast = compute_blast_radius(graph)
        ranked = rank_fragile_entities(blast, _sample_risks(), pressures)
        self.assertEqual(
            [e.entity_id for e in ranked[:5]],
            [e.entity_id for e in result.top_fragile_entities[:5]],
        )
