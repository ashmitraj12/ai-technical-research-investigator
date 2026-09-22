"""
MCP Server for Local Repository Inspection (Stdio).
Exposes tool: inspect_local_repository
"""

import os
import sys
import glob
from pathlib import Path
from typing import Dict, Any, Optional

# Ensure project root is in sys.path when executed as standalone script
project_root = str(Path(__file__).parent.parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.mcp.protocol import MCPServerBase


def handle_inspect_local_repository(
    repo_path: str,
    action: str,
    target: Optional[str] = None
) -> Dict[str, Any]:
    """
    Inspects a local codebase path.
    action: 'list_dir', 'read_file', 'search_code', 'inspect_dependencies'
    """
    p = Path(repo_path).resolve()
    if not p.exists():
        return {"error": f"Repository path '{repo_path}' does not exist.", "status": "FILE_NOT_FOUND"}

    if action == "list_dir":
        try:
            target_path = (p / target) if target else p
            if not target_path.exists() or not target_path.is_dir():
                return {"error": f"Target directory '{target_path}' not found.", "status": "NOT_A_DIRECTORY"}
            
            entries = []
            for item in target_path.iterdir():
                if item.name.startswith('.') or item.name in ['__pycache__', 'node_modules', 'venv', '.venv']:
                    continue
                entries.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None
                })
            return {"repo_path": str(p), "action": action, "entries": entries}
        except Exception as e:
            return {"error": str(e), "status": "ERROR"}

    elif action == "read_file":
        if not target:
            return {"error": "Target file path required for 'read_file' action.", "status": "MISSING_ARGUMENT"}
        target_file = (p / target) if not Path(target).is_absolute() else Path(target)
        if not target_file.exists() or not target_file.is_file():
            return {"error": f"File '{target_file}' does not exist.", "status": "FILE_NOT_FOUND"}
        try:
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            # Limit returned content to 400 lines or ~10KB for local LLM context management
            lines = content.splitlines()
            truncated = False
            
            is_log = target_file.suffix.lower() == '.log' or 'log' in target_file.name.lower()
            
            if len(lines) > 400:
                if is_log:
                    # For logs, extract lines with errors/exceptions and the tail
                    error_lines = []
                    for i, line in enumerate(lines):
                        if any(kw in line for kw in ["ERROR", "Exception", "Traceback"]):
                            # get tighter context
                            start = max(0, i - 1)
                            end = min(len(lines), i + 2)
                            error_lines.extend(lines[start:end])
                    
                    error_lines = list(dict.fromkeys(error_lines)) # deduplicate
                    
                    if len(error_lines) > 100:
                        lines = error_lines[:50] + ["\n... (more errors) ...\n"] + error_lines[-50:] + ["\n... (tail) ...\n"] + lines[-20:]
                    elif error_lines:
                        lines = error_lines + ["\n... (tail) ...\n"] + lines[-(200 - len(error_lines) - 2):]
                    else:
                        lines = lines[-400:]
                else:
                    lines = lines[:400]
                truncated = True
                
            return {
                "file_path": str(target_file),
                "total_lines": len(content.splitlines()),
                "content": "\n".join(lines),
                "truncated": truncated
            }
        except Exception as e:
            return {"error": str(e), "status": "ERROR"}

    elif action == "inspect_dependencies":
        deps_info = {}
        req_file = p / "requirements.txt"
        if req_file.exists():
            with open(req_file, "r", encoding="utf-8", errors="replace") as f:
                deps_info["requirements.txt"] = f.read().splitlines()
        
        pyproject_file = p / "pyproject.toml"
        if pyproject_file.exists():
            with open(pyproject_file, "r", encoding="utf-8", errors="replace") as f:
                deps_info["pyproject.toml"] = f.read()

        setup_file = p / "setup.py"
        if setup_file.exists():
            with open(setup_file, "r", encoding="utf-8", errors="replace") as f:
                deps_info["setup.py"] = f.read()

        if not deps_info:
            return {"notice": "No standard Python dependency manifests (requirements.txt, pyproject.toml, setup.py) found.", "deps": {}}
        return {"repo_path": str(p), "dependencies": deps_info}

    elif action == "search_code":
        if not target:
            return {"error": "Search string required in 'target' argument.", "status": "MISSING_ARGUMENT"}
        matches = []
        try:
            for root, dirs, files in os.walk(p):
                # Skip cache dirs
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'venv', '.venv', 'node_modules']]
                for file in files:
                    if file.endswith(('.py', '.toml', '.json', '.md', '.yaml', '.yml', '.txt')):
                        filepath = Path(root) / file
                        try:
                            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                                for lno, line in enumerate(f, 1):
                                    if target.lower() in line.lower():
                                        rel_path = filepath.relative_to(p)
                                        matches.append({
                                            "file": str(rel_path),
                                            "line_number": lno,
                                            "line": line.strip()
                                        })
                                        if len(matches) >= 30: # Cap match count
                                            break
                        except Exception:
                            continue
                    if len(matches) >= 30:
                        break
            return {"search_term": target, "matches_count": len(matches), "matches": matches}
        except Exception as e:
            return {"error": str(e), "status": "ERROR"}

    else:
        return {"error": f"Unknown action '{action}'. Options: list_dir, read_file, search_code, inspect_dependencies", "status": "INVALID_ACTION"}


def main():
    server = MCPServerBase(name="local-repo-mcp-server", version="1.0.0")
    server.register_tool(
        name="inspect_local_repository",
        description="Inspects local directory structures, dependency files (requirements.txt/pyproject.toml), source code, and performs pattern searches in local codebases.",
        input_schema={
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Directory path of the project to inspect."
                },
                "action": {
                    "type": "string",
                    "enum": ["list_dir", "read_file", "search_code", "inspect_dependencies"],
                    "description": "Inspection action to execute."
                },
                "target": {
                    "type": "string",
                    "description": "Optional subpath (for read_file/list_dir) or query term (for search_code)."
                }
            },
            "required": ["repo_path", "action"]
        },
        handler=handle_inspect_local_repository
    )
    server.run_stdio()


if __name__ == "__main__":
    main()
