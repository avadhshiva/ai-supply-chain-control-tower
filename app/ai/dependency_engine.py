from __future__ import annotations

from dataclasses import dataclass, field

from app.api.schemas.ai import (
    BlastRadiusRanking,
    CascadingRiskStatement,
    ConcentrationHotspot,
    CrossDomainPressureSummary,
    DependencyAnalysisResult,
    DependencyChain,
    DependencyEdgeModel,
    DependencyGraphModel,
    DependencyNodeModel,
    FragileEntity,
)
from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    OperationalRisk,
    OperationalRiskList,
    SupplierReliabilityOverview,
)

DEPENDENCY_ENGINE_VERSION = "deterministic-dependency-v1"

# Fixed cross-domain edge weights (versioned with DEPENDENCY_ENGINE_VERSION).
_EDGE_SUPPLIER_INVENTORY = 0.85
_EDGE_SUPPLIER_DELIVERY = 0.75
_EDGE_INVENTORY_DELIVERY = 0.70
_EDGE_DELIVERY_INVENTORY = 0.55
_ENTITY_DOMAIN_EDGE = 0.90

_DOMAIN_IDS = ("domain:inventory", "domain:delivery", "domain:supplier")
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_SEVERITY_MULT = {"critical": 1.35, "high": 1.15, "medium": 1.0, "low": 0.85}


@dataclass
class _Graph:
    nodes: dict[str, DependencyNodeModel] = field(default_factory=dict)
    adjacency: dict[str, list[tuple[str, float]]] = field(default_factory=dict)

    def add_node(self, node: DependencyNodeModel) -> None:
        self.nodes[node.node_id] = node
        self.adjacency.setdefault(node.node_id, [])

    def add_edge(self, source_id: str, target_id: str, weight: float) -> None:
        w = _clamp01(weight)
        if source_id not in self.nodes or target_id not in self.nodes:
            return
        existing = self.adjacency.setdefault(source_id, [])
        for i, (tid, tw) in enumerate(existing):
            if tid == target_id:
                existing[i] = (tid, max(tw, w))
                return
        existing.append((target_id, w))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _parse_entity_from_risk(risk: OperationalRisk) -> tuple[str, str, str]:
    """Return (domain, entity_id, display_label) from operational risk row."""
    rt = risk.risk_type.strip().lower()
    label = risk.label.strip()
    if rt == "delivery" and label.startswith("SLA breaches on "):
        entity = label[len("SLA breaches on ") :].strip()
        return ("route", entity, entity)
    if rt == "inventory" and label.startswith("Low stock for "):
        entity = label[len("Low stock for ") :].strip()
        return ("product", entity, entity)
    if rt == "supplier" and label.startswith("Low reliability: "):
        entity = label[len("Low reliability: ") :].strip()
        return ("supplier", entity, entity)
    return (rt or "risk", label, label)


def _entity_node_id(domain: str, entity_id: str) -> str:
    return f"{domain}:{entity_id}"


def _risk_row_weight(risk: OperationalRisk) -> float:
    sev = risk.severity.strip().lower()
    mult = _SEVERITY_MULT.get(sev, 0.9)
    score = float(risk.score) if risk.score is not None else 0.0
    count = float(risk.count) if risk.count else 0.0
    base = score if score > 0 else count
    return max(0.0, base) * mult


def _concentration_index(weights: dict[str, float]) -> float:
    total = sum(weights.values())
    if total <= 1e-12 or not weights:
        return 0.0
    shares = [w / total for w in weights.values()]
    n = len(shares)
    hhi = sum(s * s for s in shares)
    if n <= 1:
        return 1.0
    min_hhi = 1.0 / float(n)
    denom = 1.0 - min_hhi
    if denom <= 1e-12:
        return 0.0
    return _clamp01((hhi - min_hhi) / denom)


def _domain_pressure(
    inventory: InventoryRiskSummary,
    deliveries: DelayedDeliverySummary,
    suppliers: SupplierReliabilityOverview,
) -> dict[str, float]:
    inv_total = max(1, inventory.total_items)
    del_total = max(1, deliveries.total_deliveries)
    sup_total = max(1, suppliers.total_suppliers)

    inv_pressure = _clamp01(
        (inventory.critical_items / inv_total) * 0.55
        + (inventory.low_stock_items / inv_total) * 0.35
        + (0.10 if inventory.critical_items > 0 else 0.0)
    )
    del_pressure = _clamp01(
        (deliveries.sla_breaches + deliveries.failed_deliveries) / del_total * 0.70
        + (deliveries.delayed_deliveries / del_total) * 0.30
    )
    sup_pressure = _clamp01(suppliers.high_risk_suppliers / sup_total)

    return {
        "inventory": round(inv_pressure, 4),
        "delivery": round(del_pressure, 4),
        "supplier": round(sup_pressure, 4),
    }


