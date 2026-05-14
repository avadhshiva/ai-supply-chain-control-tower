from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alert_type: str
    severity: str
    status: str
    title: str
    description: str | None = None
    inventory_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedAlertsResponse(BaseModel):
    items: list[AlertRead]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
