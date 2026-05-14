from __future__ import annotations

import asyncio
import csv
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import get_sessionmaker
from app.models.delivery_metrics import DeliveryMetric
from app.models.inventory import InventoryItem
from app.models.suppliers import Supplier

logger = logging.getLogger(__name__)

DATA_DIR = Path("pre-cursor-kit/07_data")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


async def ingest_suppliers(csv_path: Path) -> int:
    rows: list[dict] = []

    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for r in reader:
            rows.append(
                {
                    "supplier_code": r["supplier_id"],
                    "name": r["supplier_name"],
                    "reliability_score": float(r["reliability_score"])
                    if r.get("reliability_score")
                    else None,
                    "avg_lead_time_days": int(r["avg_lead_time_days"])
                    if r.get("avg_lead_time_days")
                    else None,
                    "on_time_delivery_rate": float(r["on_time_delivery_rate"])
                    if r.get("on_time_delivery_rate")
                    else None,
                    "scenario_tag": r.get("scenario_tag"),
                }
            )

    if not rows:
        return 0

    async with get_sessionmaker()() as session:
        stmt = insert(Supplier).values(rows)

        stmt = stmt.on_conflict_do_update(
            index_elements=[Supplier.supplier_code],
            set_={
                "name": stmt.excluded.name,
                "reliability_score": stmt.excluded.reliability_score,
                "avg_lead_time_days": stmt.excluded.avg_lead_time_days,
                "on_time_delivery_rate": stmt.excluded.on_time_delivery_rate,
                "scenario_tag": stmt.excluded.scenario_tag,
            },
        )

        result = await session.execute(stmt)
        await session.commit()

    affected = result.rowcount or 0

    logger.info(
        "ingested_suppliers",
        extra={
            "path": str(csv_path),
            "rows": len(rows),
            "affected": affected,
        },
    )

    return affected


async def ingest_inventory(csv_path: Path) -> int:
    deduped: dict[tuple[str, str], dict] = {}

    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for r in reader:
            key = (r["warehouse_id"], r["product_id"])

            deduped[key] = {
                "warehouse_id": r["warehouse_id"],
                "product_id": r["product_id"],
                "current_stock": int(r["current_stock"]),
                "reorder_point": int(r["reorder_point"]),
                "avg_daily_demand": int(r["avg_daily_demand"])
                if r.get("avg_daily_demand")
                else None,
                "last_restock_date": _parse_date(
                    r.get("last_restock_date")
                ),
                "scenario_tag": r.get("scenario_tag"),
            }

    rows = list(deduped.values())

    if not rows:
        return 0

    async with get_sessionmaker()() as session:
        stmt = insert(InventoryItem).values(rows)

        stmt = stmt.on_conflict_do_update(
            constraint="uq_inventory_warehouse_product",
            set_={
                "current_stock": stmt.excluded.current_stock,
                "reorder_point": stmt.excluded.reorder_point,
                "avg_daily_demand": stmt.excluded.avg_daily_demand,
                "last_restock_date": stmt.excluded.last_restock_date,
                "scenario_tag": stmt.excluded.scenario_tag,
            },
        )

        result = await session.execute(stmt)
        await session.commit()

    affected = result.rowcount or 0

    logger.info(
        "ingested_inventory",
        extra={
            "path": str(csv_path),
            "rows": len(rows),
            "affected": affected,
        },
    )

    return affected


async def ingest_delivery_metrics(csv_path: Path) -> int:
    rows: list[dict] = []

    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for r in reader:
            rows.append(
                {
                    "delivery_code": r["delivery_id"],
                    "route_id": r["route_id"],
                    "status": r["status"],
                    "sla_hours": int(r["sla_hours"]),
                    "actual_hours": int(r["actual_hours"]),
                    "scenario_tag": r.get("scenario_tag"),
                }
            )

    if not rows:
        return 0

    async with get_sessionmaker()() as session:
        stmt = insert(DeliveryMetric).values(rows)

        stmt = stmt.on_conflict_do_update(
            index_elements=[DeliveryMetric.delivery_code],
            set_={
                "route_id": stmt.excluded.route_id,
                "status": stmt.excluded.status,
                "sla_hours": stmt.excluded.sla_hours,
                "actual_hours": stmt.excluded.actual_hours,
                "scenario_tag": stmt.excluded.scenario_tag,
            },
        )

        result = await session.execute(stmt)
        await session.commit()

    affected = result.rowcount or 0

    logger.info(
        "ingested_delivery_metrics",
        extra={
            "path": str(csv_path),
            "rows": len(rows),
            "affected": affected,
        },
    )

    return affected


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    suppliers_path = DATA_DIR / "suppliers.csv"
    inventory_path = DATA_DIR / "inventory.csv"
    delivery_path = DATA_DIR / "delivery_metrics.csv"

    await ingest_suppliers(suppliers_path)
    await ingest_inventory(inventory_path)
    await ingest_delivery_metrics(delivery_path)

    async with get_sessionmaker()() as session:
        supplier_count = await session.scalar(
            select(func.count()).select_from(Supplier)
        )

        inventory_count = await session.scalar(
            select(func.count()).select_from(InventoryItem)
        )

        delivery_count = await session.scalar(
            select(func.count()).select_from(DeliveryMetric)
        )

    logger.info(
        "ingestion_complete",
        extra={
            "suppliers": supplier_count,
            "inventory": inventory_count,
            "delivery_metrics": delivery_count,
        },
    )


if __name__ == "__main__":
    asyncio.run(main())