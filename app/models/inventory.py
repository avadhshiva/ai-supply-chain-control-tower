from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class InventoryItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "product_id", name="uq_inventory_warehouse_product"),
    )

    warehouse_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    current_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reorder_point: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_daily_demand: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_restock_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    scenario_tag: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

