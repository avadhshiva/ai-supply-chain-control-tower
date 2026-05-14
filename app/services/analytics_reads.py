from __future__ import annotations

from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    LowStockItem,
    OperationalRisk,
    OperationalRiskList,
    ScenarioTagBucket,
    ScenarioTagDistribution,
    SupplierReliabilityOverview,
)
from app.models.delivery_metrics import DeliveryMetric
from app.models.inventory import InventoryItem
from app.models.suppliers import Supplier


async def get_inventory_risk_summary(session: AsyncSession) -> InventoryRiskSummary:
    low_stock = InventoryItem.current_stock <= InventoryItem.reorder_point

    stmt = select(
        func.count(InventoryItem.id).label("total_items"),
        _sum_if(low_stock).label("low_stock_items"),
        _sum_if(InventoryItem.scenario_tag == "critical").label("critical_items"),
        _sum_if(InventoryItem.scenario_tag == "overstocked").label("overstocked_items"),
        func.avg(InventoryItem.current_stock / func.nullif(InventoryItem.avg_daily_demand, 0)).label(
            "avg_stock_coverage_days"
        ),
    )
    row = (await session.execute(stmt)).one()

    return InventoryRiskSummary(
        total_items=row.total_items,
        low_stock_items=row.low_stock_items,
        critical_items=row.critical_items,
        overstocked_items=row.overstocked_items,
        avg_stock_coverage_days=row.avg_stock_coverage_days,
    )


