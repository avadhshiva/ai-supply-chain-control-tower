"""Deterministic decision orchestration built on analytics signals (no LLM runtime)."""

from app.ai.decision_engine import ENGINE_VERSION, build_recommendations

__all__ = ["ENGINE_VERSION", "build_recommendations"]
