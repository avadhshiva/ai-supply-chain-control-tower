from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.ai.decision_engine import ENGINE_VERSION, build_recommendations
from app.api.deps import DbSession
from app.api.schemas.ai import RecommendationsResponse
from app.services import analytics_reads

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/recommendations", response_model=RecommendationsResponse)
async def get_ai_recommendations(
    db: DbSession,
    operational_risk_limit: int = Query(default=10, ge=1, le=25),
) -> RecommendationsResponse:
    """Deterministic orchestration: analytics aggregates in, structured recommendations out."""
    inventory = await analytics_reads.get_inventory_risk_summary(db)
    deliveries = await analytics_reads.get_delayed_delivery_summary(db)
    suppliers = await analytics_reads.get_supplier_reliability_overview(db)
    scenarios = await analytics_reads.get_scenario_tag_distribution(db)
    risks = await analytics_reads.list_top_operational_risks(db, limit=operational_risk_limit)

    recommendations = build_recommendations(inventory, deliveries, suppliers, scenarios, risks)
    return RecommendationsResponse(
        engine_version=ENGINE_VERSION,
        generated_at=datetime.now(timezone.utc),
        recommendations=recommendations,
    )
