"""
MCP Server for GitHub Issues and Release Research (Stdio).
Exposes tool: search_github_issues
"""

import os
import sys
import requests
from pathlib import Path
from typing import Dict, Any, Optional, List

project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.mcp.protocol import MCPServerBase


def handle_search_github_issues(
    query: Optional[str] = None,
    repo: Optional[str] = None
) -> Dict[str, Any]:
    """
    Searches GitHub issues and pull requests using GitHub public API with fallback to structured query.
    """
    if not query or not str(query).strip():
        return {"error": "Target query required for 'search_github_issues'.", "status": "MISSING_ARGUMENT"}
    search_q = query
    if repo:
        search_q += f" repo:{repo}"

    url = "https://api.github.com/search/issues"
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "AI-Technical-Research-Investigator"}
    
    # Check if optional GITHUB_TOKEN is available
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {"q": search_q, "per_page": 6}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            results = []
            for item in items:
                body_snippet = item.get("body", "") or ""
                if len(body_snippet) > 300:
                    body_snippet = body_snippet[:300] + "..."
                
                results.append({
                    "title": item.get("title"),
                    "url": item.get("html_url"),
                    "state": item.get("state"),
                    "created_at": item.get("created_at"),
                    "comments_count": item.get("comments"),
                    "body_snippet": body_snippet,
                    "repository_url": item.get("repository_url")
                })
            return {
                "query": query,
                "repo": repo,
                "total_count": data.get("total_count", 0),
                "returned_count": len(results),
                "issues": results
            }
        else:
            # If GitHub API hits rate limit or error, perform web search fallback specifically targeted at github.com
            return fallback_github_web_search(query, repo)
    except Exception as e:
        return fallback_github_web_search(query, repo)


def fallback_github_web_search(query: str, repo: Optional[str] = None) -> Dict[str, Any]:
    """Fallback search using DuckDuckGo focused on site:github.com."""
    try:
        from duckduckgo_search import DDGS
        ddg_q = f"site:github.com {query}"
        if repo:
            ddg_q = f"site:github.com/{repo} {query}"

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(ddg_q, max_results=5):
                results.append({
                    "title": r.get("title"),
                    "url": r.get("href"),
                    "state": "unknown (web index)",
                    "created_at": None,
                    "comments_count": None,
                    "body_snippet": r.get("body", ""),
                    "repository_url": repo or "github.com"
                })
        return {
            "query": query,
            "repo": repo,
            "total_count": len(results),
            "returned_count": len(results),
            "issues": results,
            "notice": "Retrieved via GitHub web search fallback."
        }
    except Exception as e:
        return {
            "query": query,
            "repo": repo,
            "total_count": 0,
            "returned_count": 0,
            "issues": [],
            "error": f"GitHub API & fallback error: {str(e)}"
        }


def main():
    server = MCPServerBase(name="github-research-mcp-server", version="1.0.0")
    server.register_tool(
        name="search_github_issues",
        description="Searches GitHub repositories for bug reports, issues, pull requests, release notes, and community discussions.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords or error messages to search for."
                },
                "repo": {
                    "type": "string",
                    "description": "Optional repository filter in format 'owner/repo' (e.g. 'fastapi/fastapi')."
                }
            },
            "required": ["query"]
        },
        handler=handle_search_github_issues
    )
    server.run_stdio()


if __name__ == "__main__":
    main()
