from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field


def _optional_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


OptionalFloat = Annotated[float | None, BeforeValidator(_optional_float)]


class InventoryRiskSummary(BaseModel):
    total_items: int = Field(ge=0)
    low_stock_items: int = Field(ge=0)
    critical_items: int = Field(ge=0)
    overstocked_items: int = Field(ge=0)
    avg_stock_coverage_days: OptionalFloat = None


class LowStockItem(BaseModel):
    id: uuid.UUID
    warehouse_id: str
    product_id: str
    current_stock: int
    reorder_point: int
    stock_gap: int = Field(ge=0)
    avg_daily_demand: int | None = None
    scenario_tag: str | None = None


class DelayedDeliverySummary(BaseModel):
    total_deliveries: int = Field(ge=0)
    delayed_deliveries: int = Field(ge=0)
    failed_deliveries: int = Field(ge=0)
    sla_breaches: int = Field(ge=0)
    avg_delay_hours: OptionalFloat = None


class SupplierReliabilityOverview(BaseModel):
    total_suppliers: int = Field(ge=0)
    high_risk_suppliers: int = Field(ge=0)
    reliable_suppliers: int = Field(ge=0)
    avg_reliability_score: OptionalFloat = None
    avg_on_time_delivery_rate: OptionalFloat = None
    avg_lead_time_days: OptionalFloat = None


class ScenarioTagBucket(BaseModel):
    scenario_tag: str
    inventory_items: int = Field(ge=0)
    delivery_metrics: int = Field(ge=0)
    suppliers: int = Field(ge=0)
    total: int = Field(ge=0)


class ScenarioTagDistribution(BaseModel):
    items: list[ScenarioTagBucket]


class OperationalRisk(BaseModel):
    risk_type: str
    label: str
    severity: str
    count: int = Field(ge=0)
    score: OptionalFloat = None
    metric: str


class OperationalRiskList(BaseModel):
    items: list[OperationalRisk]
