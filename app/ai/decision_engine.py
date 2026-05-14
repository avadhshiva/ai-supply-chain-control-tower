from __future__ import annotations

from app.ai import simulation_engine as sim
from app.api.schemas.ai import (
    EvidenceSignal,
    ExplainabilityDetail,
    KPIInfluence,
    RecommendationItem,
    WeightedContributor,
)
from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    OperationalRiskList,
    ScenarioTagBucket,
    ScenarioTagDistribution,
    SupplierReliabilityOverview,
)

ENGINE_VERSION = "deterministic-rules-v2"

# Policy thresholds (fixed, versioned with ENGINE_VERSION).
_INV_LOW_STOCK_RATIO_HIGH = 0.08
_INV_LOW_STOCK_RATIO_MEDIUM = 0.02
_DEL_BREACH_RATIO_CRITICAL = 0.25
_DEL_BREACH_RATIO_HIGH = 0.12
_DEL_DELAY_RATIO_HIGH = 0.18
_SUP_HIGH_RISK_RATIO_HIGH = 0.20
_SUP_AVG_RELIABILITY_WARN = 0.78
_SUP_AVG_ON_TIME_WARN = 0.80


def build_recommendations(
    inventory: InventoryRiskSummary,
    deliveries: DelayedDeliverySummary,
    suppliers: SupplierReliabilityOverview,
    scenarios: ScenarioTagDistribution,
    operational_risks: OperationalRiskList,
) -> list[RecommendationItem]:
    """Derive ordered, explainable recommendations from analytics aggregates."""
    recs: list[RecommendationItem] = []
    recs.extend(_inventory_recommendations(inventory))
    recs.extend(_delivery_recommendations(deliveries))
    recs.extend(_supplier_recommendations(suppliers))
    recs.extend(_operational_recommendations(scenarios, operational_risks))
    recs.sort(key=_sort_key)
    return [
        _attach_decision_intel(r, inventory, deliveries, suppliers, scenarios, operational_risks)
        for r in recs
    ]


def _sort_key(item: RecommendationItem) -> tuple[int, int, str]:
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    category_order = {"inventory": 0, "delivery": 1, "supplier": 2, "operational": 3}
    return (severity_order.get(item.severity, 9), category_order.get(item.category, 9), item.id)


def _inventory_recommendations(inv: InventoryRiskSummary) -> list[RecommendationItem]:
    if inv.total_items <= 0:
        return []

    low_ratio = inv.low_stock_items / inv.total_items
    evidence = [
        EvidenceSignal(name="total_items", value=inv.total_items),
        EvidenceSignal(name="low_stock_items", value=inv.low_stock_items),
        EvidenceSignal(name="critical_items", value=inv.critical_items),
        EvidenceSignal(
            name="low_stock_ratio",
            value=round(low_ratio, 4),
            comparison=f"policy_high≥{_INV_LOW_STOCK_RATIO_HIGH}, policy_medium≥{_INV_LOW_STOCK_RATIO_MEDIUM}",
        ),
    ]
    if inv.avg_stock_coverage_days is not None:
        evidence.append(
            EvidenceSignal(name="avg_stock_coverage_days", value=round(inv.avg_stock_coverage_days, 2))
        )

    if inv.critical_items > 0:
        severity = "critical"
        title = "Critical inventory exposure detected"
        summary = (
            f"{inv.critical_items} item(s) are tagged critical and require immediate supply or "
            "allocation action before service levels degrade."
        )
        actions = [
            "Expedite replenishment or inbound transfers for critical SKUs.",
            "Validate demand spikes versus forecast and adjust safety stock where confirmed.",
            "Communicate stock risk to sales and fulfillment leads with ETA ranges.",
        ]
        rationale = (
            "Rule inventory:critical_stock fires when critical_items>0 because critical-tagged stock "
            "is treated as highest operational priority in this policy set."
        )
        return [
            RecommendationItem(
                id="inventory:critical_stock",
                category="inventory",
                severity=severity,
                title=title,
                summary=summary,
                actions=actions,
                evidence=evidence,
                rationale=rationale,
            )
        ]

    if inv.low_stock_items <= 0:
        return []

    if low_ratio >= _INV_LOW_STOCK_RATIO_HIGH or inv.low_stock_items >= 5:
        severity = "high"
    elif low_ratio >= _INV_LOW_STOCK_RATIO_MEDIUM or inv.low_stock_items >= 2:
        severity = "medium"
    else:
        severity = "low"

    return [
        RecommendationItem(
            id="inventory:low_stock",
            category="inventory",
            severity=severity,
            title="Low inventory risk across monitored items",
            summary=(
                f"{inv.low_stock_items} of {inv.total_items} tracked items are at or below reorder "
                "points; prioritize replenishment planning for the largest stock gaps first."
            ),
            actions=[
                "Run replenishment for SKUs below reorder point, ordered by projected stockout date.",
                "Review reorder points and lead times where breaches repeat for the same SKU/location.",
                "Align promotional demand with available cover to avoid thinning buffers unintentionally.",
            ],
            evidence=evidence,
            rationale=(
                "Rule inventory:low_stock uses low_stock_items, critical_items==0, and the ratio "
                "low_stock_items/total_items against fixed ratio thresholds to classify severity."
            ),
        )
    ]


