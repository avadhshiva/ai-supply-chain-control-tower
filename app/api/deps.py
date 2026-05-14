from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageParams
from app.core.database import get_db_session

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_page_params(
    page: Annotated[int, Query(ge=1, le=1_000_000, description="1-based page index")] = 1,
    page_size: Annotated[
        int,
        Query(ge=1, le=MAX_PAGE_SIZE, description="Items per page"),
    ] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


Pagination = Annotated[PageParams, Depends(get_page_params)]