def build_dependency_graph(
    operational_risks: OperationalRiskList,
    domain_pressures: dict[str, float],
) -> DependencyGraphModel:
    """Build a deterministic directed dependency graph from operational risks and domain pressure."""
    graph = _Graph()

    domain_labels = {
        "domain:inventory": ("inventory", "Inventory network"),
        "domain:delivery": ("delivery", "Delivery network"),
        "domain:supplier": ("supplier", "Supplier network"),
    }
    for node_id, (domain, label) in domain_labels.items():
        graph.add_node(DependencyNodeModel(node_id=node_id, domain=domain, label=label))

    cross_edges = (
        ("domain:supplier", "domain:inventory", _EDGE_SUPPLIER_INVENTORY),
        ("domain:supplier", "domain:delivery", _EDGE_SUPPLIER_DELIVERY),
        ("domain:inventory", "domain:delivery", _EDGE_INVENTORY_DELIVERY),
        ("domain:delivery", "domain:inventory", _EDGE_DELIVERY_INVENTORY),
    )
    for src, tgt, w in cross_edges:
        graph.add_edge(src, tgt, w * (0.5 + 0.5 * domain_pressures.get(tgt.split(":")[-1], 0.5)))

    domain_map = {"inventory": "domain:inventory", "delivery": "domain:delivery", "supplier": "domain:supplier"}
    risk_type_to_domain = {
        "inventory": "domain:inventory",
        "delivery": "domain:delivery",
        "supplier": "domain:supplier",
    }

    for risk in operational_risks.items:
        dom_kind, entity_id, display = _parse_entity_from_risk(risk)
        if not entity_id:
            continue
        node_id = _entity_node_id(dom_kind, entity_id)
        rt_domain = risk.risk_type.strip().lower()
        parent_domain = risk_type_to_domain.get(rt_domain, domain_map.get(rt_domain, ""))

        graph.add_node(
            DependencyNodeModel(
                node_id=node_id,
                domain=dom_kind,
                label=display,
            )
        )
        if parent_domain:
            graph.add_edge(node_id, parent_domain, _ENTITY_DOMAIN_EDGE)
            graph.add_edge(parent_domain, node_id, _ENTITY_DOMAIN_EDGE * 0.35)

    nodes = sorted(graph.nodes.values(), key=lambda n: (n.domain, n.node_id))
    edges: list[DependencyEdgeModel] = []
    for src in sorted(graph.adjacency.keys()):
        for tgt, w in sorted(graph.adjacency[src], key=lambda x: x[0]):
            edges.append(DependencyEdgeModel(source_id=src, target_id=tgt, weight=round(w, 4)))

    return DependencyGraphModel(nodes=nodes, edges=edges)


def _graph_from_model(model: DependencyGraphModel) -> _Graph:
    graph = _Graph()
    for node in model.nodes:
        graph.add_node(node)
    for edge in model.edges:
        graph.add_edge(edge.source_id, edge.target_id, edge.weight)
    return graph


def compute_blast_radius(graph_model: DependencyGraphModel) -> list[BlastRadiusRanking]:
    """Compute downstream blast-radius score per entity node (deterministic BFS accumulation)."""
    graph = _graph_from_model(graph_model)
    entity_nodes = [n for n in graph.nodes.values() if not n.node_id.startswith("domain:")]
    rankings: list[BlastRadiusRanking] = []

    for node in sorted(entity_nodes, key=lambda n: n.node_id):
        visited: set[str] = set()
        affected_domains: set[str] = set()
        queue: list[tuple[str, float]] = [(node.node_id, 1.0)]
        blast = 0.0

        while queue:
            queue.sort(key=lambda x: x[0])
            current_id, carry = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)
            if current_id != node.node_id:
                blast += carry * 0.25
                cn = graph.nodes.get(current_id)
                if cn and cn.node_id.startswith("domain:"):
                    affected_domains.add(cn.domain)

            for tgt, w in sorted(graph.adjacency.get(current_id, []), key=lambda x: x[0]):
                if tgt not in visited:
                    queue.append((tgt, carry * w))

        blast = _clamp01(blast / max(1, len(entity_nodes)))

        rankings.append(
            BlastRadiusRanking(
                entity_id=node.node_id.split(":", 1)[-1] if ":" in node.node_id else node.node_id,
                domain=node.domain,
                label=node.label,
                blast_radius_score=round(blast, 4),
                affected_domains=sorted(affected_domains),
            )
        )

    rankings.sort(key=lambda r: (-r.blast_radius_score, r.domain, r.entity_id))
    return rankings