def _delivery_recommendations(dm: DelayedDeliverySummary) -> list[RecommendationItem]:
    if dm.total_deliveries <= 0:
        return []

    breach_ratio = dm.sla_breaches / dm.total_deliveries
    delay_ratio = dm.delayed_deliveries / dm.total_deliveries

    if dm.delayed_deliveries == 0 and dm.sla_breaches == 0 and dm.failed_deliveries == 0:
        return []

    evidence = [
        EvidenceSignal(name="total_deliveries", value=dm.total_deliveries),
        EvidenceSignal(name="delayed_deliveries", value=dm.delayed_deliveries),
        EvidenceSignal(name="failed_deliveries", value=dm.failed_deliveries),
        EvidenceSignal(name="sla_breaches", value=dm.sla_breaches),
        EvidenceSignal(
            name="breach_ratio",
            value=round(breach_ratio, 4),
            comparison=f"critical≥{_DEL_BREACH_RATIO_CRITICAL}, high≥{_DEL_BREACH_RATIO_HIGH}",
        ),
        EvidenceSignal(
            name="delay_ratio",
            value=round(delay_ratio, 4),
            comparison=f"high_delay≥{_DEL_DELAY_RATIO_HIGH}",
        ),
    ]
    if dm.avg_delay_hours is not None:
        evidence.append(EvidenceSignal(name="avg_delay_hours", value=round(dm.avg_delay_hours, 2)))

    if dm.failed_deliveries > 0:
        severity: str = "critical"
    elif breach_ratio >= _DEL_BREACH_RATIO_CRITICAL or delay_ratio >= _DEL_DELAY_RATIO_HIGH:
        severity = "critical" if breach_ratio >= _DEL_BREACH_RATIO_CRITICAL else "high"
    elif breach_ratio >= _DEL_BREACH_RATIO_HIGH or delay_ratio >= 0.10:
        severity = "high"
    elif breach_ratio > 0 or delay_ratio > 0:
        severity = "medium"
    else:
        severity = "low"

    return [
        RecommendationItem(
            id="delivery:sla_and_delays",
            category="delivery",
            severity=severity,
            title="Delivery performance pressure (delays and SLA adherence)",
            summary=(
                f"Observed {dm.delayed_deliveries} delayed, {dm.sla_breaches} SLA breaches, and "
                f"{dm.failed_deliveries} failed deliveries over {dm.total_deliveries} tracked movements."
            ),
            actions=[
                "Segment lanes with repeated SLA breaches and assign carrier or routing mitigations.",
                "Tighten milestone tracking for high-value or time-sensitive routes.",
                "Pair delayed lanes with inventory actions where downstream stockouts are projected.",
            ],
            evidence=evidence,
            rationale=(
                "Rule delivery:sla_and_delays prioritizes failed deliveries as critical, then breach "
                "and delay ratios against fixed thresholds, using only aggregate delivery metrics."
            ),
        )
    ]