async def list_low_stock_items(session: AsyncSession, *, limit: int) -> list[LowStockItem]:
    stock_gap = (InventoryItem.reorder_point - InventoryItem.current_stock).label("stock_gap")
    stmt = (
        select(
            InventoryItem.id,
            InventoryItem.warehouse_id,
            InventoryItem.product_id,
            InventoryItem.current_stock,
            InventoryItem.reorder_point,
            stock_gap,
            InventoryItem.avg_daily_demand,
            InventoryItem.scenario_tag,
        )
        .where(InventoryItem.current_stock <= InventoryItem.reorder_point)
        .order_by(desc(stock_gap), InventoryItem.updated_at.desc(), InventoryItem.id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [LowStockItem(**row._mapping) for row in rows]


async def get_delayed_delivery_summary(session: AsyncSession) -> DelayedDeliverySummary:
    sla_breach = DeliveryMetric.actual_hours > DeliveryMetric.sla_hours
    delay_hours = func.greatest(DeliveryMetric.actual_hours - DeliveryMetric.sla_hours, 0)

    stmt = select(
        func.count(DeliveryMetric.id).label("total_deliveries"),
        _sum_if(DeliveryMetric.status == "delayed").label("delayed_deliveries"),
        _sum_if(DeliveryMetric.status == "failed").label("failed_deliveries"),
        _sum_if(sla_breach).label("sla_breaches"),
        func.avg(delay_hours).label("avg_delay_hours"),
    )
    row = (await session.execute(stmt)).one()

    return DelayedDeliverySummary(
        total_deliveries=row.total_deliveries,
        delayed_deliveries=row.delayed_deliveries,
        failed_deliveries=row.failed_deliveries,
        sla_breaches=row.sla_breaches,
        avg_delay_hours=row.avg_delay_hours,
    )


async def get_supplier_reliability_overview(session: AsyncSession) -> SupplierReliabilityOverview:
    high_risk = (Supplier.reliability_score < 0.70) | (Supplier.on_time_delivery_rate < 0.75)
    reliable = (Supplier.reliability_score >= 0.85) & (Supplier.on_time_delivery_rate >= 0.85)

    stmt = select(
        func.count(Supplier.id).label("total_suppliers"),
        _sum_if(high_risk).label("high_risk_suppliers"),
        _sum_if(reliable).label("reliable_suppliers"),
        func.avg(Supplier.reliability_score).label("avg_reliability_score"),
        func.avg(Supplier.on_time_delivery_rate).label("avg_on_time_delivery_rate"),
        func.avg(Supplier.avg_lead_time_days).label("avg_lead_time_days"),
    )
    row = (await session.execute(stmt)).one()

    return SupplierReliabilityOverview(
        total_suppliers=row.total_suppliers,
        high_risk_suppliers=row.high_risk_suppliers,
        reliable_suppliers=row.reliable_suppliers,
        avg_reliability_score=row.avg_reliability_score,
        avg_on_time_delivery_rate=row.avg_on_time_delivery_rate,
        avg_lead_time_days=row.avg_lead_time_days,
    )


async def get_scenario_tag_distribution(session: AsyncSession) -> ScenarioTagDistribution:
    buckets: dict[str, dict[str, int]] = {}

    for field, rows in (
        ("inventory_items", await _scenario_counts(session, InventoryItem.scenario_tag)),
        ("delivery_metrics", await _scenario_counts(session, DeliveryMetric.scenario_tag)),
        ("suppliers", await _scenario_counts(session, Supplier.scenario_tag)),
    ):
        for scenario_tag, count in rows:
            bucket = buckets.setdefault(
                scenario_tag,
                {"inventory_items": 0, "delivery_metrics": 0, "suppliers": 0},
            )
            bucket[field] = count

    items = [
        ScenarioTagBucket(
            scenario_tag=scenario_tag,
            total=counts["inventory_items"] + counts["delivery_metrics"] + counts["suppliers"],
            **counts,
        )
        for scenario_tag, counts in buckets.items()
    ]
    items.sort(key=lambda item: (-item.total, item.scenario_tag))
    return ScenarioTagDistribution(items=items)


async def list_top_operational_risks(session: AsyncSession, *, limit: int) -> OperationalRiskList:
    risks: list[OperationalRisk] = []
    risks.extend(await _top_inventory_risks(session, limit=limit))
    risks.extend(await _top_delivery_risks(session, limit=limit))
    risks.extend(await _top_supplier_risks(session, limit=limit))

    risks.sort(key=lambda item: (_severity_rank(item.severity), -(item.score or 0), item.label))
    return OperationalRiskList(items=risks[:limit])


def _sum_if(condition) -> object:
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


async def _scenario_counts(session: AsyncSession, column) -> list[tuple[str, int]]:
    stmt = (
        select(column.label("scenario_tag"), func.count().label("item_count"))
        .where(column.is_not(None))
        .group_by(column)
    )
    rows = (await session.execute(stmt)).all()
    return [(row.scenario_tag, row.item_count) for row in rows]


async def _top_inventory_risks(session: AsyncSession, *, limit: int) -> list[OperationalRisk]:
    gap = InventoryItem.reorder_point - InventoryItem.current_stock
    total_gap = func.sum(gap).label("score")
    count = func.count(InventoryItem.id).label("item_count")
    stmt = (
        select(InventoryItem.product_id.label("label"), count, total_gap)
        .where(InventoryItem.current_stock <= InventoryItem.reorder_point)
        .group_by(InventoryItem.product_id)
        .order_by(desc(total_gap), InventoryItem.product_id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()

    return [
        OperationalRisk(
            risk_type="inventory",
            label=f"Low stock for {row.label}",
            severity="high" if row.item_count >= 3 else "medium",
            count=row.item_count,
            score=row.score,
            metric="stock_gap_units",
        )
        for row in rows
    ]


async def _top_delivery_risks(session: AsyncSession, *, limit: int) -> list[OperationalRisk]:
    breach_hours = func.sum(func.greatest(DeliveryMetric.actual_hours - DeliveryMetric.sla_hours, 0)).label(
        "score"
    )
    count = func.count(DeliveryMetric.id).label("item_count")
    stmt = (
        select(DeliveryMetric.route_id.label("label"), count, breach_hours)
        .where(DeliveryMetric.actual_hours > DeliveryMetric.sla_hours)
        .group_by(DeliveryMetric.route_id)
        .order_by(desc(breach_hours), DeliveryMetric.route_id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()

    return [
        OperationalRisk(
            risk_type="delivery",
            label=f"SLA breaches on {row.label}",
            severity="critical" if row.item_count >= 3 else "high",
            count=row.item_count,
            score=row.score,
            metric="breach_hours",
        )
        for row in rows
    ]


async def _top_supplier_risks(session: AsyncSession, *, limit: int) -> list[OperationalRisk]:
    score = (1 - Supplier.reliability_score).label("score")
    stmt = (
        select(Supplier.name.label("label"), score)
        .where(Supplier.reliability_score.is_not(None), Supplier.reliability_score < 0.70)
        .order_by(desc(score), Supplier.name)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()

    return [
        OperationalRisk(
            risk_type="supplier",
            label=f"Low reliability: {row.label}",
            severity="high" if row.score and row.score >= 0.40 else "medium",
            count=1,
            score=row.score,
            metric="reliability_gap",
        )
        for row in rows
    ]


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 4)
