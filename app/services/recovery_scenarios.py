from __future__ import annotations

from app.ai.recovery_simulator import build_recovery_scenarios
from app.api.schemas.ai import RecoveryScenariosResult
from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    SupplierReliabilityOverview,
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def build_recovery_scenarios_from_analytics(
    inventory: InventoryRiskSummary,
    deliveries: DelayedDeliverySummary,
    suppliers: SupplierReliabilityOverview,
) -> RecoveryScenariosResult:
    """Derive recovery simulator inputs deterministically from analytics aggregates."""
    total_deliveries = max(1, deliveries.total_deliveries)
    total_items = max(1, inventory.total_items)
    total_suppliers = max(1, suppliers.total_suppliers)

    sla_breaches = deliveries.sla_breaches
    failed_deliveries = deliveries.failed_deliveries
    high_risk_suppliers = suppliers.high_risk_suppliers
    critical_inventory = inventory.critical_items

    affected_route_share = _clamp01((sla_breaches + failed_deliveries) / total_deliveries)

    reliability = suppliers.avg_reliability_score
    on_time = suppliers.avg_on_time_delivery_rate
    if reliability is not None and on_time is not None:
        reroute_success_rate = _clamp01((reliability + on_time) / 2.0)
    elif reliability is not None:
        reroute_success_rate = _clamp01(reliability)
    elif on_time is not None:
        reroute_success_rate = _clamp01(on_time)
    else:
        reroute_success_rate = 0.72

    reallocation_percent = min(100.0, (high_risk_suppliers / total_suppliers) * 100.0)
    supplier_reliability_score = _clamp01(reliability if reliability is not None else 0.75)

    inventory_pressure = critical_inventory / total_items
    coverage_days = inventory.avg_stock_coverage_days
    coverage_factor = _clamp01(coverage_days / 14.0) if coverage_days is not None else 0.55
    transfer_efficiency = _clamp01(0.45 + coverage_factor * 0.40 - inventory_pressure * 0.25)

    lead_delay = suppliers.avg_lead_time_days or 5.0
    delivery_delay = (deliveries.avg_delay_hours or 0.0) / 24.0
    replenishment_delay_days = max(0.0, max(lead_delay, delivery_delay))

    return build_recovery_scenarios(
        affected_route_share=affected_route_share,
        reroute_success_rate=reroute_success_rate,
        current_sla_breaches=sla_breaches,
        failed_deliveries=failed_deliveries,
        high_risk_supplier_count=high_risk_suppliers,
        reallocation_percent=reallocation_percent,
        supplier_reliability_score=supplier_reliability_score,
        critical_inventory_count=critical_inventory,
        transfer_efficiency=transfer_efficiency,
        replenishment_delay_days=replenishment_delay_days,
    )
