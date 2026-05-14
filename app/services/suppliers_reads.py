from __future__ import annotations

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.suppliers import Supplier


async def list_suppliers(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    supplier_code: str | None = None,
    scenario_tag: str | None = None,
    name_contains: str | None = None,
) -> tuple[list[Supplier], int]:
    filters = []
    if supplier_code is not None:
        filters.append(Supplier.supplier_code == supplier_code)
    if scenario_tag is not None:
        filters.append(Supplier.scenario_tag == scenario_tag)
    if name_contains:
        filters.append(Supplier.name.ilike(f"%{name_contains}%"))

    base = select(Supplier)
    count_base = select(func.count()).select_from(Supplier)
    if filters:
        cond = and_(*filters)
        base = base.where(cond)
        count_base = count_base.where(cond)

    total = int((await session.execute(count_base)).scalar_one())

    stmt = base.order_by(Supplier.name.asc(), Supplier.id).offset(offset).limit(limit)
    rows = (await session.scalars(stmt)).all()
    return list(rows), total


async def get_supplier(session: AsyncSession, supplier_id: uuid.UUID) -> Supplier | None:
    return await session.get(Supplier, supplier_id)