def _supplier_recommendations(sup: SupplierReliabilityOverview) -> list[RecommendationItem]:
    if sup.total_suppliers <= 0:
        return []

    high_ratio = sup.high_risk_suppliers / sup.total_suppliers
    evidence = [
        EvidenceSignal(name="total_suppliers", value=sup.total_suppliers),
        EvidenceSignal(name="high_risk_suppliers", value=sup.high_risk_suppliers),
        EvidenceSignal(name="reliable_suppliers", value=sup.reliable_suppliers),
        EvidenceSignal(
            name="high_risk_ratio",
            value=round(high_ratio, 4),
            comparison=f"high≥{_SUP_HIGH_RISK_RATIO_HIGH}",
        ),
    ]
    if sup.avg_reliability_score is not None:
        evidence.append(
            EvidenceSignal(
                name="avg_reliability_score",
                value=round(sup.avg_reliability_score, 4),
                comparison=f"warn≤{_SUP_AVG_RELIABILITY_WARN}",
            )
        )
    if sup.avg_on_time_delivery_rate is not None:
        evidence.append(
            EvidenceSignal(
                name="avg_on_time_delivery_rate",
                value=round(sup.avg_on_time_delivery_rate, 4),
                comparison=f"warn≤{_SUP_AVG_ON_TIME_WARN}",
            )
        )
    if sup.avg_lead_time_days is not None:
        evidence.append(EvidenceSignal(name="avg_lead_time_days", value=round(sup.avg_lead_time_days, 2)))

    if sup.high_risk_suppliers <= 0:
        avg_rel = sup.avg_reliability_score
        avg_ot = sup.avg_on_time_delivery_rate
        if (avg_rel is not None and avg_rel < _SUP_AVG_RELIABILITY_WARN) or (
            avg_ot is not None and avg_ot < _SUP_AVG_ON_TIME_WARN
        ):
            severity = "medium"
            return [
                RecommendationItem(
                    id="supplier:portfolio_avg",
                    category="supplier",
                    severity=severity,
                    title="Supplier portfolio averages indicate elevated fragility",
                    summary=(
                        "No suppliers meet the isolated high-risk filter, but portfolio averages suggest "
                        "weakening reliability or punctuality relative to policy targets."
                    ),
                    actions=[
                        "Refresh scorecards for mid-tier suppliers with volatile on-time performance.",
                        "Introduce dual sourcing or backup agreements for SKUs tied to the weakest lanes.",
                        "Negotiate lead-time buffers or milestone-based incentives where feasible.",
                    ],
                    evidence=evidence,
                    rationale=(
                        "Rule supplier:portfolio_avg triggers when high_risk_suppliers==0 but average "
                        "reliability or on-time performance falls below configured warn thresholds."
                    ),
                )
            ]
        return []

    if sup.high_risk_suppliers >= 3 or high_ratio >= _SUP_HIGH_RISK_RATIO_HIGH:
        severity = "high"
    else:
        severity = "medium"

    return [
        RecommendationItem(
            id="supplier:unreliable_segment",
            category="supplier",
            severity=severity,
            title="Unreliable supplier segment needs governance focus",
            summary=(
                f"{sup.high_risk_suppliers} supplier(s) exceed the configured high-risk thresholds on "
                "reliability and punctuality; treat as a concentrated remediation cohort."
            ),
            actions=[
                "Run joint improvement plans with owners, metrics, and exit criteria for each high-risk supplier.",
                "Rebalance volume toward reliable_suppliers cohort where contracts and capacity allow.",
                "Tighten inbound QA and contingency stock for parts exclusively tied to at-risk suppliers.",
            ],
            evidence=evidence,
            rationale=(
                "Rule supplier:unreliable_segment uses high_risk_suppliers counts and their ratio to "
                "total_suppliers, mirroring the analytics service definition of high-risk suppliers."
            ),
        )
    ]


def _bucket_for_tag(items: list[ScenarioTagBucket], tag: str) -> ScenarioTagBucket | None:
    for b in items:
        if b.scenario_tag == tag:
            return b
    return None


