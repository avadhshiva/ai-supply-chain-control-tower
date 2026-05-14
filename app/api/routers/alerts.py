from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession, Pagination
from app.api.schemas.alerts import AlertRead, PaginatedAlertsResponse
from app.services import alerts_reads

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=PaginatedAlertsResponse)
async def list_alerts(
    db: DbSession,
    pagination: Pagination,
    alert_type: str | None = Query(default=None, max_length=64),
    severity: str | None = Query(default=None, max_length=16),
    status_filter: str | None = Query(default=None, max_length=32, alias="status"),
    inventory_id: uuid.UUID | None = None,
) -> PaginatedAlertsResponse:
    items, total = await alerts_reads.list_alerts(
        db,
        offset=pagination.offset,
        limit=pagination.page_size,
        alert_type=alert_type,
        severity=severity,
        status_value=status_filter,
        inventory_id=inventory_id,
    )
    return PaginatedAlertsResponse(
        items=[AlertRead.model_validate(r) for r in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{alert_id}",
    response_model=AlertRead,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Alert not found"}},
)
async def get_alert(alert_id: uuid.UUID, db: DbSession) -> AlertRead:
    row = await alerts_reads.get_alert(db, alert_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return AlertRead.model_validate(row)
