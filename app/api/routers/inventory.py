from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession, Pagination
from app.api.schemas.inventory import InventoryItemRead, PaginatedInventoryResponse
from app.services import inventory_reads

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("", response_model=PaginatedInventoryResponse)
async def list_inventory(
    db: DbSession,
    pagination: Pagination,
    warehouse_id: str | None = Query(default=None, max_length=16),
    product_id: str | None = Query(default=None, max_length=16),
    scenario_tag: str | None = Query(default=None, max_length=32),
) -> PaginatedInventoryResponse:
    items, total = await inventory_reads.list_inventory_items(
        db,
        offset=pagination.offset,
        limit=pagination.page_size,
        warehouse_id=warehouse_id,
        product_id=product_id,
        scenario_tag=scenario_tag,
    )
    return PaginatedInventoryResponse(
        items=[InventoryItemRead.model_validate(r) for r in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{item_id}",
    response_model=InventoryItemRead,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Inventory row not found"}},
)
async def get_inventory(item_id: uuid.UUID, db: DbSession) -> InventoryItemRead:
    row = await inventory_reads.get_inventory_item(db, item_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")
    return InventoryItemRead.model_validate(row)
