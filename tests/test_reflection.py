"""
Unit tests for One-Pass Reflection Engine.
"""

import pytest
from app.agent.reflection import ReflectionEngine
from app.agent.state import AgentState
from app.evidence.models import SourceType, ReliabilityLevel
from app.llm.ollama_client import OllamaClient


def test_reflection_with_evidence():
    ollama = OllamaClient()
    engine = ReflectionEngine(ollama)
    
    state = AgentState(objective="Verify FastAPI Pydantic v2 migration")
    state.evidence_mgr.add_evidence(
        source="FastAPI Official Docs",
        source_type=SourceType.OFFICIAL_DOCS,
        title="Migration from Pydantic v1 to v2",
        url_or_path="https://fastapi.tiangolo.com/tutorial/pydantic-v2/",
        finding="@validator was replaced by @field_validator in Pydantic v2.",
        reliability=ReliabilityLevel.HIGH
    )
    
    draft = "Pydantic v2 deprecated @validator in favor of @field_validator."
    reflection = engine.reflect(state, draft_conclusion=draft, model_name="llama3.2:1b")
    
    assert "is_evidence_sufficient" in reflection
    assert "confidence_rating" in reflection
    assert "fact_vs_inference_check" in reflection
    assert state.tracker.metrics.reflection_passes == 1


def test_reflection_insufficient_evidence():
    ollama = OllamaClient()
    engine = ReflectionEngine(ollama)
    
    state = AgentState(objective="Why did hypothetical unknown package crash?")
    # No evidence added
    draft = "Hypothetical unknown failure."
    reflection = engine.reflect(state, draft_conclusion=draft, model_name="llama3.2:1b")
    
    assert "is_evidence_sufficient" in reflection
    assert state.tracker.metrics.reflection_passes == 1
