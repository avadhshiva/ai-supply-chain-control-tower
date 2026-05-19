from __future__ import annotations

from app.api.schemas.ai import (
    ConfidenceBand,
    ConfidenceLevel,
    InventoryRebalancingSimulation,
    LaneRerouteSimulation,
    RecoveryProjectedImprovements,
    RecoveryScenariosResult,
    RecoveryStrategy,
    RecoveryStrategyKind,
    SupplierReallocationSimulation,
)

RECOVERY_ENGINE_VERSION = "deterministic-recovery-v1"

# Fixed policy coefficients (versioned with RECOVERY_ENGINE_VERSION).
_LANE_BREACH_MITIGATION = 0.90
_LANE_DELAY_MITIGATION = 0.55
_SUP_RISK_MITIGATION = 0.75
_SUP_DELIVERY_UPLIFT = 0.12
_INV_STOCKOUT_MITIGATION = 0.80

_STRATEGY_ORDER: tuple[RecoveryStrategyKind, ...] = ("conservative", "balanced", "aggressive")

_STRATEGY_PROFILES: dict[RecoveryStrategyKind, dict[str, float | str]] = {
    "conservative": {
        "title": "Conservative stabilization",
        "route_share_cap": 0.40,
        "reroute_success_scale": 0.85,
        "reallocation_scale": 0.50,
        "transfer_scale": 0.75,
        "confidence_scale": 0.88,
        "tradeoff": (
            "Minimizes operational disruption and carrier change volume; slower recovery "
            "but lower execution risk and fewer customer-facing routing changes."
        ),
    },
    "balanced": {
        "title": "Balanced recovery plan",
        "route_share_cap": 0.65,
        "reroute_success_scale": 1.00,
        "reallocation_scale": 0.75,
        "transfer_scale": 1.00,
        "confidence_scale": 1.00,
        "tradeoff": (
            "Balances speed and execution risk across logistics, suppliers, and inventory; "
            "requires coordinated owners but stays within typical surge capacity."
        ),
    },
    "aggressive": {
        "title": "Aggressive recovery push",
        "route_share_cap": 0.90,
        "reroute_success_scale": 1.10,
        "reallocation_scale": 1.00,
        "transfer_scale": 1.15,
        "confidence_scale": 0.92,
        "tradeoff": (
            "Maximizes intervention intensity for fastest stabilization; increases cost, "
            "change fatigue, and short-term service variability during cutover."
        ),
    },
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _normalize_percent(value: float) -> float:
    """Accept 0–1 ratios or 0–100 percentages deterministically."""
    v = float(value)
    if v > 1.0:
        return _clamp01(v / 100.0)
    return _clamp01(v)


def _confidence_band(success_rate: float, coverage: float) -> ConfidenceBand:
    score = _clamp01(success_rate * coverage)
    if score >= 0.70:
        level: ConfidenceLevel = "high"
    elif score >= 0.40:
        level = "medium"
    else:
        level = "low"
    lower = round(score * 0.85, 4)
    upper = round(min(1.0, score * 1.10), 4)
    return ConfidenceBand(level=level, lower_bound=lower, upper_bound=upper)


def simulate_lane_reroute(
    affected_route_share: float,
    reroute_success_rate: float,
    current_sla_breaches: int,
    failed_deliveries: int,
) -> LaneRerouteSimulation:
    """Project logistics recovery from lane rerouting (deterministic, no randomness)."""
    share = _clamp01(affected_route_share)
    success = _clamp01(reroute_success_rate)
    effectiveness = share * success

    breach_base = max(0, int(current_sla_breaches))
    fail_base = max(0, int(failed_deliveries))
    total_pressure = breach_base + fail_base

    projected_breach_reduction = round(breach_base * effectiveness * _LANE_BREACH_MITIGATION, 2)
    projected_delay_reduction = round(total_pressure * effectiveness * _LANE_DELAY_MITIGATION, 2)

    residual = max(0.0, 1.0 - effectiveness)
    stabilization_horizon_days = int(max(3, min(21, round(3 + residual * 14 + fail_base * 0.8))))

    return LaneRerouteSimulation(
        projected_breach_reduction=projected_breach_reduction,
        projected_delay_reduction=projected_delay_reduction,
        stabilization_horizon_days=stabilization_horizon_days,
        confidence_band=_confidence_band(success, share),
    )


def simulate_supplier_reallocation(
    high_risk_supplier_count: int,
    reallocation_percent: float,
    supplier_reliability_score: float,
) -> SupplierReallocationSimulation:
    """Project supplier-segment recovery from volume reallocation."""
    count = max(0, int(high_risk_supplier_count))
    realloc = _normalize_percent(reallocation_percent)
    reliability = _clamp01(supplier_reliability_score)

    exposure = count * (1.0 - reliability)
    projected_supplier_risk_reduction = round(exposure * realloc * _SUP_RISK_MITIGATION, 2)
    projected_delivery_improvement = round(
        min(1.0, reliability * realloc * _SUP_DELIVERY_UPLIFT + count * realloc * 0.04),
        4,
    )
    projected_recovery_horizon_days = int(max(5, min(45, round(10 + count * (1.0 - realloc) * 2.5))))

    return SupplierReallocationSimulation(
        projected_supplier_risk_reduction=projected_supplier_risk_reduction,
        projected_delivery_improvement=projected_delivery_improvement,
        projected_recovery_horizon_days=projected_recovery_horizon_days,
    )


def simulate_inventory_rebalancing(
    critical_inventory_count: int,
    transfer_efficiency: float,
    replenishment_delay_days: float,
) -> InventoryRebalancingSimulation:
    """Project inventory recovery from transfers and replenishment alignment."""
    critical = max(0, int(critical_inventory_count))
    efficiency = _clamp01(transfer_efficiency)
    delay = max(0.0, float(replenishment_delay_days))

    projected_stockout_reduction = round(critical * efficiency * _INV_STOCKOUT_MITIGATION, 2)
    projected_recovery_days = int(max(2, min(30, round(delay * (1.0 - efficiency * 0.5) + critical * 0.6))))
    projected_service_level_stabilization = round(
        min(1.0, 0.55 + efficiency * 0.35 - min(delay, 14.0) * 0.01),
        4,
    )

    return InventoryRebalancingSimulation(
        projected_stockout_reduction=projected_stockout_reduction,
        projected_recovery_days=projected_recovery_days,
        projected_service_level_stabilization=projected_service_level_stabilization,
    )


def _strategy_assumptions(
    kind: RecoveryStrategyKind,
    *,
    route_share: float,
    reroute_success: float,
    realloc: float,
    transfer_eff: float,
) -> list[str]:
    return [
        f"Intervene on up to {round(route_share * 100)}% of affected lanes with "
        f"{round(reroute_success * 100)}% modeled reroute success ({kind}).",
        f"Reallocate {round(realloc * 100)}% of high-risk supplier volume toward reliable cohort.",
        f"Execute inventory transfers at {round(transfer_eff * 100)}% modeled transfer efficiency.",
    ]


def _aggregate_confidence(
    lane: LaneRerouteSimulation,
    supplier: SupplierReallocationSimulation,
    inventory: InventoryRebalancingSimulation,
    scale: float,
) -> float:
    raw = (
        lane.confidence_band.upper_bound * 0.40
        + supplier.projected_delivery_improvement * 0.30
        + inventory.projected_service_level_stabilization * 0.30
    )
    return round(_clamp01(raw * scale), 4)


def build_recovery_scenarios(
    *,
    affected_route_share: float,
    reroute_success_rate: float,
    current_sla_breaches: int,
    failed_deliveries: int,
    high_risk_supplier_count: int,
    reallocation_percent: float,
    supplier_reliability_score: float,
    critical_inventory_count: int,
    transfer_efficiency: float,
    replenishment_delay_days: float,
) -> RecoveryScenariosResult:
    """Build three deterministic recovery strategies: conservative, balanced, aggressive."""
    base_realloc = _normalize_percent(reallocation_percent)
    base_transfer = _clamp01(transfer_efficiency)
    base_reroute = _clamp01(reroute_success_rate)

    strategies: list[RecoveryStrategy] = []
    for kind in _STRATEGY_ORDER:
        profile = _STRATEGY_PROFILES[kind]
        route_share = min(_clamp01(affected_route_share), float(profile["route_share_cap"]))
        reroute_success = _clamp01(base_reroute * float(profile["reroute_success_scale"]))
        realloc = _clamp01(base_realloc * float(profile["reallocation_scale"]))
        transfer_eff = _clamp01(base_transfer * float(profile["transfer_scale"]))

        lane = simulate_lane_reroute(
            route_share, reroute_success, current_sla_breaches, failed_deliveries
        )
        supplier = simulate_supplier_reallocation(
            high_risk_supplier_count, realloc, supplier_reliability_score
        )
        inventory = simulate_inventory_rebalancing(
            critical_inventory_count, transfer_eff, replenishment_delay_days
        )

        recovery_horizon_days = max(
            lane.stabilization_horizon_days,
            supplier.projected_recovery_horizon_days,
            inventory.projected_recovery_days,
        )
        confidence = _aggregate_confidence(
            lane, supplier, inventory, float(profile["confidence_scale"])
        )

        strategies.append(
            RecoveryStrategy(
                kind=kind,
                title=str(profile["title"]),
                operational_assumptions=_strategy_assumptions(
                    kind,
                    route_share=route_share,
                    reroute_success=reroute_success,
                    realloc=realloc,
                    transfer_eff=transfer_eff,
                ),
                projected_improvements=RecoveryProjectedImprovements(
                    breach_reduction=lane.projected_breach_reduction,
                    delay_reduction=lane.projected_delay_reduction,
                    supplier_risk_reduction=supplier.projected_supplier_risk_reduction,
                    delivery_improvement=supplier.projected_delivery_improvement,
                    stockout_reduction=inventory.projected_stockout_reduction,
                    service_level_stabilization=inventory.projected_service_level_stabilization,
                ),
                recovery_horizon_days=recovery_horizon_days,
                confidence=confidence,
                operational_tradeoff_note=str(profile["tradeoff"]),
            )
        )

    return RecoveryScenariosResult(
        engine_version=RECOVERY_ENGINE_VERSION,
        strategies=strategies,
    )


def explain_recovery_coefficients() -> dict[str, float]:
    """Optional helper for operators/tests; not exposed on the wire by default."""
    return {
        "lane_breach_mitigation": _LANE_BREACH_MITIGATION,
        "lane_delay_mitigation": _LANE_DELAY_MITIGATION,
        "supplier_risk_mitigation": _SUP_RISK_MITIGATION,
        "supplier_delivery_uplift": _SUP_DELIVERY_UPLIFT,
        "inventory_stockout_mitigation": _INV_STOCKOUT_MITIGATION,
    }
