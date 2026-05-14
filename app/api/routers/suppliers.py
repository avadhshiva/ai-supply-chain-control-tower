from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSession, Pagination
from app.api.schemas.suppliers import PaginatedSuppliersResponse, SupplierRead
from app.services import suppliers_reads

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=PaginatedSuppliersResponse)
async def list_suppliers(
    db: DbSession,
    pagination: Pagination,
    supplier_code: str | None = Query(default=None, max_length=32),
    scenario_tag: str | None = Query(default=None, max_length=32),
    name_contains: str | None = Query(default=None, max_length=200),
) -> PaginatedSuppliersResponse:
    items, total = await suppliers_reads.list_suppliers(
        db,
        offset=pagination.offset,
        limit=pagination.page_size,
        supplier_code=supplier_code,
        scenario_tag=scenario_tag,
        name_contains=name_contains,
    )
    return PaginatedSuppliersResponse(
        items=[SupplierRead.model_validate(r) for r in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get(
    "/{supplier_id}",
    response_model=SupplierRead,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Supplier not found"}},
)
async def get_supplier(supplier_id: uuid.UUID, db: DbSession) -> SupplierRead:
    row = await suppliers_reads.get_supplier(db, supplier_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return SupplierRead.model_validate(row)
