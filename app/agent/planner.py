"""
ReAct Action Planner for tool selection and decision logic.
Supports both structured nested and flat JSON representations produced by local LLMs.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple
from app.llm.ollama_client import OllamaClient
from app.llm.models import ChatMessage, Role, LLMDecision, ParsedToolCall
from app.agent.prompts import REACT_SYSTEM_PROMPT
from app.agent.state import AgentState
from app.mcp.client import MCPClientManager
from app.evidence.models import EvidenceCategory, SourceType

logger = logging.getLogger(__name__)


# Directories to skip entirely when navigating
SKIP_DIRS: Set[str] = {
    "__pycache__", "node_modules", ".git", "venv", ".venv", ".tox",
    "dist", "build", "eggs", ".eggs", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "htmlcov", ".env", "env", "site-packages"
}

# Source code directories in priority order (broad investigation)
SOURCE_CODE_DIRS = ["src", "app", "backend", "lib", "core", "server",
                    "api", "service", "services", "pkg", "source", "tests", "test"]

# Log-related directories
LOG_DIRS = ["logs", "log", "var", "tmp", "output"]

# Interesting root-level files (not directories) to read when broadly investigating
ROOT_FILES_OF_INTEREST = [
    "README.md", "readme.md", "README.rst",
    "CHANGELOG.md", "CHANGES.md", "HISTORY.md",
    "config.py", "config.yaml", "config.yml", "config.toml",
    ".env.example", "settings.py", "setup.cfg",
    "Makefile", "docker-compose.yml", "docker-compose.yaml"
]

# Max files to read per source directory before concluding
MAX_SOURCE_FILES = 4


def _parse_dir_listing(finding: str) -> Tuple[List[str], List[str]]:
    """
    Parse a list_dir evidence finding into (files, directories).
    Supports both JSON-style {'name': ..., 'type': ...} lines and plain text.
    Returns (files, dirs) as relative name lists.
    """
    files: List[str] = []
    dirs: List[str] = []

    # Try JSON array parsing first
    try:
        parsed = json.loads(finding)
        if isinstance(parsed, list):
            for entry in parsed:
                if isinstance(entry, dict):
                    name = entry.get("name", "")
                    typ = entry.get("type", "")
                    if not name:
                        continue
                    if typ == "directory":
                        dirs.append(name)
                    elif typ == "file":
                        files.append(name)
            return files, dirs
    except (json.JSONDecodeError, TypeError):
        pass

    # Try line-by-line parsing (mixed format from evidence text)
    for line in finding.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Pattern: "name": "foo", "type": "file"
        name_m = re.search(r'"name":\s*"([^"]+)"', stripped)
        type_m = re.search(r'"type":\s*"([^"]+)"', stripped)
        if name_m:
            name = name_m.group(1)
            typ = type_m.group(1) if type_m else ""
            if typ == "directory":
                dirs.append(name)
            elif typ == "file":
                files.append(name)
            continue

        # Pattern: directory or file markers in plain text
        if re.search(r'\b(directory|DIR|dir)\b', stripped, re.IGNORECASE):
            # Extract name before the marker
            m = re.match(r'^([^\s]+)', stripped)
            if m:
                dirs.append(m.group(1).rstrip("/\\"))
        elif re.search(r'\b(file)\b', stripped, re.IGNORECASE):
            m = re.match(r'^([^\s]+)', stripped)
            if m:
                files.append(m.group(1))

    return files, dirs


def _get_dir_listing_evidence(state: AgentState) -> Dict[str, Tuple[List[str], List[str]]]:
    """
    Returns mapping of { listed_path: ([files], [dirs]) } from all list_dir evidence items.
    """
    result: Dict[str, Tuple[List[str], List[str]]] = {}
    for item in state.evidence_mgr.get_all_evidence():
        if item.source_type != SourceType.LOCAL_REPO:
            continue
        if item.title and ("directory structure" in item.title.lower() or "directory listing" in item.title.lower()):
            # Determine which path was listed
            path_key = item.url_or_path or state.repo_path or ""
            files, dirs = _parse_dir_listing(item.finding)
            result[path_key] = (files, dirs)
    return result


def _already_read(path: str, state: AgentState) -> bool:
    """Return True if a file with this suffix was already read (success or failed)."""
    norm = path.replace("\\", "/").lower()
    for item in state.evidence_mgr.get_all_evidence():
        if item.source_type == SourceType.LOCAL_REPO:
            if norm in item.url_or_path.replace("\\", "/").lower():
                return True
    # Also check failed signatures
    for sig in state.failed_tool_signatures:
        if norm in sig.lower():
            return True
    return False


def _is_source_file(name: str) -> bool:
    """Return True if a filename is interesting source code to read."""
    exts = {".py", ".js", ".ts", ".java", ".go", ".rb", ".cs", ".cpp", ".c",
            ".rs", ".php", ".kt", ".swift"}
    return Path(name).suffix.lower() in exts


def _is_log_file(name: str) -> bool:
    stem = name.lower()
    return (
        stem.endswith(".log") or
        "error" in stem or
        "crash" in stem or
        "exception" in stem or
        "warn" in stem or
        "output" in stem
    )


def _is_config_file(name: str) -> bool:
    n = name.lower()
    return any(n.endswith(ext) for ext in [".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".env.example"])


class ReActPlanner:
    """Decides next action in the ReAct investigation loop."""

    def __init__(self, ollama_client: OllamaClient, mcp_client: MCPClientManager):
        self.ollama = ollama_client
        self.mcp_client = mcp_client

    def plan_next_action(self, state: AgentState, model_name: str) -> LLMDecision:
        """
        Decides the next action.  For repository-aware queries this uses a
        deterministic navigator that adapts to the actual directory structure
        returned by list_dir, never confusing directories with files.
        For external/general queries the LLM is asked to decide.
        """
        # Check if user explicitly requested external search
        is_explicit_external = bool(
            re.search(
                r"\b(search github|github issues?|search web|find issues on github|github search)\b",
                state.objective.lower()
            )
        )

        # ------------------------------------------------------------------ #
        # REPOSITORY-AWARE DETERMINISTIC INVESTIGATION PATH                   #
        # ------------------------------------------------------------------ #
        if state.repo_path and not is_explicit_external:
            result = self._plan_repo_investigation(state)
            if result is not None:
                return result
            # If _plan_repo_investigation returns None, fall through to LLM

        # ------------------------------------------------------------------ #
        # LLM-DRIVEN PATH (external queries, or repo exhausted)               #
        # ------------------------------------------------------------------ #
        return self._plan_via_llm(state, model_name, is_explicit_external)

    # ---------------------------------------------------------------------- #
    # REPOSITORY NAVIGATOR                                                    #
    # ---------------------------------------------------------------------- #

    def _plan_repo_investigation(self, state: AgentState) -> Optional[LLMDecision]:
        """
        Deterministic, dynamic navigator for local repository investigation.
        Returns None when it has nothing more to do (caller falls to LLM).
        """
        items = state.evidence_mgr.get_all_evidence()
        local_items = [i for i in items if i.source_type == SourceType.LOCAL_REPO]
        categories = {i.category for i in local_items}
        obj_lower = state.objective.lower()

        # ---------- STEP 1: Directory listing at root ----------
        root_listing = self._get_root_listing(state, local_items)

        if root_listing is None:
            # No directory listing yet → always start here
            return LLMDecision(
                action="tool_call",
                tool_call=ParsedToolCall(
                    tool_name="inspect_local_repository",
                    arguments={"repo_path": state.repo_path, "action": "list_dir"},
                    thought="List root directory to discover the project structure before proceeding."
                ),
                user_status_message="Inspecting repository structure..."
            )

        root_files, root_dirs = root_listing
        root_files_lower = {f.lower() for f in root_files}
        root_dirs_lower = {d.lower() for d in root_dirs}

        # ---------- STEP 2: Dependency manifest ----------
        if EvidenceCategory.DEPENDENCY not in categories:
            return LLMDecision(
                action="tool_call",
                tool_call=ParsedToolCall(
                    tool_name="inspect_local_repository",
                    arguments={"repo_path": state.repo_path, "action": "inspect_dependencies"},
                    thought="Read dependency manifests (requirements.txt / pyproject.toml / setup.py)."
                ),
                user_status_message="Inspecting dependency manifests..."
            )

        # ---------- STEP 3: README (if broad investigation or 'about'/'overview') ----------
        # For repository investigation, we assume it's a broad inspection unless it specifically asks for something else.
        is_broad = True

        readme_names = ["readme.md", "readme.rst", "readme.txt", "readme"]
        has_readme = any(f in root_files_lower for f in readme_names)
        readme_read = any(_already_read("README", state) or _already_read("readme", state)
                          for _ in [None])
        if is_broad and has_readme and not readme_read:
            readme_file = next((f for f in root_files if f.lower() in readme_names), "README.md")
            return LLMDecision(
                action="tool_call",
                tool_call=ParsedToolCall(
                    tool_name="inspect_local_repository",
                    arguments={"repo_path": state.repo_path, "action": "read_file", "target": readme_file},
                    thought="Read README for project purpose and known issues."
                ),
                user_status_message="Reading README..."
            )

        # ---------- STEP 4: Error logs ----------
        # Only do this for broad / problem investigations
        if is_broad and EvidenceCategory.ERROR_TRACE not in categories:
            log_decision = self._plan_log_inspection(state, root_files, root_dirs, local_items)
            if log_decision is not None:
                return log_decision

        # ---------- STEP 5: Source code inspection ----------
        if is_broad or any(w in obj_lower for w in [
            "source", "code", "function", "class", "module", "file", "implementation"
        ]):
            src_decision = self._plan_source_inspection(state, root_files, root_dirs, local_items)
            if src_decision is not None:
                return src_decision

        # ---------- STEP 6: Specific targeted queries ----------

        # Error log only query
        if any(w in obj_lower for w in ["error log", "error_log", "what does the error", "traceback", "stack trace"]):
            if EvidenceCategory.ERROR_TRACE not in categories:
                log_decision = self._plan_log_inspection(state, root_files, root_dirs, local_items)
                if log_decision is not None:
                    return log_decision

        # Dependencies only query
        if any(w in obj_lower for w in ["dependencies", "versions", "requirements", "packages"]):
            if EvidenceCategory.DEPENDENCY not in categories:
                return LLMDecision(
                    action="tool_call",
                    tool_call=ParsedToolCall(
                        tool_name="inspect_local_repository",
                        arguments={"repo_path": state.repo_path, "action": "inspect_dependencies"},
                        thought="Read dependency manifests."
                    ),
                    user_status_message="Inspecting dependency manifests..."
                )
            # Have dependencies, that's sufficient
            return LLMDecision(
                action="final_answer",
                thought="Dependency manifests have been inspected.",
                user_status_message="Finalizing dependency analysis..."
            )

        # ---------- STEP 7: Evidence sufficiency check ----------
        has_source = EvidenceCategory.LOCAL_CODE in categories
        has_error = EvidenceCategory.ERROR_TRACE in categories
        has_deps = EvidenceCategory.DEPENDENCY in categories
        source_files_read = [
            i for i in local_items
            if i.category == EvidenceCategory.LOCAL_CODE
        ]

        if is_broad:
            # For broad investigations require at least deps + (source OR error)
            if not (has_deps and (has_source or has_error)):
                # Still missing critical evidence but ran out of steps — let LLM conclude with incomplete flag
                state.logger.warning("AGENT", "Evidence sufficiency not met before finalizing.")
                return None  # fall to LLM

        # All relevant local evidence collected.
        # Returning None falls through to the LLM to decide on web/github searches
        # or to finalize the investigation if it has enough information.
        return None

    def _get_root_listing(
        self,
        state: AgentState,
        local_items: List[Any]
    ) -> Optional[Tuple[List[str], List[str]]]:
        """
        Returns (files, dirs) for the root listing, or None if not yet done.
        The root listing has url_or_path == repo_path (no subdir appended).
        """
        repo_norm = (state.repo_path or "").replace("\\", "/").rstrip("/").lower()
        for item in local_items:
            if item.title and "directory structure" in item.title.lower():
                item_path_norm = item.url_or_path.replace("\\", "/").rstrip("/").lower()
                # Root listing: url_or_path matches repo_path exactly
                if item_path_norm == repo_norm:
                    return _parse_dir_listing(item.finding)
        return None

    def _plan_log_inspection(
        self,
        state: AgentState,
        root_files: List[str],
        root_dirs: List[str],
        local_items: List[Any]
    ) -> Optional[LLMDecision]:
        """
        Returns a decision to list a logs dir or read a log file.
        Never calls read_file on a directory.
        """
        root_dirs_lower = {d.lower(): d for d in root_dirs}
        root_files_lower = {f.lower(): f for f in root_files}

        # Check if a logs/ directory exists at root
        for log_dir_name in LOG_DIRS:
            if log_dir_name in root_dirs_lower:
                actual_dir_name = root_dirs_lower[log_dir_name]
                # Check if we already have a listing of this log dir
                log_dir_listed = self._has_subdir_listing(state, actual_dir_name, local_items)
                if not log_dir_listed:
                    return LLMDecision(
                        action="tool_call",
                        tool_call=ParsedToolCall(
                            tool_name="inspect_local_repository",
                            arguments={
                                "repo_path": state.repo_path,
                                "action": "list_dir",
                                "target": actual_dir_name
                            },
                            thought=f"List '{actual_dir_name}/' directory to find actual log files."
                        ),
                        user_status_message=f"Listing {actual_dir_name}/ directory..."
                    )
                # Already have listing → find log files and read them
                log_dir_files = self._get_subdir_files(state, actual_dir_name, local_items)
                for log_file in log_dir_files:
                    if _is_log_file(log_file):
                        full_path = f"{actual_dir_name}/{log_file}"
                        if not _already_read(full_path, state):
                            return LLMDecision(
                                action="tool_call",
                                tool_call=ParsedToolCall(
                                    tool_name="inspect_local_repository",
                                    arguments={
                                        "repo_path": state.repo_path,
                                        "action": "read_file",
                                        "target": full_path
                                    },
                                    thought=f"Read log file '{full_path}' for runtime errors and exceptions."
                                ),
                                user_status_message=f"Reading {full_path}..."
                            )

        # Check for root-level log/error files
        log_file_candidates = [
            f for f in root_files
            if _is_log_file(f)
        ]
        for log_file in log_file_candidates:
            if not _already_read(log_file, state):
                return LLMDecision(
                    action="tool_call",
                    tool_call=ParsedToolCall(
                        tool_name="inspect_local_repository",
                        arguments={
                            "repo_path": state.repo_path,
                            "action": "read_file",
                            "target": log_file
                        },
                        thought=f"Read log file '{log_file}' for runtime errors and exceptions."
                    ),
                    user_status_message=f"Reading {log_file}..."
                )

        return None  # No log files found to inspect

    def _plan_source_inspection(
        self,
        state: AgentState,
        root_files: List[str],
        root_dirs: List[str],
        local_items: List[Any]
    ) -> Optional[LLMDecision]:
        """
        Dynamically navigate source code directories and read relevant source files.
        Never calls read_file on a directory.
        """
        categories = {i.category for i in local_items}
        root_dirs_lower = {d.lower(): d for d in root_dirs}
        root_files_lower = {f.lower(): f for f in root_files}

        # Count source files already read
        source_items_read = [
            i for i in local_items
            if i.category == EvidenceCategory.LOCAL_CODE
        ]
        if len(source_items_read) >= MAX_SOURCE_FILES:
            return None  # Enough source code already read

        # First: prioritize files mentioned in error logs
        error_items = [i for i in local_items if i.category == EvidenceCategory.ERROR_TRACE]
        for item in error_items:
            for match in re.finditer(r'([a-zA-Z0-9_/\\]+\.py)', item.finding):
                # Extract plausible local paths
                path_str = match.group(1).replace('\\', '/')
                # E.g., if path is /some/absolute/path/app/models.py, try to get the relative part
                if 'app/' in path_str:
                    path_str = 'app/' + path_str.split('app/', 1)[1]
                elif 'src/' in path_str:
                    path_str = 'src/' + path_str.split('src/', 1)[1]
                
                # It might just be 'main.py' or 'app/models.py'
                if not _already_read(path_str, state) and not _already_read(path_str.split('/')[-1], state):
                     return LLMDecision(
                        action="tool_call",
                        tool_call=ParsedToolCall(
                            tool_name="inspect_local_repository",
                            arguments={
                                "repo_path": state.repo_path,
                                "action": "read_file",
                                "target": path_str
                            },
                            thought=f"Read source file '{path_str}' mentioned in error traceback."
                        ),
                        user_status_message=f"Reading {path_str} from traceback..."
                    )

        # Second: explore source directories
        for src_dir in SOURCE_CODE_DIRS:
            if src_dir not in root_dirs_lower:
                continue
            actual_dir = root_dirs_lower[src_dir]
            # Get listing of source dir
            if not self._has_subdir_listing(state, actual_dir, local_items):
                return LLMDecision(
                    action="tool_call",
                    tool_call=ParsedToolCall(
                        tool_name="inspect_local_repository",
                        arguments={
                            "repo_path": state.repo_path,
                            "action": "list_dir",
                            "target": actual_dir
                        },
                        thought=f"List '{actual_dir}/' to discover source files and sub-packages."
                    ),
                    user_status_message=f"Listing {actual_dir}/ directory..."
                )

            # We have a listing of src_dir → recurse into it
            src_decision = self._read_from_dir(state, actual_dir, local_items, depth=0)
            if src_decision is not None:
                return src_decision

        # Second: read interesting root-level source files (e.g., main.py, cli.py)
        root_source_candidates = [
            f for f in root_files
            if _is_source_file(f)
        ]
        for f in root_source_candidates:
            if not _already_read(f, state):
                return LLMDecision(
                    action="tool_call",
                    tool_call=ParsedToolCall(
                        tool_name="inspect_local_repository",
                        arguments={
                            "repo_path": state.repo_path,
                            "action": "read_file",
                            "target": f
                        },
                        thought=f"Read root source file '{f}' for application entry-point logic."
                    ),
                    user_status_message=f"Reading {f}..."
                )

        return None

    def _read_from_dir(
        self,
        state: AgentState,
        dir_path: str,
        local_items: List[Any],
        depth: int = 0
    ) -> Optional[LLMDecision]:
        """
        Given a listed directory, try to read the most interesting source file from it.
        Will recurse one level into sub-packages if needed.
        """
        files = self._get_subdir_files(state, dir_path, local_items)
        sub_dirs = self._get_subdir_dirs(state, dir_path, local_items)

        # Read interesting source files first
        priority_names = [
            "main.py", "app.py", "cli.py", "__main__.py",
            "models.py", "routes.py", "router.py", "api.py",
            "server.py", "handler.py", "manager.py", "utils.py"
        ]
        # Sort: priority names first, then all other source files
        sorted_files = (
            [f for f in files if f.lower() in priority_names] +
            [f for f in files if f.lower() not in priority_names and _is_source_file(f)]
        )

        for f in sorted_files:
            full_path = f"{dir_path}/{f}"
            if not _already_read(full_path, state):
                return LLMDecision(
                    action="tool_call",
                    tool_call=ParsedToolCall(
                        tool_name="inspect_local_repository",
                        arguments={
                            "repo_path": state.repo_path,
                            "action": "read_file",
                            "target": full_path
                        },
                        thought=f"Read source file '{full_path}' to analyze application logic."
                    ),
                    user_status_message=f"Reading {full_path}..."
                )

        # Recurse into sub-packages (one level only) if no files found yet
        if depth < 1:
            for sub in sub_dirs:
                if sub.lower() in SKIP_DIRS:
                    continue
                sub_path = f"{dir_path}/{sub}"
                if not self._has_subdir_listing(state, sub_path, local_items):
                    return LLMDecision(
                        action="tool_call",
                        tool_call=ParsedToolCall(
                            tool_name="inspect_local_repository",
                            arguments={
                                "repo_path": state.repo_path,
                                "action": "list_dir",
                                "target": sub_path
                            },
                            thought=f"List sub-package '{sub_path}/' to discover source files."
                        ),
                        user_status_message=f"Listing {sub_path}/..."
                    )
                result = self._read_from_dir(state, sub_path, local_items, depth=depth + 1)
                if result is not None:
                    return result

        return None

    def _has_subdir_listing(
        self,
        state: AgentState,
        dir_name: str,
        local_items: List[Any]
    ) -> bool:
        """Return True if there is an evidence item that listed dir_name/."""
        dir_lower = dir_name.replace("\\", "/").lower()
        for item in local_items:
            if item.title and "directory structure" in item.title.lower():
                path_in_item = item.url_or_path.replace("\\", "/").lower()
                if path_in_item.endswith(dir_lower) or path_in_item.endswith(dir_lower + "/"):
                    return True
                # Also check the finding for the listed path
                if dir_lower in item.finding.lower()[:100]:
                    pass  # not reliable enough
        return False

    def _get_subdir_files(
        self,
        state: AgentState,
        dir_name: str,
        local_items: List[Any]
    ) -> List[str]:
        """Return files listed inside dir_name, from evidence."""
        dir_lower = dir_name.replace("\\", "/").lower()
        for item in local_items:
            if item.title and "directory structure" in item.title.lower():
                path_in_item = item.url_or_path.replace("\\", "/").lower()
                if path_in_item.endswith(dir_lower) or path_in_item.endswith(dir_lower + "/"):
                    files, _ = _parse_dir_listing(item.finding)
                    return files
        return []

    def _get_subdir_dirs(
        self,
        state: AgentState,
        dir_name: str,
        local_items: List[Any]
    ) -> List[str]:
        """Return sub-directories listed inside dir_name, from evidence."""
        dir_lower = dir_name.replace("\\", "/").lower()
        for item in local_items:
            if item.title and "directory structure" in item.title.lower():
                path_in_item = item.url_or_path.replace("\\", "/").lower()
                if path_in_item.endswith(dir_lower) or path_in_item.endswith(dir_lower + "/"):
                    _, dirs = _parse_dir_listing(item.finding)
                    return dirs
        return []

    # ---------------------------------------------------------------------- #
    # LLM-DRIVEN DECISION PATH                                                #
    # ---------------------------------------------------------------------- #

    def _plan_via_llm(
        self,
        state: AgentState,
        model_name: str,
        is_explicit_external: bool
    ) -> LLMDecision:
        """Ask the LLM for the next action (used for external queries)."""
        
        # DETERMINISTIC RULE: Search -> Fetch flow
        # After a search_web call, automatically fetch the top unfetched result.
        # Use state.fetched_urls (set per-run) to avoid refetching and infinite loops.
        unfetched = [
            item for item in state.evidence_mgr.items
            if item.verification_status == "RETRIEVED"
            and item.url_or_path not in state.fetched_urls
        ]

        recent_search = bool(state.history and state.history[-1].get("tool_name") in ("search_web", "search_github_issues"))

        if unfetched and recent_search:
            target_url = unfetched[0].url_or_path
            state.fetched_urls.add(target_url)  # mark immediately to prevent re-selection
            state.logger.info("AGENT", f"Auto-fetching search result: {target_url}")
            return LLMDecision(
                action="tool_call",
                tool_call=ParsedToolCall(
                    tool_name="fetch_web_document",
                    arguments={"url": target_url},
                    thought=f"Fetching full content of top search result: {target_url}"
                ),
                user_status_message="Fetching web document for verification..."
            )

        tools_prompt_str = self.mcp_client.format_tools_for_prompt()
        system_content = REACT_SYSTEM_PROMPT.format(mcp_tools_description=tools_prompt_str)

        user_prompt = f"USER RESEARCH OBJECTIVE: {state.objective}\n"
        if state.repo_path and not is_explicit_external:
            user_prompt += f"ACTIVE LOCAL WORKSPACE / REPOSITORY PATH: {state.repo_path}\n"
        else:
            user_prompt += "LOCAL WORKSPACE: None provided (External research required).\n"

        user_prompt += f"\nCURRENT ITERATION: {state.iteration + 1} / {state.max_iterations}\n"
        user_prompt += f"MCP CALLS USED: {state.mcp_call_count} / {state.max_mcp_calls}\n"

        evidence_str = state.evidence_mgr.format_evidence_for_prompt()
        user_prompt += f"\nCOLLECTED EVIDENCE SO FAR:\n{evidence_str}\n"

        if state.history:
            user_prompt += "\nRECENT ACTION HISTORY & TOOL OBSERVATIONS:\n"
            for item in state.history[-4:]:
                tool_prefix = f"[{item.get('tool_name')}] " if item.get('tool_name') else ""
                user_prompt += f"- {item['role'].upper()}: {tool_prefix}{item['content'][:350]}\n"

        user_prompt += "\nDecide next action in JSON:"

        messages = [
            ChatMessage(role=Role.SYSTEM, content=system_content),
            ChatMessage(role=Role.USER, content=user_prompt)
        ]

        state.logger.info("LLM", f"Requesting action decision from LLM ({model_name})...")
        llm_resp = self.ollama.chat(
            messages=messages,
            model=model_name,
            temperature=state.temperature,
            format_json=True
        )

        state.tracker.record_llm_call(
            latency_sec=llm_resp["latency_sec"],
            prompt_tokens=llm_resp.get("prompt_tokens", 0),
            eval_tokens=llm_resp.get("eval_tokens", 0)
        )

        if not llm_resp["success"]:
            state.logger.warning("LLM", f"Initial planner call failed ({llm_resp['error']}). Retrying...")
            minimal_prompt = (
                f"OBJECTIVE: {state.objective}\n"
                f"ITERATION: {state.iteration + 1}/{state.max_iterations}\n"
                f"TOOLS: search_web(query), search_github_issues(query), "
                f"fetch_web_document(url), inspect_local_repository(repo_path, action)\n\n"
                f"Respond with JSON:\n"
                f'{{"action": "tool_call", "thought": "Need external evidence", '
                f'"user_status_message": "Searching...", '
                f'"tool_call": {{"tool_name": "search_web", '
                f'"arguments": {{"query": "{state.objective}"}}}}}}'
            )
            retry_resp = self.ollama.chat(
                messages=[ChatMessage(role=Role.USER, content=minimal_prompt)],
                model=model_name,
                temperature=0.0,
                format_json=True
            )
            state.tracker.record_llm_call(
                latency_sec=retry_resp["latency_sec"],
                prompt_tokens=retry_resp.get("prompt_tokens", 0),
                eval_tokens=retry_resp.get("eval_tokens", 0)
            )
            if retry_resp["success"]:
                llm_resp = retry_resp
            else:
                state.logger.error("LLM", f"Retry planner call failed: {retry_resp['error']}")
                state.tracker.record_error()
                return LLMDecision(
                    action="decision_failed",
                    thought="LLM decision step failed after retry.",
                    user_status_message="Agent decision step failed."
                )

        raw_text = llm_resp["content"]
        parsed_json = OllamaClient.extract_json(raw_text)

        if not parsed_json or not isinstance(parsed_json, dict):
            state.logger.warning("LLM", "LLM output was not valid JSON, concluding investigation.")
            return LLMDecision(
                action=(
                    "decision_failed"
                    if (state.query_classification.get("evidence_required") and len(state.evidence_mgr.items) == 0)
                    else "final_answer"
                ),
                thought="Could not parse LLM JSON decision.",
                user_status_message="Finalizing analysis..."
            )

        action = str(parsed_json.get("action", "")).strip()
        user_msg = parsed_json.get("user_status_message", "Investigating...")
        thought = parsed_json.get("thought", "")

        # Resolve tool name from various JSON shapes
        tname = None
        if isinstance(parsed_json.get("tool_call"), dict):
            tname = parsed_json["tool_call"].get("tool_name")
        elif isinstance(parsed_json.get("tool_call"), str) and parsed_json["tool_call"] in self.mcp_client.tools:
            tname = parsed_json["tool_call"]
        elif parsed_json.get("tool_name") in self.mcp_client.tools:
            tname = parsed_json.get("tool_name")
        elif action in self.mcp_client.tools:
            tname = action

        if tname and tname in self.mcp_client.tools:
            targs: Dict[str, Any] = {}
            if isinstance(parsed_json.get("tool_call"), dict) and isinstance(parsed_json["tool_call"].get("arguments"), dict):
                targs = parsed_json["tool_call"]["arguments"]
            elif isinstance(parsed_json.get("arguments"), dict):
                targs = parsed_json["arguments"]
            else:
                tool_schema = self.mcp_client.tools[tname].inputSchema
                for k in tool_schema.get("properties", {}).keys():
                    if k in parsed_json:
                        targs[k] = parsed_json[k]

            # Sanitize arguments: strip any fields that are RESPONSE-only fields
            # that the small LLM may hallucinate back into tool call arguments.
            targs = self._sanitize_tool_args(tname, targs)

            # Enforce local repo before external when repo is set and no local evidence yet
            if state.repo_path and not is_explicit_external:
                local_evidence = [e for e in state.evidence_mgr.get_all_evidence()
                                  if e.source_type == SourceType.LOCAL_REPO]
                if not local_evidence and tname in ["search_github_issues", "search_web", "fetch_web_document"]:
                    state.logger.info("AGENT", "Redirecting to local inspection before external research.")
                    tname = "inspect_local_repository"
                    targs = {"repo_path": state.repo_path, "action": "list_dir"}
                    user_msg = "Inspecting local repository structure..."
                    thought = "Local repository must be inspected before external research."

            if tname == "inspect_local_repository":
                if not state.repo_path:
                    state.logger.warning("AGENT", "Intercepted hallucinatory inspect_local_repository call without a repo_path.")
                    tname = "search_web"
                    targs = {"query": self._extract_focused_search_query(state)}
                    thought = "External search required since no local repository was provided."
                    user_msg = "Searching web..."
                else:
                    targs["repo_path"] = state.repo_path
                    if "action" not in targs:
                        targs["action"] = "inspect_dependencies"

            if tname in ["search_github_issues", "search_web"]:
                raw_q = str(targs.get("query", "")).strip()
                if not raw_q or raw_q == state.objective or "sample project" in raw_q.lower():
                    targs["query"] = self._extract_focused_search_query(state)

            if tname == "fetch_web_document":
                req_url = str(targs.get("url", "")).strip()
                known_retrieved_urls = {item.url_or_path for item in state.evidence_mgr.items if item.verification_status == "RETRIEVED"}
                if req_url not in known_retrieved_urls:
                    state.logger.warning("AGENT", f"Intercepted hallucinated URL: {req_url}")
                    # Find a real unfetched URL from our evidence
                    unfetched_candidates = [u for u in known_retrieved_urls if u not in state.fetched_urls]
                    if unfetched_candidates:
                        req_url = unfetched_candidates[0]
                        targs["url"] = req_url
                    else:
                        tname = "search_web"
                        targs = {"query": self._extract_focused_search_query(state)}
                        user_msg = "Searching external sources..."
                        thought = "No valid known URLs to fetch; starting new search."
                if tname == "fetch_web_document":
                    state.fetched_urls.add(targs.get("url", ""))

            return LLMDecision(
                action="tool_call",
                tool_call=ParsedToolCall(tool_name=tname, arguments=targs, thought=thought),
                user_status_message=user_msg
            )

        if action == "final_answer" or "final" in action.lower():
            # Don't finalize prematurely with no evidence and evidence required
            if (
                state.iteration <= 2
                and not state.repo_path
                and state.query_classification.get("evidence_required")
                and len(state.evidence_mgr.items) == 0
            ):
                state.logger.info("AGENT", "Auto-initiating external research for required evidence...")
                return LLMDecision(
                    action="tool_call",
                    tool_call=ParsedToolCall(
                        tool_name="search_web",
                        arguments={"query": state.objective},
                        thought="External research required before concluding."
                    ),
                    user_status_message="Searching external sources..."
                )
            
            # Don't finalize prematurely for repo investigations
            if state.repo_path and state.query_classification.get("local_repository_required"):
                items = state.evidence_mgr.get_all_evidence()
                local_items = [i for i in items if i.source_type == SourceType.LOCAL_REPO]
                categories = {i.category for i in local_items}
                has_source = EvidenceCategory.LOCAL_CODE in categories
                has_error = EvidenceCategory.ERROR_TRACE in categories
                has_deps = EvidenceCategory.DEPENDENCY in categories
                
                if not (has_deps and (has_source or has_error)) and state.iteration < state.max_iterations - 1:
                    state.logger.info("AGENT", "Intercepted premature final_answer. Redirecting to local inspection.")
                    return LLMDecision(
                        action="tool_call",
                        tool_call=ParsedToolCall(
                            tool_name="inspect_local_repository",
                            arguments={"repo_path": state.repo_path, "action": "list_dir"},
                            thought="Must collect dependencies, logs, and source before finalizing."
                        ),
                        user_status_message="Continuing repository inspection..."
                    )

            # Ensure retrieved web snippets are actually verified (fetched) before finalizing.
            # Use state.fetched_urls to avoid re-selecting URLs we already attempted.
            if state.iteration < state.max_iterations - 1:
                unfetched_candidates = [
                    item.url_or_path for item in state.evidence_mgr.get_all_evidence()
                    if item.verification_status == "RETRIEVED"
                    and item.url_or_path not in state.fetched_urls
                ]
                if unfetched_candidates:
                    target_url = unfetched_candidates[0]
                    state.fetched_urls.add(target_url)  # mark before dispatching
                    state.logger.info("AGENT", f"Intercepting premature final_answer — fetching unverified result: {target_url}")
                    return LLMDecision(
                        action="tool_call",
                        tool_call=ParsedToolCall(
                            tool_name="fetch_web_document",
                            arguments={"url": target_url},
                            thought=f"Must read full document to verify the search snippet from: {target_url}"
                        ),
                        user_status_message=f"Fetching document for verification..."
                    )

            return LLMDecision(
                action="final_answer",
                thought=thought,
                user_status_message=user_msg,
                unresolved_questions=parsed_json.get("unresolved_questions", [])
            )

        # Fallback: if no valid tool and no final_answer
        if state.repo_path and not is_explicit_external and len(state.evidence_mgr.items) == 0:
            return LLMDecision(
                action="tool_call",
                tool_call=ParsedToolCall(
                    tool_name="inspect_local_repository",
                    arguments={"repo_path": state.repo_path, "action": "list_dir"},
                    thought="Starting local repository inspection."
                ),
                user_status_message="Inspecting repository structure..."
            )

        return LLMDecision(
            action="final_answer",
            thought=thought,
            user_status_message=user_msg
        )

    @staticmethod
    def _extract_focused_search_query(state: AgentState) -> str:
        """Derive a concise, focused technical search query from gathered local findings."""
        items = state.evidence_mgr.get_all_evidence()
        error_item = next((item for item in items if item.category == EvidenceCategory.ERROR_TRACE), None)
        if error_item and error_item.finding:
            for line in error_item.finding.splitlines():
                if "Error" in line or "Exception" in line or "deprecated" in line.lower():
                    clean_line = line.strip()
                    if ":" in clean_line:
                        clean_line = clean_line.split(":", 1)[1].strip()
                    clean_line = re.sub(r"[`'\"]", "", clean_line)
                    if len(clean_line) > 10:
                        return clean_line[:100]
        obj = state.objective.lower()
        keywords: List[str] = []
        for kw in ["FastAPI", "Pydantic", "Django", "SQLAlchemy", "asyncio", "celery"]:
            if kw.lower() in obj:
                keywords.append(kw)
        if "v2" in obj or "version 2" in obj:
            keywords.append("v2")
        if "validator" in obj:
            keywords.append("validator")
        if keywords:
            return " ".join(keywords) + " compatibility migration"

        # Build a smarter query from gathered local evidence
        dep_item = next((item for item in items if item.category == EvidenceCategory.DEPENDENCY), None)
        src_item = next((item for item in items if item.category == EvidenceCategory.LOCAL_CODE), None)

        # Extract key library names from dependencies
        dep_keywords: List[str] = []
        if dep_item and dep_item.finding:
            for line in dep_item.finding.splitlines():
                match = re.match(r'^([a-zA-Z][a-zA-Z0-9_-]+)', line.strip())
                if match:
                    pkg = match.group(1).lower()
                    if pkg not in {"python", "pip", "setuptools", "wheel"}:
                        dep_keywords.append(match.group(1))

        # Build a concise keyword query from objective and gathered dependencies
        filler = {
            "tell", "me", "what", "changes", "can", "i", "make", "in", "this",
            "type", "of", "project", "do", "a", "web", "search", "and", "how",
            "why", "is", "my", "the", "for", "to", "an", "on", "with", "about",
            "please", "give", "provide", "suggest", "recommend", "how", "many"
        }
        obj_words = [w for w in re.findall(r'[a-zA-Z0-9_.-]+', state.objective) if w.lower() not in filler]

        # Combine with discovered libraries
        combined_keywords = []
        for kw in obj_words + dep_keywords:
            if kw.lower() not in [k.lower() for k in combined_keywords]:
                combined_keywords.append(kw)

        if combined_keywords:
            return " ".join(combined_keywords[:5]) + " best practices"
        return "Python application architecture reliability best practices"

    @staticmethod
    def _sanitize_tool_args(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Strip fields that appear in tool RESPONSES but are not valid tool INPUT arguments.
        Small LLMs often hallucinate response-only fields back into tool calls.
        """
        # Fields that appear in inspect_local_repository RESPONSES, not inputs
        RESPONSE_ONLY_FIELDS = {
            "inspect_local_repository": {
                "entries", "file_path", "content", "total_lines",
                "dependencies", "matches", "status", "error"
            },
            "search_web": {
                "results", "results_count", "error"
            },
            "search_github_issues": {
                "issues", "error"
            },
            "fetch_web_document": {
                "title", "text", "truncated", "error"
            },
        }
        bad_fields = RESPONSE_ONLY_FIELDS.get(tool_name, set())
        return {k: v for k, v in args.items() if k not in bad_fields}
