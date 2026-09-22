"""
Runtime Evaluation Tracker for measuring investigation metrics accurately.
"""

import time
from typing import Dict, Any, List, Optional
from app.evaluation.metrics import InvestigationMetrics, ToolCallMetrics


class MetricsTracker:
    """Accurate in-memory metrics tracker for agent execution."""

    def __init__(self):
        self.metrics = InvestigationMetrics()
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None

    def start_investigation(self):
        self._start_time = time.time()
        self.metrics = InvestigationMetrics()

    def stop_investigation(self):
        if self._start_time:
            self._end_time = time.time()
            self.metrics.total_investigation_time_sec = round(self._end_time - self._start_time, 3)

    def record_llm_call(self, latency_sec: float, prompt_tokens: int = 0, eval_tokens: int = 0):
        self.metrics.total_llm_calls += 1
        self.metrics.total_llm_latency_sec = round(self.metrics.total_llm_latency_sec + latency_sec, 3)
        self.metrics.avg_llm_latency_sec = round(self.metrics.total_llm_latency_sec / self.metrics.total_llm_calls, 3)
        
        self.metrics.total_prompt_tokens += prompt_tokens
        self.metrics.total_eval_tokens += eval_tokens
        self.metrics.total_tokens = self.metrics.total_prompt_tokens + self.metrics.total_eval_tokens

    def record_mcp_call(self, tool_name: str, success: bool, latency_sec: float):
        self.metrics.total_mcp_calls += 1
        if success:
            self.metrics.successful_mcp_calls += 1
        else:
            self.metrics.failed_mcp_calls += 1
            self.metrics.error_count += 1

        self.metrics.total_mcp_latency_sec = round(self.metrics.total_mcp_latency_sec + latency_sec, 3)
        self.metrics.avg_mcp_latency_sec = round(self.metrics.total_mcp_latency_sec / self.metrics.total_mcp_calls, 3)

        if tool_name not in self.metrics.tool_metrics:
            self.metrics.tool_metrics[tool_name] = ToolCallMetrics(tool_name=tool_name)
        
        tm = self.metrics.tool_metrics[tool_name]
        tm.call_count += 1
        if success:
            tm.success_count += 1
        else:
            tm.failure_count += 1
        tm.total_latency_sec = round(tm.total_latency_sec + latency_sec, 3)
        tm.avg_latency_sec = round(tm.total_latency_sec / tm.call_count, 3)

    def record_iteration(self):
        self.metrics.agent_iterations += 1

    def record_reflection(self):
        self.metrics.reflection_passes += 1

    def set_evidence_counts(self, sources_count: int, evidence_count: int):
        self.metrics.sources_collected_count = sources_count
        self.metrics.evidence_items_count = evidence_count

    def set_final_confidence(self, confidence_percent: int):
        self.metrics.final_confidence_percent = confidence_percent

    def record_error(self):
        self.metrics.error_count += 1

    def set_query_type(self, query_type: str):
        self.metrics.query_type = query_type

    def set_evidence_requirement(self, evidence_required: bool):
        self.metrics.evidence_required = evidence_required

    def record_duplicate_prevented(self):
        self.metrics.duplicate_tool_calls_prevented += 1

    def get_metrics(self) -> InvestigationMetrics:
        if self._start_time and not self._end_time:
            current_time = time.time()
            self.metrics.total_investigation_time_sec = round(current_time - self._start_time, 3)
        return self.metrics