def _operational_recommendations(
    scenarios: ScenarioTagDistribution,
    risks: OperationalRiskList,
) -> list[RecommendationItem]:
    out: list[RecommendationItem] = []
    critical_bucket = _bucket_for_tag(scenarios.items, "critical")
    critical_entities = 0
    if critical_bucket is not None:
        critical_entities = critical_bucket.inventory_items + critical_bucket.delivery_metrics + critical_bucket.suppliers

    critical_risk_count = sum(1 for r in risks.items if r.severity == "critical")

    if critical_entities <= 0 and critical_risk_count <= 0:
        return out

    evidence: list[EvidenceSignal] = []
    if critical_bucket is not None:
        evidence.extend(
            [
                EvidenceSignal(name="scenario_tag", value=critical_bucket.scenario_tag),
                EvidenceSignal(name="critical_inventory_items", value=critical_bucket.inventory_items),
                EvidenceSignal(name="critical_delivery_metrics", value=critical_bucket.delivery_metrics),
                EvidenceSignal(name="critical_suppliers", value=critical_bucket.suppliers),
            ]
        )
    evidence.append(EvidenceSignal(name="top_risk_critical_count", value=critical_risk_count))

    severity: str = "critical" if critical_entities > 0 or critical_risk_count >= 2 else "high"
    summary_parts: list[str] = []
    if critical_entities > 0:
        summary_parts.append(
            f"The 'critical' scenario tag appears across {critical_entities} combined entity records "
            "(inventory, deliveries, suppliers)."
        )
    if critical_risk_count > 0:
        summary_parts.append(
            f"{critical_risk_count} of the top consolidated operational risk entries are classified critical."
        )
    summary = " ".join(summary_parts) if summary_parts else "Critical operational pattern detected."

    out.append(
        RecommendationItem(
            id="operational:critical_scenario",
            category="operational",
            severity=severity,
            title="Critical operational scenario requires cross-functional command",
            summary=summary,
            actions=[
                "Stand up a short daily war-room until critical tags and SLA breaches trend down.",
                "Pair inventory, logistics, and supplier owners on a single prioritized recovery backlog.",
                "Publish customer- and site-level impact assumptions with explicit decision owners.",
            ],
            evidence=evidence,
            rationale=(
                "Rule operational:critical_scenario combines scenario_tag_distribution for tag 'critical' "
                "with the count of critical-severity rows in top_operational_risks."
            ),
        ),
    )
    return out


_NAME_WEIGHT_HINTS: tuple[tuple[str, float], ...] = (
    ("breach", 0.26),
    ("delay", 0.22),
    ("fail", 0.24),
    ("critical", 0.24),
    ("risk", 0.20),
    ("ratio", 0.18),
    ("stock", 0.19),
    ("reorder", 0.17),
    ("reliability", 0.21),
    ("on_time", 0.19),
    ("scenario", 0.20),
    ("operational", 0.16),
)


def _operational_cross_domain_signal(
    scenarios: ScenarioTagDistribution,
    risks: OperationalRiskList,
    rec_category: str,
) -> bool:
    crit = _bucket_for_tag(scenarios.items, "critical")
    domains = 0
    if crit is not None:
        if crit.inventory_items > 0:
            domains += 1
        if crit.delivery_metrics > 0:
            domains += 1
        if crit.suppliers > 0:
            domains += 1
    risk_types = {str(r.risk_type).strip().lower() for r in risks.items}
    multi_risk = len({t for t in risk_types if t}) >= 2
    if rec_category == "operational":
        return domains >= 2 or multi_risk
    return domains >= 2 or (domains >= 1 and multi_risk)


def _first_route_from_risks(risks: OperationalRiskList) -> str | None:
    for row in risks.items:
        if str(row.risk_type).strip().lower() == "delivery" and row.label.startswith("SLA breaches on "):
            token = row.label[len("SLA breaches on ") :].strip()
            if token:
                return token
    return None


def _breach_ratio_trend_series(dm: DelayedDeliverySummary) -> list[float]:
    td = max(1, dm.total_deliveries)
    br = dm.sla_breaches / float(td)
    shape = (0.72, 0.78, 0.83, 0.87, 0.91, 0.96, 1.0)
    return [max(0.0, br * float(s)) for s in shape]


def _weighted_contributors_from_evidence(evidence: list[EvidenceSignal]) -> list[WeightedContributor]:
    scored: list[tuple[str, float]] = []
    for ev in evidence:
        nm = str(ev.name).strip().lower()
        w = 0.09
        for needle, wt in _NAME_WEIGHT_HINTS:
            if needle in nm:
                w = max(w, wt)
        scored.append((str(ev.name), w))
    total = sum(w for _, w in scored) or 1.0
    ranked = sorted(scored, key=lambda x: (-x[1], x[0]))
    return [WeightedContributor(name=n, weight=round(w / total, 4)) for n, w in ranked[:10]]


def _delivery_kpi_influences(dm: DelayedDeliverySummary) -> list[KPIInfluence]:
    td = max(1, dm.total_deliveries)
    w_b = dm.sla_breaches / float(td)
    w_d = dm.delayed_deliveries / float(td)
    w_f = dm.failed_deliveries / float(td)
    s = w_b + w_d + w_f or 1.0
    return [
        KPIInfluence(kpi_id="sla_breach_rate", influence_pct=round(100.0 * w_b / s, 1)),
        KPIInfluence(kpi_id="delay_rate", influence_pct=round(100.0 * w_d / s, 1)),
        KPIInfluence(kpi_id="failure_rate", influence_pct=round(100.0 * w_f / s, 1)),
    ]


