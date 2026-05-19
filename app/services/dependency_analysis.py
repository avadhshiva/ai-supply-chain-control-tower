from __future__ import annotations

from app.ai.dependency_engine import build_dependency_analysis
from app.api.schemas.ai import DependencyAnalysisResult
from app.api.schemas.analytics import (
    DelayedDeliverySummary,
    InventoryRiskSummary,
    OperationalRiskList,
    SupplierReliabilityOverview,
)


def build_dependency_analysis_from_analytics(
    inventory: InventoryRiskSummary,
    deliveries: DelayedDeliverySummary,
    suppliers: SupplierReliabilityOverview,
    operational_risks: OperationalRiskList,
) -> DependencyAnalysisResult:
    """Derive dependency intelligence deterministically from analytics aggregates only."""
    return build_dependency_analysis(inventory, deliveries, suppliers, operational_risks)
