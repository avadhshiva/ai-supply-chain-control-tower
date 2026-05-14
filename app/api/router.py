from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import ai, alerts, analytics, delivery_metrics, inventory, suppliers

api_router = APIRouter(prefix="/v1")
api_router.include_router(inventory.router)
api_router.include_router(suppliers.router)
api_router.include_router(delivery_metrics.router)
api_router.include_router(alerts.router)
api_router.include_router(analytics.router)
api_router.include_router(ai.router)
