from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession, Pagination
from app.api.schemas.delivery_metrics import DeliveryMetricRead, PaginatedDeliveryMetricsResponse
from app.services import delivery_metrics_reads

router = APIRouter(prefix="/delivery-metrics", tags=["delivery-metrics"])


@router.get("", response_model=PaginatedDeliveryMetricsResponse)
async def list_delivery_metrics(
    db: DbSession,
    pagination: Pagination,
    route_id: str | None = Query(default=None, max_length=16),
    status_filter: str | None = Query(default=None, max_length=32, alias="status"),
    scenario_tag: str | None = Query(default=None, max_length=32),
) -> PaginatedDeliveryMetricsResponse:
    items, total = await delivery_metrics_reads.list_delivery_metrics(
        db,
        offset=pagination.offset,
        limit=pagination.page_size,
        route_id=route_id,
        status_value=status_filter,
        scenario_tag=scenario_tag,
    )
    return PaginatedDeliveryMetricsResponse(
        items=[DeliveryMetricRead.model_validate(r) for r in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{metric_id}",
    response_model=DeliveryMetricRead,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Delivery metric not found"}},
)
async def get_delivery_metric(metric_id: uuid.UUID, db: DbSession) -> DeliveryMetricRead:
    row = await delivery_metrics_reads.get_delivery_metric(db, metric_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery metric not found",
        )
    return DeliveryMetricRead.model_validate(row)
