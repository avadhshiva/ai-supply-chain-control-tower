from __future__ import annotations

from app.api.schemas.ai import EvidenceSignal, RecommendationItem
from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    OperationalRiskList,
    ScenarioTagBucket,
    ScenarioTagDistribution,
    SupplierReliabilityOverview,
)

ENGINE_VERSION = "deterministic-rules-v1"

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
    return recs


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