def detect_concentration_hotspots(
    operational_risks: OperationalRiskList,
) -> list[ConcentrationHotspot]:
    """Detect entity-level concentration hotspots per domain using normalized HHI."""
    by_domain: dict[str, dict[str, float]] = {}
    labels: dict[str, str] = {}

    for risk in operational_risks.items:
        dom_kind, entity_id, display = _parse_entity_from_risk(risk)
        if not entity_id:
            continue
        domain_key = risk.risk_type.strip().lower()
        pk = f"{dom_kind}:{entity_id}"
        by_domain.setdefault(domain_key, {})
        by_domain[domain_key][pk] = by_domain[domain_key].get(pk, 0.0) + _risk_row_weight(risk)
        labels[pk] = display

    hotspots: list[ConcentrationHotspot] = []
    for domain in sorted(by_domain.keys()):
        weights = by_domain[domain]
        total = sum(weights.values())
        if total <= 1e-12:
            continue
        conc = _concentration_index(weights)
        ranked = sorted(weights.items(), key=lambda x: (-x[1], x[0]))
        for rank, (pk, w) in enumerate(ranked[:5], start=1):
            dom_kind, entity_id = pk.split(":", 1) if ":" in pk else (domain, pk)
            hotspots.append(
                ConcentrationHotspot(
                    domain=domain,
                    entity_id=entity_id,
                    label=labels.get(pk, entity_id),
                    concentration_index=round(conc, 4),
                    weight_share=round(w / total, 4),
                    rank=rank,
                )
            )

    hotspots.sort(key=lambda h: (-h.concentration_index, -h.weight_share, h.domain, h.rank))
    return hotspots


def infer_cascading_risks(
    graph_model: DependencyGraphModel,
    domain_pressures: dict[str, float],
    operational_risks: OperationalRiskList,
) -> list[CascadingRiskStatement]:
    """Infer deterministic cross-domain cascading risk statements from graph topology and pressure."""
    statements: list[CascadingRiskStatement] = []
    risk_types = {r.risk_type.strip().lower() for r in operational_risks.items}
    sev_high = sum(1 for r in operational_risks.items if r.severity in ("critical", "high"))

    if domain_pressures.get("supplier", 0) >= 0.25 and domain_pressures.get("inventory", 0) >= 0.15:
        statements.append(
            CascadingRiskStatement(
                statement_id="cascade:supplier_inventory",
                source_domain="supplier",
                target_domains=["inventory", "delivery"],
                severity="high" if domain_pressures["supplier"] >= 0.40 else "medium",
                statement=(
                    "Elevated supplier risk is propagating into inventory buffers; "
                    "replenishment lag may amplify downstream fulfillment exposure."
                ),
                chain_entities=_top_entities_for_domain(operational_risks, "supplier", 3),
            )
        )

    if domain_pressures.get("inventory", 0) >= 0.20 and domain_pressures.get("delivery", 0) >= 0.15:
        statements.append(
            CascadingRiskStatement(
                statement_id="cascade:inventory_delivery",
                source_domain="inventory",
                target_domains=["delivery"],
                severity="critical" if domain_pressures["inventory"] >= 0.35 else "high",
                statement=(
                    "Inventory shortfall pressure is coupling with delivery SLA stress; "
                    "stock-constrained lanes face compounded breach risk."
                ),
                chain_entities=_top_entities_for_domain(operational_risks, "inventory", 3),
            )
        )

    if len(risk_types) >= 2 and sev_high >= 2:
        dom_order = sorted(domain_pressures.items(), key=lambda x: -x[1])
        dominant = dom_order[0][0] if dom_order else "operational"
        statements.append(
            CascadingRiskStatement(
                statement_id="cascade:cross_domain",
                source_domain=dominant,
                target_domains=sorted(risk_types - {dominant}),
                severity="critical" if sev_high >= 4 else "high",
                statement=(
                    f"Cross-domain dependency pressure detected: {dominant} stress is cascading "
                    "across inventory, delivery, and supplier layers with correlated high-severity signals."
                ),
                chain_entities=_top_entities_all_domains(operational_risks, 4),
            )
        )

    if domain_pressures.get("delivery", 0) >= 0.30 and "inventory" in risk_types:
        statements.append(
            CascadingRiskStatement(
                statement_id="cascade:delivery_feedback",
                source_domain="delivery",
                target_domains=["inventory"],
                severity="high",
                statement=(
                    "Delivery SLA degradation is feeding back into inventory allocation; "
                    "delayed inbound movements extend stock coverage gaps."
                ),
                chain_entities=_top_entities_for_domain(operational_risks, "delivery", 3),
            )
        )

    statements.sort(key=lambda s: (_SEVERITY_RANK.get(s.severity, 9), s.statement_id))
    return statements


