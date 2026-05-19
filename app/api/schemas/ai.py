from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
RecommendationCategory = Literal["inventory", "delivery", "supplier", "operational"]


class EvidenceSignal(BaseModel):
    """Single explainable input signal attached to a recommendation."""

    name: str
    value: str | int | float | None = None
    comparison: str | None = Field(
        default=None,
        description="Human-readable comparison against a policy threshold, when applicable.",
    )


class RecommendationItem(BaseModel):
    """One deterministic, rule-driven operational recommendation."""

    id: str
    category: RecommendationCategory
    severity: Severity
    title: str
    summary: str
    actions: list[str] = Field(default_factory=list)
    evidence: list[EvidenceSignal] = Field(default_factory=list)
    rationale: str


class RecommendationsResponse(BaseModel):
    """Structured orchestration output for clients and downstream automation."""

    engine_version: str
    generated_at: datetime
    recommendations: list[RecommendationItem]


ConfidenceLevel = Literal["low", "medium", "high"]
RecoveryStrategyKind = Literal["conservative", "balanced", "aggressive"]


class ConfidenceBand(BaseModel):
    """Deterministic confidence interval derived from intervention coverage."""

    level: ConfidenceLevel
    lower_bound: float = Field(ge=0.0, le=1.0)
    upper_bound: float = Field(ge=0.0, le=1.0)


class LaneRerouteSimulation(BaseModel):
    projected_breach_reduction: float = Field(ge=0.0)
    projected_delay_reduction: float = Field(ge=0.0)
    stabilization_horizon_days: int = Field(ge=1)
    confidence_band: ConfidenceBand


class SupplierReallocationSimulation(BaseModel):
    projected_supplier_risk_reduction: float = Field(ge=0.0)
    projected_delivery_improvement: float = Field(ge=0.0, le=1.0)
    projected_recovery_horizon_days: int = Field(ge=1)


class InventoryRebalancingSimulation(BaseModel):
    projected_stockout_reduction: float = Field(ge=0.0)
    projected_recovery_days: int = Field(ge=1)
    projected_service_level_stabilization: float = Field(ge=0.0, le=1.0)


class RecoveryProjectedImprovements(BaseModel):
    breach_reduction: float = Field(ge=0.0)
    delay_reduction: float = Field(ge=0.0)
    supplier_risk_reduction: float = Field(ge=0.0)
    delivery_improvement: float = Field(ge=0.0, le=1.0)
    stockout_reduction: float = Field(ge=0.0)
    service_level_stabilization: float = Field(ge=0.0, le=1.0)


class RecoveryStrategy(BaseModel):
    kind: RecoveryStrategyKind
    title: str
    operational_assumptions: list[str]
    projected_improvements: RecoveryProjectedImprovements
    recovery_horizon_days: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    operational_tradeoff_note: str


class RecoveryScenariosResult(BaseModel):
    """Deterministic operational recovery scenarios (Phase 3A)."""

    engine_version: str
    strategies: list[RecoveryStrategy]


class DependencyNodeModel(BaseModel):
    node_id: str
    domain: str
    label: str


class DependencyEdgeModel(BaseModel):
    source_id: str
    target_id: str
    weight: float = Field(ge=0.0, le=1.0)


class DependencyGraphModel(BaseModel):
    nodes: list[DependencyNodeModel]
    edges: list[DependencyEdgeModel]


class FragileEntity(BaseModel):
    entity_id: str
    domain: str
    label: str
    fragility_score: float = Field(ge=0.0, le=1.0)
    blast_radius_score: float = Field(ge=0.0, le=1.0)
    severity: Severity


class BlastRadiusRanking(BaseModel):
    entity_id: str
    domain: str
    label: str
    blast_radius_score: float = Field(ge=0.0, le=1.0)
    affected_domains: list[str] = Field(default_factory=list)


class ConcentrationHotspot(BaseModel):
    domain: str
    entity_id: str
    label: str
    concentration_index: float = Field(ge=0.0, le=1.0)
    weight_share: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)


class CascadingRiskStatement(BaseModel):
    statement_id: str
    source_domain: str
    target_domains: list[str]
    severity: Severity
    statement: str
    chain_entities: list[str] = Field(default_factory=list)


class CrossDomainPressureSummary(BaseModel):
    inventory_pressure: float = Field(ge=0.0, le=1.0)
    delivery_pressure: float = Field(ge=0.0, le=1.0)
    supplier_pressure: float = Field(ge=0.0, le=1.0)
    combined_pressure: float = Field(ge=0.0, le=1.0)
    dominant_domain: str
    summary: str


class DependencyChain(BaseModel):
    chain_id: str
    path: list[str]
    path_labels: list[str]
    chain_pressure: float = Field(ge=0.0, le=1.0)


class DependencyAnalysisResult(BaseModel):
    """Deterministic dependency intelligence (Phase 4A)."""

    engine_version: str
    top_fragile_entities: list[FragileEntity]
    blast_radius_rankings: list[BlastRadiusRanking]
    concentration_hotspots: list[ConcentrationHotspot]
    cascading_risk_statements: list[CascadingRiskStatement]
    cross_domain_pressure_summary: CrossDomainPressureSummary
    dependency_chains: list[DependencyChain]
