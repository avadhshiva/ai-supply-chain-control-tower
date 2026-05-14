from __future__ import annotations

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery_metrics import DeliveryMetric


async def list_delivery_metrics(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    route_id: str | None = None,
    status_value: str | None = None,
    scenario_tag: str | None = None,
) -> tuple[list[DeliveryMetric], int]:
    filters = []
    if route_id is not None:
        filters.append(DeliveryMetric.route_id == route_id)
    if status_value is not None:
        filters.append(DeliveryMetric.status == status_value)
    if scenario_tag is not None:
        filters.append(DeliveryMetric.scenario_tag == scenario_tag)

    base = select(DeliveryMetric)
    count_base = select(func.count()).select_from(DeliveryMetric)
    if filters:
        cond = and_(*filters)
        base = base.where(cond)
        count_base = count_base.where(cond)

    total = int((await session.execute(count_base)).scalar_one())

    stmt = (
        base.order_by(DeliveryMetric.updated_at.desc(), DeliveryMetric.id)
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.scalars(stmt)).all()
    return list(rows), total


async def get_delivery_metric(session: AsyncSession, metric_id: uuid.UUID) -> DeliveryMetric | None:
    return await session.get(DeliveryMetric, metric_id)
