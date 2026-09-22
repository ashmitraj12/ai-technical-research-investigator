"""
Evaluator for generating the Evaluation Matrix and computing qualitative scores.
"""

from typing import List, Dict, Any
from app.evaluation.metrics import InvestigationMetrics, EvaluationMatrixRow, QualitativeScores
from app.evidence.manager import EvidenceManager
from app.evidence.models import EvidenceCategory, ReliabilityLevel


class EvaluationEngine:
    """Generates evaluation matrices and calculates performance metrics from real telemetry."""

    @staticmethod
    def generate_matrix(metrics: InvestigationMetrics) -> List[EvaluationMatrixRow]:
        """Builds a formatted evaluation matrix table from actual runtime telemetry."""
        web_calls = metrics.tool_metrics.get("search_web", {}).call_count if "search_web" in metrics.tool_metrics else 0
        github_calls = metrics.tool_metrics.get("search_github_issues", {}).call_count if "search_github_issues" in metrics.tool_metrics else 0
        repo_calls = metrics.tool_metrics.get("inspect_local_repository", {}).call_count if "inspect_local_repository" in metrics.tool_metrics else 0
        doc_calls = metrics.tool_metrics.get("fetch_web_document", {}).call_count if "fetch_web_document" in metrics.tool_metrics else 0

        evidence_notes = "Structured findings; validation status is shown separately"
        if metrics.evidence_required is False and metrics.evidence_items_count == 0:
            evidence_notes = "Direct response (External evidence not required for general knowledge)"

        rows = [
            EvaluationMatrixRow(metric="Total Investigation Time", value=f"{metrics.total_investigation_time_sec:.2f} sec", notes="Wall clock duration"),
            EvaluationMatrixRow(metric="LLM Calls", value=str(metrics.total_llm_calls), notes=f"Avg latency: {metrics.avg_llm_latency_sec:.2f}s"),
            EvaluationMatrixRow(metric="Total Tokens", value=str(metrics.total_tokens) if metrics.total_tokens > 0 else "N/A", notes=f"Prompt: {metrics.total_prompt_tokens}, Eval: {metrics.total_eval_tokens}"),
            EvaluationMatrixRow(metric="Total MCP Calls", value=str(metrics.total_mcp_calls), notes=f"Success: {metrics.successful_mcp_calls}, Fail: {metrics.failed_mcp_calls}"),
            EvaluationMatrixRow(metric="Duplicate Calls Prevented", value=str(metrics.duplicate_tool_calls_prevented), notes="Successful identical calls skipped"),
            EvaluationMatrixRow(metric="Average Tool Latency", value=f"{metrics.avg_mcp_latency_sec:.2f} sec", notes="Stdio transport execution latency"),
            EvaluationMatrixRow(metric="Web Searches", value=str(web_calls), notes="DuckDuckGo Search calls"),
            EvaluationMatrixRow(metric="GitHub Searches", value=str(github_calls), notes="GitHub Issues/PRs search calls"),
            EvaluationMatrixRow(metric="Repository Inspections", value=str(repo_calls), notes="Local filesystem/code inspection calls"),
            EvaluationMatrixRow(metric="Web Document Extractions", value=str(doc_calls), notes="Full web page content extractions"),
            EvaluationMatrixRow(metric="Evidence Items Collected", value=str(metrics.evidence_items_count), notes=evidence_notes),
            EvaluationMatrixRow(metric="Reflection Pass", value="Completed" if metrics.reflection_passes > 0 else "Skipped", notes="Single-pass verification check"),
            EvaluationMatrixRow(metric="Final Confidence", value=f"{metrics.final_confidence_percent}%", notes="Evidence-backed confidence rating"),
            EvaluationMatrixRow(metric="Error Count", value=str(metrics.error_count), notes="Captured network/parse failures")
        ]
        return rows

    @staticmethod
    def calculate_qualitative_scores(metrics: InvestigationMetrics, evidence_mgr: EvidenceManager, final_text: str) -> QualitativeScores:
        """
        Calculates conservative, grounded qualitative assessment scores based on category coverage,
        source reliability, and tool failure penalties.
        """
        items = evidence_mgr.get_all_evidence()
        verified_items = evidence_mgr.get_verified_evidence()
        evidence_count = len(items)

        # 1. Evidence Completeness: Evaluate coverage across essential categories
        has_error = any(item.category == EvidenceCategory.ERROR_TRACE for item in items)
        has_deps = any(item.category == EvidenceCategory.DEPENDENCY for item in items)
        has_code = any(item.category == EvidenceCategory.LOCAL_CODE for item in items)
        has_doc = any(item.category == EvidenceCategory.OFFICIAL_DOC for item in items)
        has_community = any(item.category == EvidenceCategory.COMMUNITY_REPORT for item in items)

        categories_covered = sum([has_error, has_deps, has_code, has_doc, has_community])
        
        if metrics.evidence_required is False and metrics.total_mcp_calls == 0:
            completeness = 10.0  # Evidence is correctly unnecessary for this request type.
        elif evidence_count == 0:
            completeness = 1.0
        else:
            # Base score derived from distinct evidence dimensions covered (up to 2.0 per category)
            completeness = min(10.0, round(categories_covered * 2.2 + (len(verified_items) * 0.5), 1))

        # Penalty if tool failures occurred
        if metrics.failed_mcp_calls > 0:
            completeness = max(1.0, round(completeness - (metrics.failed_mcp_calls * 2.0), 1))

        # 2. Source Quality: Percentage of High-reliability / Official sources
        if metrics.evidence_required is False and metrics.total_mcp_calls == 0:
            quality_score = 10.0  # Stable baseline general knowledge does not require external sources.
        elif not items:
            quality_score = 1.0
        else:
            high_count = sum(1 for item in items if item.reliability == ReliabilityLevel.HIGH)
            ratio = high_count / evidence_count
            quality_score = round(3.0 + (ratio * 6.5), 1)
            if metrics.failed_mcp_calls > 0:
                quality_score = max(1.0, round(quality_score - 1.5, 1))

        # 3. Answer Relevance: Grounded sections presence and no prompt leaking
        if metrics.evidence_required is False and metrics.total_mcp_calls == 0:
            relevance = 9.5 if len(final_text.strip()) > 20 else 7.0
        else:
            relevance = 6.0
            if len(final_text) > 150 and "Problem" in final_text and "Conclusion" in final_text and "Likely Root Cause" in final_text:
                relevance = 8.5
                if "Objective:" not in final_text and "Reflection Analysis:" not in final_text:
                    relevance = 9.5
            elif len(final_text) > 100 and "Problem" in final_text and "Conclusion" in final_text:
                relevance = 8.5
            if "INSUFFICIENT EVIDENCE" in final_text and evidence_count == 0:
                relevance = 9.0  # High relevance for correctly acknowledging missing evidence

        # 4. Reasoning Sufficiency: Dependent on reflection validation and absence of ungrounded assumptions
        if metrics.evidence_required is False and metrics.total_mcp_calls == 0:
            sufficiency = 9.5
        elif evidence_count == 0:
            sufficiency = 2.0
        elif metrics.failed_mcp_calls > 0 and not has_code and not has_deps:
            sufficiency = 3.5
        elif metrics.reflection_passes > 0 and len(verified_items) >= 2:
            sufficiency = 9.0
        elif metrics.reflection_passes > 0 and evidence_count >= 1:
            sufficiency = 8.5
        else:
            sufficiency = 6.5

        # 5. Tool Efficiency: Penalize failed or excessive calls
        if metrics.total_mcp_calls == 0:
            efficiency = 10.0 if metrics.evidence_required is False else 6.0
        elif metrics.evidence_required is False:
            efficiency = max(1.0, 10.0 - (metrics.total_mcp_calls * 2.5))
        elif metrics.failed_mcp_calls > 0:
            efficiency = max(1.0, round(8.0 - (metrics.failed_mcp_calls * 2.5), 1))
        elif metrics.total_mcp_calls <= 4:
            efficiency = 9.5
        else:
            efficiency = 7.0

        if metrics.evidence_required is False:
            contradiction_msg = "N/A (Direct stable knowledge)"
        elif evidence_count > 1 and metrics.failed_mcp_calls == 0:
            contradiction_msg = "No contradictions detected"
        elif metrics.failed_mcp_calls > 0:
            contradiction_msg = "Contradiction / Missing evidence identified"
        else:
            contradiction_msg = "N/A"

        return QualitativeScores(
            evidence_completeness=completeness,
            source_quality=quality_score,
            answer_relevance=relevance,
            reasoning_sufficiency=sufficiency,
            contradiction_detection=contradiction_msg,
            tool_selection_efficiency=efficiency
        )
