from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    LowStockItem,
    OperationalRiskList,
    ScenarioTagDistribution,
    SupplierReliabilityOverview,
)
from app.services import analytics_reads

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/inventory-risk-summary", response_model=InventoryRiskSummary)
async def get_inventory_risk_summary(db: DbSession) -> InventoryRiskSummary:
    return await analytics_reads.get_inventory_risk_summary(db)


@router.get("/low-stock-items", response_model=list[LowStockItem])
async def list_low_stock_items(
    db: DbSession,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[LowStockItem]:
    return await analytics_reads.list_low_stock_items(db, limit=limit)


@router.get("/delayed-delivery-summary", response_model=DelayedDeliverySummary)
async def get_delayed_delivery_summary(db: DbSession) -> DelayedDeliverySummary:
    return await analytics_reads.get_delayed_delivery_summary(db)


@router.get("/supplier-reliability-overview", response_model=SupplierReliabilityOverview)
async def get_supplier_reliability_overview(db: DbSession) -> SupplierReliabilityOverview:
    return await analytics_reads.get_supplier_reliability_overview(db)


@router.get("/scenario-tag-distribution", response_model=ScenarioTagDistribution)
async def get_scenario_tag_distribution(db: DbSession) -> ScenarioTagDistribution:
    return await analytics_reads.get_scenario_tag_distribution(db)


@router.get("/top-operational-risks", response_model=OperationalRiskList)
async def list_top_operational_risks(
    db: DbSession,
    limit: int = Query(default=10, ge=1, le=25),
) -> OperationalRiskList:
    return await analytics_reads.list_top_operational_risks(db, limit=limit)
