from __future__ import annotations

import uuid

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerts import Alert


async def list_alerts(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    alert_type: str | None = None,
    severity: str | None = None,
    status_value: str | None = None,
    inventory_id: uuid.UUID | None = None,
) -> tuple[list[Alert], int]:
    filters = []
    if alert_type is not None:
        filters.append(Alert.alert_type == alert_type)
    if severity is not None:
        filters.append(Alert.severity == severity)
    if status_value is not None:
        filters.append(Alert.status == status_value)
    if inventory_id is not None:
        filters.append(Alert.inventory_id == inventory_id)

    base = select(Alert)
    count_base = select(func.count()).select_from(Alert)
    if filters:
        cond = and_(*filters)
        base = base.where(cond)
        count_base = count_base.where(cond)

    total = int((await session.execute(count_base)).scalar_one())

    stmt = base.order_by(Alert.created_at.desc(), Alert.id).offset(offset).limit(limit)
    rows = (await session.scalars(stmt)).all()
    return list(rows), total


async def get_alert(session: AsyncSession, alert_id: uuid.UUID) -> Alert | None:
    return await session.get(Alert, alert_id)
