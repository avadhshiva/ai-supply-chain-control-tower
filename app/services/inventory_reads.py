from __future__ import annotations

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import InventoryItem


async def list_inventory_items(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    warehouse_id: str | None = None,
    product_id: str | None = None,
    scenario_tag: str | None = None,
) -> tuple[list[InventoryItem], int]:
    filters = []
    if warehouse_id is not None:
        filters.append(InventoryItem.warehouse_id == warehouse_id)
    if product_id is not None:
        filters.append(InventoryItem.product_id == product_id)
    if scenario_tag is not None:
        filters.append(InventoryItem.scenario_tag == scenario_tag)

    base = select(InventoryItem)
    count_base = select(func.count()).select_from(InventoryItem)
    if filters:
        cond = and_(*filters)
        base = base.where(cond)
        count_base = count_base.where(cond)

    total = int((await session.execute(count_base)).scalar_one())

    stmt = (
        base.order_by(InventoryItem.updated_at.desc(), InventoryItem.id)
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.scalars(stmt)).all()
    return list(rows), total


async def get_inventory_item(session: AsyncSession, item_id: uuid.UUID) -> InventoryItem | None:
    return await session.get(InventoryItem, item_id)
