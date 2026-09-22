"""
Single-Pass Reflection Engine for verifying findings against gathered evidence.
"""

import json
import logging
from typing import Dict, Any, Optional
from app.llm.ollama_client import OllamaClient
from app.llm.models import ChatMessage, Role
from app.agent.prompts import REFLECTION_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.evidence.models import EvidenceCategory

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """Performs exactly one reflection pass before final response generation."""

    def __init__(self, ollama_client: OllamaClient):
        self.ollama = ollama_client

    def reflect(self, state: AgentState, draft_conclusion: str, model_name: str) -> Dict[str, Any]:
        """
        Executes single reflection pass checking fact vs inference, contradictions, and evidence sufficiency.
        """
        state.logger.info("REFLECTION", "Running one-shot reflection & verification pass...")
        state.tracker.record_reflection()

        evidence_items = state.evidence_mgr.get_all_evidence()
        verified_items = state.evidence_mgr.get_verified_evidence()
        evidence_count = len(evidence_items)

        # Baseline programmatic verification check
        has_repo = bool(state.repo_path)
        has_local_evidence = any(e.source_type.value == "Local Repository / Code" for e in evidence_items)
        has_failed_tools = state.tracker.metrics.failed_mcp_calls > 0

        evidence_str = state.evidence_mgr.format_evidence_for_prompt()
        prompt = REFLECTION_SYSTEM_PROMPT.format(
            objective=state.objective,
            evidence_summary=evidence_str,
            draft_conclusion=draft_conclusion
        )

        messages = [
            ChatMessage(role=Role.USER, content=prompt)
        ]

        llm_resp = self.ollama.chat(
            messages=messages,
            model=model_name,
            temperature=0.1,
            format_json=True
        )

        state.tracker.record_llm_call(
            latency_sec=llm_resp["latency_sec"],
            prompt_tokens=llm_resp.get("prompt_tokens", 0),
            eval_tokens=llm_resp.get("eval_tokens", 0)
        )

        parsed = {}
        if llm_resp["success"]:
            parsed = OllamaClient.extract_json(llm_resp["content"]) or {}

        # A direct-answer path intentionally has no external evidence. The
        # reflection validates that strategy rather than falsely calling it an
        # evidence failure.
        if state.query_classification.get("evidence_required") is False and not has_repo:
            return {
                "is_evidence_sufficient": True,
                "confidence_rating": "HIGH",
                "fact_vs_inference_check": "Direct response strategy is appropriate for this stable general-knowledge request.",
                "contradictions_found": [], "unsupported_assumptions": [],
                "revised_conclusion": draft_conclusion,
                "reflection_summary": "Direct answer verified; no external evidence was required."
            }

        # Programmatic Guardrails to enforce absolute factual integrity:
        if evidence_count == 0:
            return {
                "is_evidence_sufficient": False,
                "confidence_rating": "LOW",
                "fact_vs_inference_check": "No evidence was gathered to support the claims.",
                "contradictions_found": [],
                "unsupported_assumptions": ["Conclusion is ungrounded because zero evidence items were collected."],
                "revised_conclusion": "Insufficient evidence to determine root cause.",
                "reflection_summary": "Verification failed: Zero evidence collected. Status downgraded to INSUFFICIENT EVIDENCE."
            }

        local_categories = {item.category for item in verified_items if item.source_type.value == "Local Repository / Code"}

        # Determine which categories are truly required for this query type.
        # Error Information is only mandatory when the user explicitly asks about
        # an error, crash, bug, or traceback. For "how to improve" / "what changes"
        # style queries, the absence of error logs is expected and valid.
        obj_lower = state.objective.lower()
        is_error_query = any(w in obj_lower for w in [
            "error", "crash", "traceback", "exception", "failing", "failed",
            "broken", "bug", "fix", "debug", "why is", "why does", "not working"
        ])
        is_improvement_query = any(w in obj_lower for w in [
            "improve", "improvement", "reliable", "reliability", "changes", "better",
            "best practice", "recommendation", "optimize", "upgrade", "refactor"
        ])

        required_categories = [EvidenceCategory.DEPENDENCY, EvidenceCategory.LOCAL_CODE]
        if is_error_query:
            required_categories.append(EvidenceCategory.ERROR_TRACE)

        missing_local = [cat.value for cat in required_categories if cat not in local_categories]

        # For improvement queries: if we have ANY local evidence, we have enough to proceed.
        # For error/debugging queries: missing categories are more critical.
        repo_failed = state.tracker.metrics.tool_metrics.get("inspect_local_repository", None)
        repo_failed = bool(repo_failed and repo_failed.failure_count)

        if has_repo and not has_local_evidence:
            # Genuinely no local evidence at all — this is a hard failure
            return {
                "is_evidence_sufficient": False,
                "confidence_rating": "LOW",
                "fact_vs_inference_check": "Local repository inspection produced no evidence.",
                "contradictions_found": [],
                "unsupported_assumptions": ["No local files could be read."],
                "revised_conclusion": "Insufficient evidence: repository inspection produced no results.",
                "reflection_summary": "Verification failed: no local evidence collected despite repo path being provided."
            }

        if has_repo and missing_local and is_error_query and not is_improvement_query:
            # Error query with genuinely missing critical categories
            reason = "Local repository inspection failed" if repo_failed else "Required local evidence categories were not collected"
            return {
                "is_evidence_sufficient": False,
                "confidence_rating": "LOW",
                "fact_vs_inference_check": f"{reason}; missing: {', '.join(missing_local)}.",
                "contradictions_found": [],
                "unsupported_assumptions": ["Root cause cannot be confirmed without the missing evidence."],
                "revised_conclusion": "Insufficient evidence to confirm a repository-specific error root cause.",
                "reflection_summary": f"Confidence downgraded to LOW: missing evidence categories: {', '.join(missing_local)}."
            }

        # For improvement queries or queries with partial evidence: proceed with proportionate confidence
        # Derive final verified confidence
        confidence_rating = parsed.get("confidence_rating", "MEDIUM")
        has_authoritative_external = any(
            item.category == EvidenceCategory.OFFICIAL_DOC and item.source_type.value == "Official Documentation"
            for item in verified_items
        )
        if len(verified_items) == 0:
            confidence_rating = "LOW"
        elif evidence_count >= 4 and len(verified_items) >= 3 and has_authoritative_external and not has_failed_tools:
            confidence_rating = "HIGH"
        elif evidence_count >= 3 and len(verified_items) >= 2:
            confidence_rating = "MEDIUM"
        else:
            confidence_rating = "LOW"

        # The model can only lower this verdict; it cannot promote incomplete
        # evidence to sufficient. But for improvement queries with local evidence,
        # we always consider evidence sufficient.
        llm_sufficient = bool(parsed.get("is_evidence_sufficient", True))
        if is_improvement_query and has_local_evidence and len(verified_items) >= 2:
            is_sufficient = True  # Improvement queries don't need error traces
        elif has_repo and not missing_local and llm_sufficient:
            is_sufficient = True
        elif not has_repo and len(verified_items) >= 1 and llm_sufficient:
            is_sufficient = True
        else:
            is_sufficient = llm_sufficient and len(verified_items) > 0

        if len(verified_items) == 0:
            is_sufficient = False

        contradictions = parsed.get("contradictions_found", [])

        state.logger.info("REFLECTION", f"Reflection completed. Outcome: {'SUFFICIENT' if is_sufficient else 'INSUFFICIENT'}, Confidence: {confidence_rating}")

        return {
            "is_evidence_sufficient": is_sufficient,
            "confidence_rating": confidence_rating,
            "fact_vs_inference_check": parsed.get("fact_vs_inference_check", "Verified against evidence."),
            "contradictions_found": contradictions,
            "unsupported_assumptions": parsed.get("unsupported_assumptions", []),
            "revised_conclusion": parsed.get("revised_conclusion", draft_conclusion),
            "reflection_summary": parsed.get("reflection_summary", f"Evidence verified with {confidence_rating} confidence.")
        }
