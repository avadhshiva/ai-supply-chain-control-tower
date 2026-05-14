from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _decimal_to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


OptionalFloatFromNumeric = Annotated[float | None, BeforeValidator(_decimal_to_float)]


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supplier_code: str
    name: str
    reliability_score: OptionalFloatFromNumeric = None
    avg_lead_time_days: int | None = None
    on_time_delivery_rate: OptionalFloatFromNumeric = None
    scenario_tag: str | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedSuppliersResponse(BaseModel):
    items: list[SupplierRead]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
