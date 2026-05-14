from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.database import get_engine
from app.models.base import Base

# Ensure models are imported so metadata is populated.
from app import models as _models  # noqa: F401

logger = logging.getLogger(__name__)


async def create_tables(db_engine: AsyncEngine | None = None) -> None:
    db_engine = db_engine or get_engine()
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("db_tables_created")

