"""Regression coverage for the audit findings found during real execution."""

from pathlib import Path

from app.agent.agent import ResearchInvestigatorAgent
from app.evidence.manager import EvidenceManager


class _ScriptedOllama:
    """Small deterministic model double used to test agent routing, not tools."""
    def __init__(self, replies): self.replies = iter(replies)
    def check_health(self): return {"status": "healthy", "latency_sec": 0}
    def chat(self, *args, **kwargs):
        return {"success": True, "content": next(self.replies), "latency_sec": 0.01, "prompt_tokens": 1, "eval_tokens": 1}
    @staticmethod
    def extract_json(text):
        import json
        try: return json.loads(text)
        except json.JSONDecodeError: return None


def test_invalid_repository_is_rejected_before_investigation():
    result = ResearchInvestigatorAgent().investigate(
        "Inspect this repository", repo_path="C:/not/a/real/repository"
    )

    assert "Repository path does not exist" in result["final_report"]
    assert result["metrics"].total_mcp_calls == 0
    assert result["metrics"].total_llm_calls == 0
    assert result["metrics"].reflection_passes == 0


def test_search_hit_is_retrieved_not_verified_evidence():
    manager = EvidenceManager()
    manager.ingest_mcp_result("search_web", {"query": "Pydantic validator"}, {
        "results": [{"title": "Pydantic migration", "url": "https://docs.pydantic.dev/latest/migration/", "snippet": "Use field validators when migrating to Pydantic v2."}]
    })

    assert manager.items[0].verification_status == "RETRIEVED"
    assert manager.get_verified_evidence() == []


def test_failed_mcp_call_is_counted_by_runtime_telemetry():
    agent = ResearchInvestigatorAgent()
    # Directly use the MCP transport here so this test does not depend on an
    # LLM selecting a particular tool.
    response = agent.mcp_client.call_tool("inspect_local_repository", {
        "repo_path": "C:/not/a/real/repository", "action": "list_dir"
    })
    assert response["success"] is False


def test_general_knowledge_uses_zero_mcp_calls_and_one_reflection():
    model = _ScriptedOllama([
        '{"query_type":"general_knowledge","evidence_required":false,"external_research_required":false,"local_repository_required":false,"current_information_required":false,"reason":"stable"}',
        "Python is a high-level, general-purpose programming language.",
        '{"is_evidence_sufficient":true,"confidence_rating":"HIGH"}',
    ])
    result = ResearchInvestigatorAgent(ollama_client=model).investigate("What is Python?")
    assert result["metrics"].total_mcp_calls == 0
    assert result["metrics"].reflection_passes == 1
    assert result["metrics"].query_type == "general_knowledge"
    assert result["final_report"].startswith("Python is")
