"""
Unit tests for Evaluation Metrics Tracker and Matrix Generator.
"""

import pytest
from app.evaluation.tracker import MetricsTracker
from app.evaluation.evaluator import EvaluationEngine
from app.evidence.manager import EvidenceManager


def test_metrics_tracker_and_matrix():
    tracker = MetricsTracker()
    tracker.start_investigation()
    
    tracker.record_llm_call(latency_sec=1.25, prompt_tokens=100, eval_tokens=50)
    tracker.record_mcp_call(tool_name="search_web", success=True, latency_sec=0.85)
    tracker.record_mcp_call(tool_name="search_github_issues", success=True, latency_sec=1.10)
    tracker.record_iteration()
    tracker.record_reflection()
    tracker.set_evidence_counts(sources_count=2, evidence_count=3)
    tracker.set_final_confidence(85)
    
    tracker.stop_investigation()
    
    metrics = tracker.get_metrics()
    assert metrics.total_llm_calls == 1
    assert metrics.total_mcp_calls == 2
    assert metrics.successful_mcp_calls == 2
    assert metrics.failed_mcp_calls == 0
    assert metrics.reflection_passes == 1

    matrix = EvaluationEngine.generate_matrix(metrics)
    assert len(matrix) > 5
    
    # Verify exact metric values
    llm_row = next(r for r in matrix if r.metric == "LLM Calls")
    assert llm_row.value == "1"
    
    mcp_row = next(r for r in matrix if r.metric == "Total MCP Calls")
    assert mcp_row.value == "2"
