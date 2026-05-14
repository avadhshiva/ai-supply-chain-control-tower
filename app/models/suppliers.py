from __future__ import annotations

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Supplier(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "suppliers"

    supplier_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    reliability_score: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)
    avg_lead_time_days: Mapped[int | None] = mapped_column(nullable=True)
    on_time_delivery_rate: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)
    scenario_tag: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

