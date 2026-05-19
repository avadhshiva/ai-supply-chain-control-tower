from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.ai.decision_engine import ENGINE_VERSION, build_recommendations
from app.api.deps import DbSession
from app.api.schemas.ai import (
    DependencyAnalysisResult,
    RecommendationsResponse,
    RecoveryScenariosResult,
)
from app.services import analytics_reads
from app.services.dependency_analysis import build_dependency_analysis_from_analytics
from app.services.recovery_scenarios import build_recovery_scenarios_from_analytics

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


@router.get("/recovery-scenarios", response_model=RecoveryScenariosResult)
async def get_recovery_scenarios(db: DbSession) -> RecoveryScenariosResult:
    """Deterministic recovery simulation from analytics aggregates (no LLM)."""
    inventory = await analytics_reads.get_inventory_risk_summary(db)
    deliveries = await analytics_reads.get_delayed_delivery_summary(db)
    suppliers = await analytics_reads.get_supplier_reliability_overview(db)
    return build_recovery_scenarios_from_analytics(inventory, deliveries, suppliers)


@router.get("/dependency-analysis", response_model=DependencyAnalysisResult)
async def get_dependency_analysis(
    db: DbSession,
    operational_risk_limit: int = Query(default=20, ge=1, le=50),
) -> DependencyAnalysisResult:
    """Deterministic dependency intelligence from analytics aggregates (no LLM)."""
    inventory = await analytics_reads.get_inventory_risk_summary(db)
    deliveries = await analytics_reads.get_delayed_delivery_summary(db)
    suppliers = await analytics_reads.get_supplier_reliability_overview(db)
    risks = await analytics_reads.list_top_operational_risks(db, limit=operational_risk_limit)
    return build_dependency_analysis_from_analytics(inventory, deliveries, suppliers, risks)
