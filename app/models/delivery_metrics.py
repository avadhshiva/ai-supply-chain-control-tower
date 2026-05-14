from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DeliveryMetric(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "delivery_metrics"

    delivery_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    route_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sla_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_tag: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

