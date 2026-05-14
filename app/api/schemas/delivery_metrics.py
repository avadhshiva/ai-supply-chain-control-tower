from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DeliveryMetricRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    delivery_code: str
    route_id: str
    status: str
    sla_hours: int
    actual_hours: int
    scenario_tag: str | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedDeliveryMetricsResponse(BaseModel):
    items: list[DeliveryMetricRead]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
