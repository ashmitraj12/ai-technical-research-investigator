import sys
from pathlib import Path

project_root = str(Path(__file__).parent.resolve())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.agent.agent import ResearchInvestigatorAgent

agent = ResearchInvestigatorAgent()

def run_test(name, query, repo_path):
    print(f"\n=== Running {name} ===")
    print(f"Query: {query}")
    print(f"Repo: {repo_path}")
    res = agent.investigate(
        query=query,
        repo_path=repo_path,
        max_iterations=6
    )
    tools = res["agent_state"].tools_used
    metrics = res["metrics"]
    evidence = res["evidence_manager"].get_all_evidence()
    print(f"MCP Calls: {metrics.total_mcp_calls}")
    print(f"Tools Used: {tools}")
    print(f"Evidence Items: {len(evidence)}")
    search_web_count = sum(1 for t in tools if t == "search_web")
    fetch_web_count = sum(1 for t in tools if t == "fetch_web_document")
    inspect_repo_count = sum(1 for t in tools if t == "inspect_local_repository")
    print(f"search_web: {search_web_count}")
    print(f"fetch_web_document: {fetch_web_count}")
    print(f"inspect_local_repository: {inspect_repo_count}")
    print("="*40)

run_test(
    "TEST 1", 
    "Why does FastAPI raise PydanticUserError for @validator after migrating from Pydantic v1 to Pydantic v2?", 
    ""
)

run_test(
    "TEST 2",
    "Find out the problem in this project",
    "data/sample_project"
)

run_test(
    "TEST 3",
    "What is Python GIL?",
    ""
)