def _top_entities_for_domain(risks: OperationalRiskList, domain: str, k: int) -> list[str]:
    items = [r for r in risks.items if r.risk_type.strip().lower() == domain]
    ranked = sorted(items, key=lambda r: (-_risk_row_weight(r), r.label))
    out: list[str] = []
    for r in ranked[:k]:
        _, entity_id, _ = _parse_entity_from_risk(r)
        if entity_id and entity_id not in out:
            out.append(entity_id)
    return out


def _top_entities_all_domains(risks: OperationalRiskList, k: int) -> list[str]:
    ranked = sorted(risks.items, key=lambda r: (-_risk_row_weight(r), r.label))
    out: list[str] = []
    for r in ranked[:k]:
        _, entity_id, _ = _parse_entity_from_risk(r)
        if entity_id and entity_id not in out:
            out.append(entity_id)
    return out


def rank_fragile_entities(
    blast_rankings: list[BlastRadiusRanking],
    operational_risks: OperationalRiskList,
    domain_pressures: dict[str, float],
) -> list[FragileEntity]:
    """Rank entities by combined fragility: blast radius, local risk weight, and domain pressure."""
    risk_by_entity: dict[str, tuple[OperationalRisk, float]] = {}
    for risk in operational_risks.items:
        dom_kind, entity_id, _ = _parse_entity_from_risk(risk)
        pk = _entity_node_id(dom_kind, entity_id)
        w = _risk_row_weight(risk)
        if pk not in risk_by_entity or w > risk_by_entity[pk][1]:
            risk_by_entity[pk] = (risk, w)

    blast_map = {_entity_node_id(b.domain, b.entity_id): b for b in blast_rankings}
    domain_for_kind = {"route": "delivery", "product": "inventory", "supplier": "supplier"}

    fragile: list[FragileEntity] = []
    seen: set[str] = set()

    for ranking in blast_rankings:
        node_id = _entity_node_id(ranking.domain, ranking.entity_id)
        seen.add(node_id)
        risk, local_w = risk_by_entity.get(node_id, (None, 0.0))
        dom_pressure = domain_pressures.get(
            domain_for_kind.get(ranking.domain, ranking.domain), 0.0
        )
        local_norm = _clamp01(local_w / 200.0) if local_w > 0 else 0.0
        fragility = _clamp01(
            ranking.blast_radius_score * 0.45
            + local_norm * 0.35
            + dom_pressure * 0.20
        )
        severity = risk.severity if risk else "medium"
        fragile.append(
            FragileEntity(
                entity_id=ranking.entity_id,
                domain=ranking.domain,
                label=ranking.label,
                fragility_score=round(fragility, 4),
                blast_radius_score=ranking.blast_radius_score,
                severity=severity,
            )
        )

    for pk, (risk, local_w) in sorted(risk_by_entity.items()):
        if pk in seen:
            continue
        dom_kind, entity_id, display = _parse_entity_from_risk(risk)
        dom_pressure = domain_pressures.get(risk.risk_type.strip().lower(), 0.0)
        fragility = _clamp01(_clamp01(local_w / 200.0) * 0.65 + dom_pressure * 0.35)
        fragile.append(
            FragileEntity(
                entity_id=entity_id,
                domain=dom_kind,
                label=display,
                fragility_score=round(fragility, 4),
                blast_radius_score=0.0,
                severity=risk.severity,
            )
        )

    fragile.sort(key=lambda f: (-f.fragility_score, _SEVERITY_RANK.get(f.severity, 9), f.domain, f.entity_id))
    return fragile[:10]


