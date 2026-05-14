from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class InventoryItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    warehouse_id: str
    product_id: str
    current_stock: int
    reorder_point: int
    avg_daily_demand: int | None = None
    last_restock_date: date | None = None
    scenario_tag: str | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedInventoryResponse(BaseModel):
    items: list[InventoryItemRead]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