def _inventory_kpi_influences(inv: InventoryRiskSummary) -> list[KPIInfluence]:
    ti = max(1, inv.total_items)
    w_c = inv.critical_items / float(ti)
    w_l = inv.low_stock_items / float(ti)
    w_o = inv.overstocked_items / float(ti)
    s = w_c + w_l + w_o or 1.0
    return [
        KPIInfluence(kpi_id="critical_share", influence_pct=round(100.0 * w_c / s, 1)),
        KPIInfluence(kpi_id="low_stock_share", influence_pct=round(100.0 * w_l / s, 1)),
        KPIInfluence(kpi_id="overstock_share", influence_pct=round(100.0 * w_o / s, 1)),
    ]


def _supplier_kpi_influences(sup: SupplierReliabilityOverview) -> list[KPIInfluence]:
    ts = max(1, sup.total_suppliers)
    w_h = sup.high_risk_suppliers / float(ts)
    w_rel = sup.avg_reliability_score if sup.avg_reliability_score is not None else 0.0
    w_ot = sup.avg_on_time_delivery_rate if sup.avg_on_time_delivery_rate is not None else 0.0
    s = w_h + w_rel + w_ot or 1.0
    return [
        KPIInfluence(kpi_id="high_risk_share", influence_pct=round(100.0 * w_h / s, 1)),
        KPIInfluence(kpi_id="avg_reliability", influence_pct=round(100.0 * w_rel / s, 1)),
        KPIInfluence(kpi_id="avg_on_time", influence_pct=round(100.0 * w_ot / s, 1)),
    ]


def _metric_series_for_rec_fixed(
    rec: RecommendationItem,
    inv: InventoryRiskSummary,
    dm: DelayedDeliverySummary,
    sup: SupplierReliabilityOverview,
    scenarios: ScenarioTagDistribution,
) -> list[float]:
    if rec.category == "delivery" and dm.total_deliveries > 0:
        return _breach_ratio_trend_series(dm)
    if rec.category == "inventory" and inv.total_items > 0:
        low_ratio = inv.low_stock_items / float(inv.total_items)
        crit = inv.critical_items / float(inv.total_items)
        return [max(0.0, low_ratio * s + crit * 0.35) for s in (0.72, 0.78, 0.83, 0.87, 0.91, 0.96, 1.0)]
    if rec.category == "supplier" and sup.total_suppliers > 0:
        if rec.id == "supplier:portfolio_avg" and (
            sup.avg_reliability_score is not None or sup.avg_on_time_delivery_rate is not None
        ):
            rel = float(sup.avg_reliability_score or sup.avg_on_time_delivery_rate or 0.0)
            factors = [1.03 - i * (0.03 / 6.0) for i in range(7)]
            tail = factors[-1] or 1.0
            return [max(0.01, min(1.0, rel * (f / tail))) for f in factors]
        hr = sup.high_risk_suppliers / float(sup.total_suppliers)
        return [max(0.0, hr * float(s)) for s in (0.72, 0.78, 0.83, 0.87, 0.91, 0.96, 1.0)]
    crit = _bucket_for_tag(scenarios.items, "critical")
    if crit is None:
        return [0.05, 0.06, 0.07, 0.08, 0.085, 0.09, 0.095]
    pressure = min(
        1.0,
        0.03 * (crit.inventory_items + crit.delivery_metrics + crit.suppliers),
    )
    return [max(1e-6, pressure * float(s)) for s in (0.55, 0.62, 0.68, 0.74, 0.8, 0.88, 1.0)]


def _higher_is_bad_for_rec(rec: RecommendationItem) -> bool:
    if rec.category == "supplier" and rec.id == "supplier:portfolio_avg":
        return False
    return True


def _accountability_defaults(rec: RecommendationItem) -> tuple[str, str, str]:
    if rec.category == "delivery":
        return "Logistics Ops", "24h", "Escalate if unresolved next cycle."
    if rec.category == "inventory":
        return "Inventory Planning", "48h", "Escalate if unresolved next cycle."
    if rec.category == "supplier":
        return "Supplier Ops", "72h", "Escalate if unresolved next cycle."
    return "Ops leadership", "24h", "Escalate if unresolved next cycle."


