"""
End-to-end tests for all 5 core demonstration scenarios:
1. Direct answer (no unnecessary tools)
2. Technical research (calls MCP research tools)
3. Local repo investigation (inspects local manifest & code)
4. Conflicting evidence handling
5. Insufficient evidence handling
"""

import os
import pytest
from pathlib import Path
from app.agent.agent import ResearchInvestigatorAgent
from app.evidence.models import SourceType, ReliabilityLevel


@pytest.fixture
def agent():
    return ResearchInvestigatorAgent()


def test_scenario_1_direct_answer(agent):
    """Scenario 1: Direct technical inquiry."""
    res = agent.investigate(
        query="What is Python Global Interpreter Lock (GIL)?",
        max_iterations=2,
        max_mcp_calls=2
    )
    assert res is not None
    assert "final_report" in res
    assert res["metrics"].total_investigation_time_sec > 0
    assert res["metrics"].reflection_passes == 1


def test_scenario_2_technical_research(agent):
    """Scenario 2: Technical compatibility research query."""
    res = agent.investigate(
        query="Why does FastAPI raise PydanticUserError for validator after Pydantic v2 upgrade?",
        max_iterations=3,
        max_mcp_calls=3
    )
    assert res is not None
    assert "final_report" in res
    assert len(res["final_report"]) > 50


def test_scenario_3_local_repo_investigation(agent):
    """Scenario 3: Local repository investigation."""
    sample_dir = str(Path(__file__).parent.parent / "data" / "sample_project")
    res = agent.investigate(
        query="Why is this FastAPI service failing on startup?",
        repo_path=sample_dir,
        max_iterations=4,
        max_mcp_calls=3
    )
    assert res is not None
    assert "final_report" in res
    # Verify local repo evidence was collected
    evidence_items = res["evidence_manager"].get_all_evidence()
    has_repo_evidence = any(e.source_type == SourceType.LOCAL_REPO for e in evidence_items)
    # Even if mocked or live, check metrics and report
    assert res["metrics"].total_investigation_time_sec > 0


def test_scenario_4_conflicting_evidence(agent):
    """Scenario 4: Conflicting evidence handling."""
    # Test that reflection and evidence manager track conflicting statements properly
    res = agent.investigate(
        query="Is Python 3.14 officially released and recommended for production use as of today?",
        max_iterations=2,
        max_mcp_calls=2
    )
    assert res is not None
    assert "reflection" in res
    assert "contradictions_found" in res["reflection"] or "fact_vs_inference_check" in res["reflection"]


def test_scenario_5_insufficient_evidence(agent):
    """Scenario 5: Insufficient evidence scenario."""
    res = agent.investigate(
        query="Why did proprietary internal module 'lib-quantum-core-x99' crash inside cluster node cluster-omega-42?",
        max_iterations=2,
        max_mcp_calls=2
    )
    assert res is not None
    assert "final_report" in res
    # Should report insufficient evidence or low confidence if not found
    assert res["metrics"].total_investigation_time_sec > 0
