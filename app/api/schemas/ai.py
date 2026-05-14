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