def summarize_cross_domain_pressure(
    domain_pressures: dict[str, float],
    operational_risks: OperationalRiskList,
) -> CrossDomainPressureSummary:
    """Summarize aggregate cross-domain operational pressure from analytics-derived scores."""
    inv = domain_pressures.get("inventory", 0.0)
    deliv = domain_pressures.get("delivery", 0.0)
    sup = domain_pressures.get("supplier", 0.0)
    combined = _clamp01((inv + deliv + sup) / 3.0 + 0.08 * max(0, len({r.risk_type for r in operational_risks.items}) - 1))

    ordered = sorted(
        [("inventory", inv), ("delivery", deliv), ("supplier", sup)],
        key=lambda x: (-x[1], x[0]),
    )
    dominant = ordered[0][0]

    if combined >= 0.55:
        tone = "elevated cross-domain stress"
    elif combined >= 0.30:
        tone = "moderate cross-domain coupling"
    else:
        tone = "contained cross-domain pressure"

    summary = (
        f"{tone.capitalize()}: {dominant} domain leads "
        f"(inventory {inv:.0%}, delivery {deliv:.0%}, supplier {sup:.0%}). "
        f"{len(operational_risks.items)} operational risk signals monitored."
    )

    return CrossDomainPressureSummary(
        inventory_pressure=round(inv, 4),
        delivery_pressure=round(deliv, 4),
        supplier_pressure=round(sup, 4),
        combined_pressure=round(combined, 4),
        dominant_domain=dominant,
        summary=summary,
    )


def _extract_dependency_chains(
    graph_model: DependencyGraphModel,
    domain_pressures: dict[str, float],
) -> list[DependencyChain]:
    """Extract top deterministic cross-domain dependency chains through domain nodes."""
    canonical_paths = (
        (["domain:supplier", "domain:inventory", "domain:delivery"], "chain:supplier_inventory_delivery"),
        (["domain:inventory", "domain:delivery"], "chain:inventory_delivery"),
        (["domain:supplier", "domain:delivery"], "chain:supplier_delivery"),
        (["domain:delivery", "domain:inventory"], "chain:delivery_inventory"),
    )
    node_labels = {n.node_id: n.label for n in graph_model.nodes}
    chains: list[DependencyChain] = []

    for path, chain_id in canonical_paths:
        pressure = 1.0
        for nid in path:
            dom = nid.split(":")[-1]
            pressure *= 0.5 + 0.5 * domain_pressures.get(dom, 0.0)
        chains.append(
            DependencyChain(
                chain_id=chain_id,
                path=path,
                path_labels=[node_labels.get(nid, nid) for nid in path],
                chain_pressure=round(_clamp01(pressure), 4),
            )
        )

    entity_chains: list[DependencyChain] = []
    entity_nodes = [n for n in graph_model.nodes if not n.node_id.startswith("domain:")]
    for node in sorted(entity_nodes, key=lambda n: n.node_id)[:6]:
        dom = node.domain
        domain_target = {
            "route": "domain:delivery",
            "product": "domain:inventory",
            "supplier": "domain:supplier",
        }.get(dom, f"domain:{dom}")
        path = [node.node_id, domain_target]
        if dom == "product" and domain_pressures.get("delivery", 0) > 0.1:
            path.append("domain:delivery")
        elif dom == "supplier" and domain_pressures.get("inventory", 0) > 0.1:
            path.extend(["domain:inventory", "domain:delivery"])
        pressure = _clamp01(sum(domain_pressures.get(p.split(":")[-1], 0) for p in path) / len(path))
        entity_chains.append(
            DependencyChain(
                chain_id=f"chain:entity:{node.node_id}",
                path=path,
                path_labels=[node_labels.get(p, p.split(":")[-1]) for p in path],
                chain_pressure=round(pressure, 4),
            )
        )

    all_chains = chains + entity_chains
    all_chains.sort(key=lambda c: (-c.chain_pressure, c.chain_id))
    return all_chains[:12]


def build_dependency_analysis(
    inventory: InventoryRiskSummary,
    deliveries: DelayedDeliverySummary,
    suppliers: SupplierReliabilityOverview,
    operational_risks: OperationalRiskList,
) -> DependencyAnalysisResult:
    """Orchestrate full deterministic dependency intelligence from analytics inputs only."""
    domain_pressures = _domain_pressure(inventory, deliveries, suppliers)
    graph = build_dependency_graph(operational_risks, domain_pressures)
    blast = compute_blast_radius(graph)
    hotspots = detect_concentration_hotspots(operational_risks)
    cascading = infer_cascading_risks(graph, domain_pressures, operational_risks)
    fragile = rank_fragile_entities(blast, operational_risks, domain_pressures)
    pressure_summary = summarize_cross_domain_pressure(domain_pressures, operational_risks)
    chains = _extract_dependency_chains(graph, domain_pressures)

    return DependencyAnalysisResult(
        engine_version=DEPENDENCY_ENGINE_VERSION,
        top_fragile_entities=fragile,
        blast_radius_rankings=blast,
        concentration_hotspots=hotspots,
        cascading_risk_statements=cascading,
        cross_domain_pressure_summary=pressure_summary,
        dependency_chains=chains,
    )
