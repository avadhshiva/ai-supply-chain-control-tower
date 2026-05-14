from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
RecommendationCategory = Literal["inventory", "delivery", "supplier", "operational"]
ConfidenceLevel = Literal["high", "medium", "low"]


class EvidenceSignal(BaseModel):
    """Single explainable input signal attached to a recommendation."""

    name: str
    value: str | int | float | None = None
    comparison: str | None = Field(
        default=None,
        description="Human-readable comparison against a policy threshold, when applicable.",
    )


class WeightedContributor(BaseModel):
    name: str
    weight: float = Field(ge=0.0, le=1.0, description="Normalized influence share on this alert.")


class KPIInfluence(BaseModel):
    kpi_id: str
    influence_pct: float = Field(ge=0.0, le=100.0)


class ExplainabilityDetail(BaseModel):
    weighted_contributors: list[WeightedContributor] = Field(default_factory=list)
    kpi_influences: list[KPIInfluence] = Field(default_factory=list)
    causal_chain: list[str] = Field(default_factory=list)
    dominant_trigger_source: str = ""


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
    confidence: ConfidenceLevel | None = None
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    owner: str | None = None
    target_window: str | None = None
    escalation_trigger: str | None = None
    time_to_impact: str | None = None
    simulation_insights: list[str] = Field(default_factory=list)
    explainability: ExplainabilityDetail | None = None


class RecommendationsResponse(BaseModel):
    """Structured orchestration output for clients and downstream automation."""

    engine_version: str
    generated_at: datetime
    recommendations: list[RecommendationItem]
