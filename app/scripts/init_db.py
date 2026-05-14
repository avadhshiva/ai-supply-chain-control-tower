from __future__ import annotations

import asyncio
import logging

from app.core.init_db import create_tables


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await create_tables()


if __name__ == "__main__":
    asyncio.run(main())

