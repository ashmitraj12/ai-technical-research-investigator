"""
Metrics and Evaluation Data Models for runtime observability.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class ToolCallMetrics(BaseModel):
    tool_name: str
    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_latency_sec: float = 0.0
    avg_latency_sec: float = 0.0


class InvestigationMetrics(BaseModel):
    total_investigation_time_sec: float = 0.0
    total_llm_calls: int = 0
    total_llm_latency_sec: float = 0.0
    avg_llm_latency_sec: float = 0.0
    total_prompt_tokens: int = 0
    total_eval_tokens: int = 0
    total_tokens: int = 0
    
    total_mcp_calls: int = 0
    successful_mcp_calls: int = 0
    failed_mcp_calls: int = 0
    total_mcp_latency_sec: float = 0.0
    avg_mcp_latency_sec: float = 0.0
    
    tool_metrics: Dict[str, ToolCallMetrics] = Field(default_factory=dict)
    
    agent_iterations: int = 0
    reflection_passes: int = 0
    sources_collected_count: int = 0
    evidence_items_count: int = 0
    error_count: int = 0
    final_confidence_percent: int = 0
    retries: int = 0
    duplicate_tool_calls_prevented: int = 0
    query_type: Optional[str] = None
    evidence_required: Optional[bool] = None


class EvaluationMatrixRow(BaseModel):
    metric: str
    value: str
    notes: str = ""


class QualitativeScores(BaseModel):
    evidence_completeness: float = Field(description="Score out of 10.0")
    source_quality: float = Field(description="Score out of 10.0")
    answer_relevance: float = Field(description="Score out of 10.0")
    reasoning_sufficiency: float = Field(description="Score out of 10.0")
    contradiction_detection: str = Field(default="N/A (No contradictions found)")
    tool_selection_efficiency: float = Field(description="Score out of 10.0")