def _dominant_trigger(rec: RecommendationItem) -> str:
    return {
        "inventory": "inventory_levels",
        "delivery": "delivery_metrics",
        "supplier": "supplier_scores",
        "operational": "risk_register",
    }.get(rec.category, "aggregated_signals")


def _causal_chain_for_rec(rec: RecommendationItem) -> list[str]:
    if rec.category == "delivery":
        return [
            "In-lane delay accumulation increases milestone slip density",
            "Slip density couples into SLA breach timing and backlog",
            "Breach ratio trends against the escalation policy band",
        ]
    if rec.category == "inventory":
        return [
            "Demand or supply variance consumes safety stock faster than replenishment",
            "Low-stock population expands while critical tags concentrate on bottleneck SKUs",
            "Coverage days compress until service risk crosses governance thresholds",
        ]
    if rec.category == "supplier":
        return [
            "Supplier punctuality and reliability scores drift from contracted baselines",
            "High-risk cohort share rises in the active supplier portfolio",
            "Inbound variability propagates to inventory and delivery exception load",
        ]
    return [
        "Critical scenario tags align across inventory, delivery, and supplier records",
        "Top operational risk register shows elevated critical-severity concentration",
        "Cross-domain coupling increases coordination load on the command cadence",
    ]


def _attach_decision_intel(
    rec: RecommendationItem,
    inv: InventoryRiskSummary,
    dm: DelayedDeliverySummary,
    sup: SupplierReliabilityOverview,
    scenarios: ScenarioTagDistribution,
    risks: OperationalRiskList,
) -> RecommendationItem:
    cross = _operational_cross_domain_signal(scenarios, risks, rec.category)
    base_series = _metric_series_for_rec_fixed(rec, inv, dm, sup, scenarios)
    vol = sim.infer_metric_trend_state(base_series, higher_is_bad=_higher_is_bad_for_rec(rec))
    conf_level, conf_num = sim.compute_confidence_score(
        evidence_count=len(rec.evidence),
        metric_series=base_series,
        cross_domain_agreement=cross,
        volatility_state=vol,
    )
    owner, target, esc = _accountability_defaults(rec)

    explain = ExplainabilityDetail(
        weighted_contributors=_weighted_contributors_from_evidence(rec.evidence),
        kpi_influences=[],
        causal_chain=_causal_chain_for_rec(rec),
        dominant_trigger_source=_dominant_trigger(rec),
    )

    tti: str | None = None
    sim_lines: list[str] = []

    if rec.id == "delivery:sla_and_delays" and dm.total_deliveries > 0:
        br = dm.sla_breaches / float(dm.total_deliveries)
        crs = _breach_ratio_trend_series(dm)
        tc = sim.project_threshold_crossing(
            current_value=br,
            threshold=sim.delivery_breach_escalation_threshold(),
            metric_series=crs,
            higher_is_bad=True,
        )
        tti = str(tc["summary"])
        delay_sim = sim.simulate_delay_reduction(
            total_deliveries=dm.total_deliveries,
            delayed_deliveries=dm.delayed_deliveries,
            sla_breaches=dm.sla_breaches,
            delay_reduction_pct=0.30,
        )
        route = _first_route_from_risks(risks)
        pct = abs(float(delay_sim["exposure_delta_pct"]))
        if route:
            sim_lines.append(f"Reducing {route} delays by 30% lowers projected breach exposure by {pct:.0f}%.")
        else:
            sim_lines.append(
                f"Reducing aggregate delay incidence by 30% lowers projected breach exposure by {pct:.0f}%."
            )
        sr = sim.simulate_supplier_recovery(
            high_risk_suppliers=sup.high_risk_suppliers,
            total_suppliers=sup.total_suppliers,
            avg_reliability_score=sup.avg_reliability_score,
            reliability_improvement=0.05,
        )
        sim_lines.append(str(sr["summary"]))
        ir = sim.simulate_inventory_replenishment(
            low_stock_items=inv.low_stock_items,
            total_items=max(1, inv.total_items),
            avg_stock_coverage_days=inv.avg_stock_coverage_days,
            replenishment_acceleration_pct=0.20,
        )
        sim_lines.append(str(ir["summary"]))
        explain.kpi_influences = _delivery_kpi_influences(dm)

    elif rec.id in ("inventory:critical_stock", "inventory:low_stock") and inv.total_items > 0:
        low_ratio = inv.low_stock_items / float(inv.total_items)
        crs = [low_ratio * float(s) for s in (0.72, 0.78, 0.83, 0.87, 0.91, 0.96, 1.0)]
        thr = sim.inventory_threshold_for_low_stock_ratio(inv.total_items, inv.low_stock_items)
        tc = sim.project_threshold_crossing(
            current_value=low_ratio,
            threshold=thr,
            metric_series=crs,
            higher_is_bad=True,
            risk_descriptor="Low-stock coverage risk",
            drift_descriptor="stockout drift",
        )
        tti = str(tc["summary"])
        sim_lines.append(
            str(
                sim.simulate_inventory_replenishment(
                    low_stock_items=inv.low_stock_items,
                    total_items=inv.total_items,
                    avg_stock_coverage_days=inv.avg_stock_coverage_days,
                    replenishment_acceleration_pct=0.25,
                )["summary"]
            )
        )
        if dm.total_deliveries > 0:
            dr = sim.simulate_delay_reduction(
                total_deliveries=dm.total_deliveries,
                delayed_deliveries=dm.delayed_deliveries,
                sla_breaches=dm.sla_breaches,
                delay_reduction_pct=0.25,
            )
            sim_lines.append("Inbound latency coupling: " + str(dr["summary"]))
        sr = sim.simulate_supplier_recovery(
            high_risk_suppliers=sup.high_risk_suppliers,
            total_suppliers=sup.total_suppliers,
            avg_reliability_score=sup.avg_reliability_score,
            reliability_improvement=0.04,
        )
        sim_lines.append(str(sr["summary"]))
        explain.kpi_influences = _inventory_kpi_influences(inv)

    elif rec.id == "supplier:portfolio_avg" and sup.total_suppliers > 0:
        rel = float(sup.avg_reliability_score or sup.avg_on_time_delivery_rate or 0.75)
        crs = _metric_series_for_rec_fixed(rec, inv, dm, sup, scenarios)
        tc = sim.project_threshold_crossing(
            current_value=rel,
            threshold=_SUP_AVG_RELIABILITY_WARN,
            metric_series=crs,
            higher_is_bad=False,
            risk_descriptor="Portfolio reliability",
            drift_descriptor="reliability erosion",
        )
        tti = str(tc["summary"])
        sim_lines.append(
            str(
                sim.simulate_supplier_recovery(
                    high_risk_suppliers=sup.high_risk_suppliers,
                    total_suppliers=sup.total_suppliers,
                    avg_reliability_score=sup.avg_reliability_score,
                    reliability_improvement=0.06,
                )["summary"]
            )
        )
        ir = sim.simulate_inventory_replenishment(
            low_stock_items=inv.low_stock_items,
            total_items=max(1, inv.total_items),
            avg_stock_coverage_days=inv.avg_stock_coverage_days,
            replenishment_acceleration_pct=0.15,
        )
        sim_lines.append("Buffer coupling: " + str(ir["summary"]))
        if dm.total_deliveries > 0:
            dr = sim.simulate_delay_reduction(
                total_deliveries=dm.total_deliveries,
                delayed_deliveries=dm.delayed_deliveries,
                sla_breaches=dm.sla_breaches,
                delay_reduction_pct=0.20,
            )
            sim_lines.append(str(dr["summary"]))
        explain.kpi_influences = _supplier_kpi_influences(sup)

    elif rec.id == "supplier:unreliable_segment" and sup.total_suppliers > 0:
        hr_ratio = sup.high_risk_suppliers / float(sup.total_suppliers)
        crs = [hr_ratio * float(s) for s in (0.72, 0.78, 0.83, 0.87, 0.91, 0.96, 1.0)]
        tc = sim.project_threshold_crossing(
            current_value=hr_ratio,
            threshold=_SUP_HIGH_RISK_RATIO_HIGH,
            metric_series=crs,
            higher_is_bad=True,
            risk_descriptor="High-risk supplier cohort share",
            drift_descriptor="supplier fragility drift",
        )
        tti = str(tc["summary"])
        sim_lines.append(
            str(
                sim.simulate_supplier_recovery(
                    high_risk_suppliers=sup.high_risk_suppliers,
                    total_suppliers=sup.total_suppliers,
                    avg_reliability_score=sup.avg_reliability_score,
                    reliability_improvement=0.06,
                )["summary"]
            )
        )
        ir = sim.simulate_inventory_replenishment(
            low_stock_items=inv.low_stock_items,
            total_items=max(1, inv.total_items),
            avg_stock_coverage_days=inv.avg_stock_coverage_days,
            replenishment_acceleration_pct=0.15,
        )
        sim_lines.append("Buffer coupling: " + str(ir["summary"]))
        if dm.total_deliveries > 0:
            dr = sim.simulate_delay_reduction(
                total_deliveries=dm.total_deliveries,
                delayed_deliveries=dm.delayed_deliveries,
                sla_breaches=dm.sla_breaches,
                delay_reduction_pct=0.20,
            )
            sim_lines.append(str(dr["summary"]))
        explain.kpi_influences = _supplier_kpi_influences(sup)

    elif rec.id == "operational:critical_scenario":
        crit = _bucket_for_tag(scenarios.items, "critical")
        crc = sum(1 for r in risks.items if r.severity == "critical")
        ce = 0
        if crit is not None:
            ce = crit.inventory_items + crit.delivery_metrics + crit.suppliers
        pressure = min(1.0, 0.11 * float(ce) + 0.09 * float(crc))
        crs = [max(1e-6, pressure * float(s)) for s in (0.55, 0.62, 0.68, 0.74, 0.8, 0.88, 1.0)]
        tc = sim.project_threshold_crossing(
            current_value=pressure,
            threshold=0.55,
            metric_series=crs,
            higher_is_bad=True,
            risk_descriptor="Operational exception pressure",
            drift_descriptor="critical-tag diffusion",
            period_label="cycle",
            max_horizon=14,
        )
        tti = str(tc["summary"])
        sim_lines.append(
            str(
                sim.simulate_delay_reduction(
                    total_deliveries=max(1, dm.total_deliveries),
                    delayed_deliveries=dm.delayed_deliveries,
                    sla_breaches=dm.sla_breaches,
                    delay_reduction_pct=0.18,
                )["summary"]
            )
        )
        sim_lines.append(
            str(
                sim.simulate_supplier_recovery(
                    high_risk_suppliers=sup.high_risk_suppliers,
                    total_suppliers=max(1, sup.total_suppliers),
                    avg_reliability_score=sup.avg_reliability_score,
                    reliability_improvement=0.05,
                )["summary"]
            )
        )
        sim_lines.append(
            str(
                sim.simulate_inventory_replenishment(
                    low_stock_items=inv.low_stock_items,
                    total_items=max(1, inv.total_items),
                    avg_stock_coverage_days=inv.avg_stock_coverage_days,
                    replenishment_acceleration_pct=0.18,
                )["summary"]
            )
        )
        explain.kpi_influences = [
            KPIInfluence(kpi_id="critical_tag_entities", influence_pct=round(min(100.0, 10.0 + 12.0 * ce), 1)),
            KPIInfluence(kpi_id="critical_risk_rows", influence_pct=round(min(100.0, 10.0 + 22.0 * crc), 1)),
        ]
        ssum = sum(k.influence_pct for k in explain.kpi_influences) or 1.0
        explain.kpi_influences = [
            KPIInfluence(kpi_id=k.kpi_id, influence_pct=round(100.0 * k.influence_pct / ssum, 1))
            for k in explain.kpi_influences
        ]

    return rec.model_copy(
        update={
            "confidence": conf_level,
            "confidence_score": conf_num,
            "owner": owner,
            "target_window": target,
            "escalation_trigger": esc,
            "time_to_impact": tti,
            "simulation_insights": sim_lines[:4],
            "explainability": explain,
        }
    )


def explain_thresholds() -> dict[str, float | int]:
    """Optional helper for operators/tests; not exposed on the wire by default."""
    return {
        "inventory_low_stock_ratio_high": _INV_LOW_STOCK_RATIO_HIGH,
        "inventory_low_stock_ratio_medium": _INV_LOW_STOCK_RATIO_MEDIUM,
        "delivery_breach_ratio_critical": _DEL_BREACH_RATIO_CRITICAL,
        "delivery_breach_ratio_high": _DEL_BREACH_RATIO_HIGH,
        "delivery_delay_ratio_high": _DEL_DELAY_RATIO_HIGH,
        "supplier_high_risk_ratio_high": _SUP_HIGH_RISK_RATIO_HIGH,
        "supplier_avg_reliability_warn": _SUP_AVG_RELIABILITY_WARN,
        "supplier_avg_on_time_warn": _SUP_AVG_ON_TIME_WARN,
    }
