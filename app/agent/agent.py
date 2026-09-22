"""
Main Agent Controller implementing the complete ReAct Investigation Loop.
"""

import os
import time
import logging
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional
from app.llm.ollama_client import OllamaClient
from app.llm.models import ChatMessage, Role
from app.mcp.client import MCPClientManager
from app.agent.state import AgentState
from app.agent.planner import ReActPlanner
from app.agent.reflection import ReflectionEngine
from app.agent.prompts import FINAL_SUMMARY_PROMPT, QUERY_CLASSIFICATION_PROMPT
from app.evaluation.evaluator import EvaluationEngine
from app.evidence.models import EvidenceCategory

logger = logging.getLogger(__name__)


class ResearchInvestigatorAgent:
    """Agent Orchestrator for Technical Research Investigations."""

    def __init__(
        self,
        ollama_client: Optional[OllamaClient] = None,
        mcp_client: Optional[MCPClientManager] = None
    ):
        self.ollama = ollama_client or OllamaClient()
        self.mcp_client = mcp_client or MCPClientManager()
        self.mcp_client.discover_tools()
        
        self.planner = ReActPlanner(self.ollama, self.mcp_client)
        self.reflection_engine = ReflectionEngine(self.ollama)

    def investigate(
        self,
        query: str,
        repo_path: Optional[str] = None,
        model_name: Optional[str] = None,
        max_iterations: int = 15,
        max_mcp_calls: int = 15,
        temperature: float = 0.2,
        log_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Executes the full technical investigation workflow.
        """
        # Resolve target model from active client if not explicitly provided or if default Ollama model passed to Groq
        if not model_name or (hasattr(self.ollama, "default_model") and (model_name in ["llama3.2:1b", "qwen3.5:2b-q4_K_M"] and hasattr(self.ollama, "api_key"))):
            model_name = getattr(self.ollama, "default_model", "llama3.2:1b")
        # Resolve and validate repository path once, at the public boundary.
        # A bad path is a user-input error, not an MCP observation: do not start
        # an investigation that could later pretend it has repository evidence.
        validated_repo_path = None
        invalid_repo_path = None
        target_path = repo_path
        if not target_path or not str(target_path).strip():
            target_path = None

        if target_path and str(target_path).strip():
            candidate = Path(target_path).resolve()
            if candidate.exists() and candidate.is_dir():
                validated_repo_path = str(candidate)
            else:
                invalid_repo_path = str(target_path).strip()

        state = AgentState(
            objective=query,
            repo_path=validated_repo_path,
            max_iterations=max_iterations,
            max_mcp_calls=max_mcp_calls,
            temperature=temperature
        )

        if log_callback:
            state.logger.subscribe(log_callback)

        if invalid_repo_path:
            state.logger.warning("SYSTEM", f"Investigation not started: repository path does not exist: '{invalid_repo_path}'")
            state.tracker.record_error()
            return self._invalid_repository_result(state, invalid_repo_path)

        state.logger.info("SYSTEM", f"Application started. Target model: {model_name}")
        state.tracker.start_investigation()
        
        health = self.ollama.check_health()
        if health["status"] == "healthy":
            state.logger.info("LLM", f"Ollama connection established ({health['latency_sec']}s)")
        else:
            state.logger.warning("LLM", f"Ollama status check: {health.get('error', 'Unhealthy')}")

        discovered_tools = self.mcp_client.tools
        state.logger.info("MCP", f"MCP client initialized. Discovered {len(discovered_tools)} MCP tools.")

        state.logger.info("AGENT", f"User query received: '{query}'")
        if validated_repo_path:
            state.logger.info("AGENT", f"Local repository context attached: '{validated_repo_path}'")
        state.logger.info("AGENT", "Classifying request and determining investigation strategy...")
        classification = self._classify_query(query, validated_repo_path, state, model_name)
        state.query_classification = classification
        state.tracker.set_query_type(classification["query_type"])
        state.tracker.set_evidence_requirement(bool(classification["evidence_required"]))
        state.logger.info("AGENT", f"Query classified as {classification['query_type']}; evidence required={classification['evidence_required']}.")

        # The model makes this high-level decision. No MCP planning is entered
        # when the request is stable general knowledge and it says evidence is
        # unnecessary; reflection still runs exactly once below.
        direct_answer = None
        if not classification["evidence_required"] and not validated_repo_path:
            state.logger.info("AGENT", "Direct-answer strategy selected; MCP tools are not required.")
            direct_answer = self._generate_direct_answer(query, state, model_name)
            state.is_completed = True

        # ReAct Loop
        while direct_answer is None and state.can_continue():
            state.iteration += 1
            state.tracker.record_iteration()
            state.logger.info("AGENT", f"Iteration {state.iteration}/{state.max_iterations} started.")

            decision = self.planner.plan_next_action(state, model_name)
            
            if decision.user_status_message:
                state.current_status_message = decision.user_status_message

            if decision.action == "tool_call" and decision.tool_call:
                tcall = decision.tool_call
                signature = self._tool_signature(tcall.tool_name, tcall.arguments)
                
                # Token-overlap based semantic deduplication for searches
                is_duplicate = False
                if signature in state.successful_tool_signatures:
                    is_duplicate = True
                elif tcall.tool_name == "search_web":
                    query = str(tcall.arguments.get("query", ""))
                    for sig in state.successful_tool_signatures:
                        if sig.startswith("search_web:"):
                            try:
                                prev_args = json.loads(sig[11:])
                                prev_query = str(prev_args.get("query", ""))
                                if self._is_duplicate_search(query, prev_query):
                                    is_duplicate = True
                                    break
                            except json.JSONDecodeError:
                                pass

                if is_duplicate:
                    state.tracker.record_duplicate_prevented()
                    state.logger.warning("MCP", f"Duplicate successful tool call prevented: {tcall.tool_name} {tcall.arguments}")
                    state.add_history(role="tool_skipped", content="Duplicate successful call prevented.", tool_name=tcall.tool_name)
                    continue

                if signature in state.failed_tool_signatures:
                    state.logger.warning("MCP", f"Prevented repeating failed tool call: {tcall.tool_name} {tcall.arguments}")
                    # Switch to alternate tool if available
                    if tcall.tool_name == "fetch_web_document":
                        alternate_tool = "search_web"
                        alt_sig = None
                    else:
                        alternate_tool = "search_web" if tcall.tool_name == "search_github_issues" else ("search_github_issues" if tcall.tool_name == "search_web" else None)
                        alt_sig = self._tool_signature(alternate_tool, tcall.arguments) if alternate_tool else None
                        
                    if alternate_tool and (alt_sig is None or (alt_sig not in state.failed_tool_signatures and alt_sig not in state.successful_tool_signatures)):
                        state.logger.info("AGENT", f"Switching to alternate external tool: {alternate_tool}")
                        tcall.tool_name = alternate_tool
                        if tcall.tool_name == "search_web":
                            tcall.arguments = {"query": state.objective}
                        if alt_sig:
                            signature = alt_sig
                        else:
                            signature = self._tool_signature(tcall.tool_name, tcall.arguments)
                    else:
                        state.logger.warning("AGENT", "All alternative external research tools have been attempted or failed. Concluding investigation.")
                        state.add_history(role="tool_skipped", content="External tools failed after bounded retry.", tool_name=tcall.tool_name)
                        break

                state.mcp_call_count += 1
                state.tools_used.append(tcall.tool_name)
                
                state.logger.info("MCP", f"Tool selected: {tcall.tool_name}")
                state.logger.info("MCP", f"Calling {tcall.tool_name} with arguments: {tcall.arguments}")

                # Call genuine stdio MCP tool with timing
                res = self.mcp_client.call_tool(
                    tool_name=tcall.tool_name,
                    arguments=tcall.arguments
                )

                state.tracker.record_mcp_call(
                    tool_name=tcall.tool_name,
                    success=res["success"],
                    latency_sec=res["latency_sec"]
                )

                if res["success"]:
                    state.successful_tool_signatures.add(signature)
                    state.logger.info("MCP", f"Tool completed in {res['latency_sec']}s. Output received.")
                    state.evidence_mgr.ingest_mcp_result(
                        tool_name=tcall.tool_name,
                        arguments=tcall.arguments,
                        result=res["result"]
                    )
                    state.add_history(
                        role="tool",
                        content=str(res["result"])[:600],
                        tool_name=tcall.tool_name
                    )
                else:
                    state.failed_tool_signatures.add(signature)
                    state.failed_call_count += 1
                    state.logger.warning("MCP", f"Tool '{tcall.tool_name}' failed ({res['latency_sec']}s): {res['error']}")
                    state.add_history(
                        role="tool_error",
                        content=f"Error executing {tcall.tool_name}: {res['error']}. Do not repeat this exact call.",
                        tool_name=tcall.tool_name
                    )

                state.logger.info("AGENT", "Agent evaluating evidence...")

            elif decision.action == "decision_failed":
                state.logger.error("AGENT", "Agent decision step failed.")
                state.tracker.record_error()
                state.is_completed = False
                break
            else:
                # LLM decided final_answer or stop condition reached
                state.logger.info("AGENT", "Sufficient information or stop condition reached.")
                state.is_completed = True
                break

        # Record Evidence & Source counts
        all_evidence = state.evidence_mgr.get_all_evidence()
        unique_sources = len(set(item.url_or_path for item in all_evidence))
        state.tracker.set_evidence_counts(sources_count=unique_sources, evidence_count=len(all_evidence))

        # Build a meaningful draft conclusion from actual evidence
        if direct_answer:
            draft_conclusion = direct_answer
        elif all_evidence:
            dep_items = [e for e in all_evidence if e.category == EvidenceCategory.DEPENDENCY]
            src_items = [e for e in all_evidence if e.category == EvidenceCategory.LOCAL_CODE]
            err_items = [e for e in all_evidence if e.category == EvidenceCategory.ERROR_TRACE]
            ext_items = [e for e in all_evidence if e.category in (EvidenceCategory.OFFICIAL_DOC, EvidenceCategory.COMMUNITY_REPORT)]
            parts = []
            if dep_items:
                parts.append(f"Found {len(dep_items)} dependency manifest(s)")
            if src_items:
                parts.append(f"read {len(src_items)} source file(s)")
            if err_items:
                parts.append(f"captured {len(err_items)} error/log evidence item(s)")
            if ext_items:
                parts.append(f"retrieved {len(ext_items)} external reference(s)")
            draft_conclusion = (
                f"Investigation for '{query}': "
                + (", ".join(parts) if parts else f"{len(all_evidence)} items collected")
                + ". Sufficient context gathered to generate recommendations."
            )
        else:
            draft_conclusion = f"Investigation for: '{query}' — no evidence collected."
        reflection_res = self.reflection_engine.reflect(state, draft_conclusion, model_name)

        confidence_str = reflection_res.get("confidence_rating", "MEDIUM")
        confidence_num = 90 if confidence_str == "HIGH" else (65 if confidence_str == "MEDIUM" else 30)
        state.tracker.set_final_confidence(confidence_num)

        # Generate Final Synthesis
        state.logger.info("AGENT", "Finalizing direct response..." if direct_answer is not None else "Generating final evidence-backed investigation response...")
        evidence_text = state.evidence_mgr.format_evidence_for_prompt()
        is_sufficient = reflection_res.get("is_evidence_sufficient", True)
        
        final_prompt = FINAL_SUMMARY_PROMPT.format(
            objective=query,
            is_sufficient="Yes" if is_sufficient else "No (Insufficient Evidence)",
            confidence=confidence_str,
            reflection_summary=reflection_res.get("reflection_summary", "Verified"),
            evidence_text=evidence_text
        )

        if direct_answer is not None:
            final_text = direct_answer
        elif state.query_classification.get("evidence_required") and len(all_evidence) == 0:
            final_text = (
                "# INVESTIGATION SUMMARY\n\n"
                "## STATUS: INSUFFICIENT EVIDENCE (EXTERNAL TOOLS FAILED)\n\n"
                f"### Problem\n{query}\n\n"
                "### Conclusion\nExternal evidence was required for this investigation, but was unavailable because the MCP research tools failed or returned no results.\n\n"
                "### Confidence\n**LOW** — No external research evidence could be gathered.\n\n"
                "### Evidence-to-Claim Grounding\n"
                "- **FACT**: The query was classified as requiring external evidence.\n"
                "- **UNKNOWN**: Specific compatibility or migration details could not be validated without live tool results.\n"
                "- **RECOMMENDATION**: Check MCP tool connectivity or retry with an alternate query.\n\n"
                "### Sources\n- None (External tools unavailable)"
            )
        else:
            final_llm_resp = self.ollama.chat(
                messages=[ChatMessage(role=Role.USER, content=final_prompt)], model=model_name, temperature=0.1
            )
            state.tracker.record_llm_call(final_llm_resp["latency_sec"], final_llm_resp.get("prompt_tokens", 0), final_llm_resp.get("eval_tokens", 0))
            if final_llm_resp["success"] and final_llm_resp.get("content", "").strip():
                final_text = final_llm_resp["content"].strip()
            else:
                if not final_llm_resp["success"]:
                    state.tracker.record_error()
                    state.logger.warning("LLM", f"Final synthesis unavailable: {final_llm_resp.get('error', 'empty response')}")
                final_text = self._safe_report(query, state, reflection_res)
        
        state.tracker.stop_investigation()
        state.logger.info("SYSTEM", "Investigation completed successfully.")

        metrics = state.tracker.get_metrics()
        matrix_rows = EvaluationEngine.generate_matrix(metrics)
        qualitative = EvaluationEngine.calculate_qualitative_scores(metrics, state.evidence_mgr, final_text)

        return {
            "final_report": final_text,
            "agent_state": state,
            "evidence_manager": state.evidence_mgr,
            "metrics": metrics,
            "reflection": reflection_res,
            "evaluation_matrix": matrix_rows,
            "qualitative_scores": qualitative,
            "logs": state.logger.logs
        }

    @staticmethod
    def _safe_report(query: str, state: AgentState, reflection: Dict[str, Any]) -> str:
        """Render a structured fallback report using the actual collected evidence."""
        from app.evidence.models import EvidenceCategory
        evidence = state.evidence_mgr.get_all_evidence()
        verified = [item for item in evidence if item.verification_status == "VERIFIED"]
        if not verified and evidence:
            verified = [item for item in evidence if item.finding and item.finding.strip()]

        # Use the correct enum .value strings
        dep_items  = [i for i in verified if i.category == EvidenceCategory.DEPENDENCY]
        err_items  = [i for i in verified if i.category == EvidenceCategory.ERROR_TRACE]
        src_items  = [i for i in verified if i.category == EvidenceCategory.LOCAL_CODE]
        ext_items  = [i for i in verified if i.category in (EvidenceCategory.OFFICIAL_DOC, EvidenceCategory.COMMUNITY_REPORT)]
        gen_items  = [i for i in verified if i.category == EvidenceCategory.GENERAL]

        def _fmt(items, max_chars=400):
            return "\n".join(f"- {item.finding[:max_chars] + '...' if item.finding and len(item.finding) > max_chars else item.finding}" for item in items) if items else ""

        facts = "\n".join(f"- **{item.id}**: {item.title} — {item.finding[:200] + '...' if item.finding and len(item.finding) > 200 else item.finding}" for item in verified[:6])
        sources = "\n".join(f"- {item.url_or_path}" for item in verified[:6])

        conclusion = reflection.get("revised_conclusion", "")
        if not conclusion or "insufficient" in conclusion.lower():
            conclusion = f"Investigation for: '{query}' based on {len(verified)} verified evidence items."

        reasoning = "Not determinable from available evidence."
        if not reflection.get("is_evidence_sufficient"):
            reasoning = "Insufficient evidence collected to establish a firm conclusion."
        elif dep_items or src_items:
            reasoning = "Project structure, dependencies, and source code were examined. Recommendations are based on the patterns found."

        # Build sections — show whatever we actually have
        dep_section  = _fmt(dep_items)  or "No dependency evidence collected."
        err_section  = _fmt(err_items)  or "No error logs or tracebacks collected."
        src_section  = _fmt(src_items)  or "No source code files read."
        ext_section  = _fmt(ext_items)  or "No external documentation fetched."
        gen_section  = _fmt(gen_items)

        return (
            "# Investigation Summary\n\n"
            "## Problem\n"
            f"{query}\n\n"
            "## Evidence Collected\n\n"
            "### Dependency Evidence\n"
            f"{dep_section}\n\n"
            "### Error Evidence\n"
            f"{err_section}\n\n"
            "### Source Code Evidence\n"
            f"{src_section}\n\n"
            "### External Evidence\n"
            f"{ext_section}\n"
            + (f"\n### General Findings\n{gen_section}\n" if gen_section else "") +
            "\n## Root Cause / Analysis\n"
            f"{conclusion}\n\n"
            "## Why It Happens\n"
            f"{reasoning}\n\n"
            "## Recommended Fix\n"
            "Review the evidence above and apply the changes that are grounded in the collected code and dependency findings.\n\n"
            "## Confidence\n"
            f"**{reflection.get('confidence_rating', 'LOW')}** — based on {len(verified)} verified evidence items.\n\n"
            "## Evidence-to-Claim Mapping\n"
            f"{facts if facts else '- No evidence items to map.'}\n"
            "- **INFERENCE**: Conclusions are limited to the verified findings above.\n"
            "- **UNKNOWN**: Runtime behaviour and issues not visible in static files.\n\n"
            "## Sources\n"
            f"{sources if sources else '- No verified sources.'}"
        )

    def _invalid_repository_result(self, state: AgentState, repo_path: str) -> Dict[str, Any]:
        """Return a structured, non-investigation result for invalid input."""
        report = (
            "# INVESTIGATION SUMMARY\n\n"
            "## STATUS: REPOSITORY PATH INVALID\n\n"
            "Repository path does not exist. Please select a valid repository.\n\n"
            "No investigation, MCP call, or evidence collection was started."
        )
        metrics = state.tracker.get_metrics()
        return {
            "final_report": report, "agent_state": state, "evidence_manager": state.evidence_mgr,
            "metrics": metrics,
            "reflection": {"is_evidence_sufficient": False, "confidence_rating": "LOW", "reflection_summary": "Not run: invalid repository path."},
            "evaluation_matrix": EvaluationEngine.generate_matrix(metrics),
            "qualitative_scores": EvaluationEngine.calculate_qualitative_scores(metrics, state.evidence_mgr, report),
            "logs": state.logger.logs,
        }

    @staticmethod
    def _extract_query_signals(query: str, repo_path: Optional[str]) -> Dict[str, bool]:
        """Extract structured intent signals from query text and context."""
        q_lower = query.lower()

        temporal_patterns = [
            r"\b(current|currently|latest|recent|recently|newest|today|now|upcoming)\b",
            r"\b(compatibility|compatible|release|releases|released|roadmap|changelog)\b",
            r"\b(breaking change[s]?|migration|migrating|upgrade|upgrading)\b",
            r"\bv?[0-9]+(?:\.[0-9]+)*\s*(?:to|vs|and)\s*v?[0-9]+"
        ]
        has_temporal = any(re.search(p, q_lower) for p in temporal_patterns)

        investigation_patterns = [
            r"\b(investigate|debug|debugging|root cause|why is|why does|why did)\b",
            r"\b(failing|failed|failure|crash|crashed|crashing|error|traceback|exception)\b",
            r"\b(broken|bug|issue|fix|not working|diagnose|troubleshoot)\b"
        ]
        has_investigation = any(re.search(p, q_lower) for p in investigation_patterns)

        repo_patterns = [
            r"\b(sample project|repository|repo|codebase|workspace|local project|my project|my app|my application|source code)\b"
        ]
        has_repo_mention = any(re.search(p, q_lower) for p in repo_patterns)
        has_repo = bool(repo_path) or has_repo_mention

        comparison_patterns = [
            r"\b(difference between|compare|comparison|versus|vs|pros and cons|trade-offs|benchmarks?)\b"
        ]
        has_comparison = any(re.search(p, q_lower) for p in comparison_patterns)

        general_patterns = [
            r"^(what is|what are|explain|describe|define)\s+([a-zA-Z0-9_\s]+)\??$"
        ]
        is_general_pattern = any(re.match(p, q_lower.strip()) for p in general_patterns)
        is_general_stable = is_general_pattern and not (has_temporal or has_investigation or has_repo or has_comparison)

        return {
            "has_temporal": has_temporal,
            "has_investigation": has_investigation,
            "has_repo": has_repo,
            "has_comparison": has_comparison,
            "is_general_stable": is_general_stable
        }

    def _classify_query(self, query: str, repo_path: Optional[str], state: AgentState, model_name: str) -> Dict[str, Any]:
        signals = self._extract_query_signals(query, repo_path)
        signal_hint = (
            f"\nContext signals: repo_supplied={bool(repo_path)}, "
            f"has_temporal={signals['has_temporal']}, "
            f"has_investigation={signals['has_investigation']}, "
            f"has_repo_mention={signals['has_repo']}, "
            f"is_general_stable={signals['is_general_stable']}"
        )

        response = self.ollama.chat(
            [ChatMessage(role=Role.USER, content=QUERY_CLASSIFICATION_PROMPT + signal_hint + f"\nRequest: {query}")],
            model=model_name,
            temperature=0.0,
            format_json=True
        )
        state.tracker.record_llm_call(response["latency_sec"], response.get("prompt_tokens", 0), response.get("eval_tokens", 0))
        parsed = self.ollama.extract_json(response.get("content", "")) if response["success"] else None

        is_explicit_external_search = bool(
            re.search(r"\b(search github|github issues?|search web|find issues on github|github search)\b", query.lower())
        )
        if is_explicit_external_search:
            return {
                "query_type": "research",
                "evidence_required": True,
                "external_research_required": True,
                "local_repository_required": False,
                "current_information_required": False,
                "reason": "Explicit external GitHub/web search requested."
            }

        if signals["is_general_stable"] and not repo_path:
            return {
                "query_type": "general_knowledge",
                "evidence_required": False,
                "external_research_required": False,
                "local_repository_required": False,
                "current_information_required": False,
                "reason": "Stable general technical knowledge without temporal, debugging, or repository context."
            }

        if signals["has_repo"] or repo_path:
            # Always allow external research in addition to local inspection.
            # The planner will run local first and then pass to LLM for web research.
            return {
                "query_type": "repository_investigation",
                "evidence_required": True,
                "external_research_required": True,
                "local_repository_required": True,
                "current_information_required": signals["has_temporal"],
                "reason": "Local repository inspection required, with supplemental external research for best-practice recommendations."
            }

        if signals["has_investigation"]:
            return {
                "query_type": "troubleshooting",
                "evidence_required": True,
                "external_research_required": True,
                "local_repository_required": False,
                "current_information_required": signals["has_temporal"],
                "reason": "Root cause investigation and technical diagnosis required."
            }

        if signals["has_temporal"] or signals["has_comparison"]:
            q_type = "current_information" if signals["has_temporal"] else "comparison"
            return {
                "query_type": q_type,
                "evidence_required": True,
                "external_research_required": True,
                "local_repository_required": False,
                "current_information_required": signals["has_temporal"],
                "reason": "External evidence required for current version/compatibility research."
            }

        allowed = {"general_knowledge", "current_information", "technical_investigation", "troubleshooting", "repository_investigation", "comparison", "research"}
        if isinstance(parsed, dict) and parsed.get("query_type") in allowed:
            if parsed.get("query_type") == "general_knowledge" and not (signals["has_temporal"] or signals["has_investigation"]):
                parsed["evidence_required"] = False
            else:
                parsed["evidence_required"] = True
                parsed["external_research_required"] = not bool(repo_path)
                parsed["local_repository_required"] = bool(repo_path)
            return parsed

        state.tracker.record_error()
        state.logger.warning("LLM", "Query classification was unavailable or malformed; using conservative investigation strategy.")
        return {
            "query_type": "repository_investigation" if repo_path else "research",
            "evidence_required": True,
            "external_research_required": not bool(repo_path),
            "local_repository_required": bool(repo_path),
            "current_information_required": False,
            "reason": "Conservative fallback after classification failure."
        }

    def _generate_direct_answer(self, query: str, state: AgentState, model_name: str) -> str:
        prompt = f"Answer this stable technical/general-knowledge question concisely and accurately. Do not mention tools, evidence, investigation, or hidden reasoning.\n\nQuestion: {query}"
        response = self.ollama.chat([ChatMessage(role=Role.USER, content=prompt)], model=model_name, temperature=0.1)
        state.tracker.record_llm_call(response["latency_sec"], response.get("prompt_tokens", 0), response.get("eval_tokens", 0))
        if response["success"] and response["content"].strip():
            return response["content"].strip()
        state.tracker.record_error()
        return "I could not generate a direct answer because the configured local model is unavailable."

    @staticmethod
    def _tool_signature(tool_name: str, arguments: Dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(arguments, sort_keys=True, separators=(',', ':'), default=str)}"

    @staticmethod
    def _is_duplicate_search(query1: str, query2: str) -> bool:
        """Check if two search queries are semantically similar based on token overlap."""
        tokens1 = set(re.findall(r'\w+', query1.lower()))
        tokens2 = set(re.findall(r'\w+', query2.lower()))
        if not tokens1 or not tokens2:
            return False
        overlap = len(tokens1.intersection(tokens2))
        return overlap / max(len(tokens1), len(tokens2)) > 0.75

