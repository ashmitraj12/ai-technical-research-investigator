"""
Integration test for Research Investigator Agent.
"""

import pytest
from app.agent.agent import ResearchInvestigatorAgent


def test_agent_simple_query_no_unnecessary_tools():
    """Simple general questions should conclude without tool call bloat."""
    agent = ResearchInvestigatorAgent()
    result = agent.investigate(
        query="What is Python programming language?",
        max_iterations=2,
        max_mcp_calls=2
    )
    
    assert "final_report" in result
    assert result["metrics"].total_investigation_time_sec > 0
    assert result["metrics"].reflection_passes == 1


def test_agent_with_repo_inspection():
    """Agent inspecting a local codebase path."""
    import os
    sample_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    agent = ResearchInvestigatorAgent()
    result = agent.investigate(
        query="Inspect local project dependencies",
        repo_path=sample_dir,
        max_iterations=3,
        max_mcp_calls=3
    )
    
    assert "final_report" in result
    assert result["metrics"].total_investigation_time_sec > 0
