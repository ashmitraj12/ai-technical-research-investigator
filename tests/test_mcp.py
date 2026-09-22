"""
Unit tests for MCP Client Manager and Stdio Server integration.
"""

import pytest
from pathlib import Path
from app.mcp.client import MCPClientManager


def test_mcp_tool_discovery():
    client = MCPClientManager()
    tools = client.discover_tools()
    
    assert "inspect_local_repository" in tools
    assert "search_github_issues" in tools
    assert "search_web" in tools
    assert "fetch_web_document" in tools


def test_mcp_tool_execution_local_repo():
    client = MCPClientManager()
    client.discover_tools()
    
    current_dir = str(Path(__file__).parent.parent)
    res = client.call_tool(
        tool_name="inspect_local_repository",
        arguments={"repo_path": current_dir, "action": "list_dir"}
    )
    
    assert res["success"] is True
    assert res["tool_name"] == "inspect_local_repository"
    assert res["latency_sec"] > 0
    assert "entries" in res["result"]


def test_mcp_tool_execution_web_search_reports_real_network_failure():
    client = MCPClientManager()
    client.discover_tools()
    
    res = client.call_tool(
        tool_name="search_web",
        arguments={"query": "FastAPI Python 3.14 compatibility", "max_results": 2}
    )
    
    assert res["tool_name"] == "search_web"
    # Network access is environment-dependent.  The integration contract is
    # that the actual outcome is surfaced, never converted into fake evidence.
    if res["success"]:
        assert "results" in res["result"]
    else:
        assert res["error"]
