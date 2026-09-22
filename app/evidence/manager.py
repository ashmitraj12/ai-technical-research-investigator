"""
Evidence Manager for processing, deduplicating, validating, and formatting investigation evidence.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.evidence.models import EvidenceItem, ReliabilityLevel, SourceType, EvidenceCategory

logger = logging.getLogger(__name__)


class EvidenceManager:
    """Manages evidence collection, validation, and claim grounding during an investigation."""

    def __init__(self):
        self.items: List[EvidenceItem] = []
        self._counter = 0

    def add_evidence(
        self,
        source: str,
        source_type: SourceType,
        title: str,
        url_or_path: str,
        finding: str,
        category: EvidenceCategory = EvidenceCategory.GENERAL,
        reliability: ReliabilityLevel = ReliabilityLevel.MEDIUM,
        verification_status: str = "VERIFIED",
        relationship: str = "Relevant finding",
        supports_claim: Optional[str] = None,
        timestamp: Optional[str] = None,
        relevant: bool = True,
    ) -> EvidenceItem:
        """Add a new evidence item, skipping duplicates."""
        # Deduplication check
        for existing in self.items:
            if existing.url_or_path == url_or_path and existing.title == title:
                return existing

        self._counter += 1
        item_id = f"EVD-{self._counter:03d}"
        now_ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        item = EvidenceItem(
            id=item_id,
            source=source,
            source_type=source_type,
            category=category,
            title=title,
            url_or_path=url_or_path,
            finding=finding.strip(),
            reliability=reliability,
            verification_status=verification_status,
            supports_claim=supports_claim,
            relationship_to_conclusion=relationship,
            timestamp=now_ts,
            retrieved_at=now_ts,
            relevant=relevant,
        )
        self.items.append(item)
        return item

    def ingest_mcp_result(self, tool_name: str, arguments: Dict[str, Any], result: Dict[str, Any]):
        """
        Processes and validates raw MCP tool output into structured EvidenceItems.
        Does NOT treat failed results or irrelevant noise as verified evidence.
        """
        if not result or not isinstance(result, dict):
            return

        # Check for error payload
        if "error" in result or result.get("status") in ["FILE_NOT_FOUND", "NOT_A_DIRECTORY", "ERROR"]:
            return

        if tool_name == "inspect_local_repository":
            repo_path = arguments.get("repo_path", "")
            action = arguments.get("action", "")

            if action == "list_dir":
                entries = result.get("entries", [])
                if entries:
                    import json as _json
                    # Determine the actual directory that was listed (root or subdir)
                    target_sub = arguments.get("target", "") or ""
                    if target_sub:
                        listed_path = repo_path.rstrip("/\\") + "/" + target_sub.strip("/\\")
                    else:
                        listed_path = repo_path
                    # Store full entry list as JSON so planner can distinguish files/dirs
                    finding_str = _json.dumps(entries, ensure_ascii=False)
                    entry_names = [e.get("name") for e in entries if isinstance(e, dict)]
                    title = f"Repository Directory Structure: {target_sub or '(root)'}"
                    self.add_evidence(
                        source="Local Workspace Structure",
                        source_type=SourceType.LOCAL_REPO,
                        category=EvidenceCategory.GENERAL,
                        title=title,
                        url_or_path=listed_path,
                        finding=finding_str,
                        reliability=ReliabilityLevel.HIGH,
                        verification_status="VERIFIED",
                        relationship="Identifies available configuration, manifest, and source files."
                    )

            elif action == "inspect_dependencies":
                deps = result.get("dependencies", {})
                for fname, content in deps.items():
                    finding_str = content if isinstance(content, str) else "\n".join(content)
                    self.add_evidence(
                        source=f"Local Dependency Manifest ({fname})",
                        source_type=SourceType.LOCAL_REPO,
                        category=EvidenceCategory.DEPENDENCY,
                        title=f"Dependencies manifest: {fname}",
                        url_or_path=f"{repo_path}/{fname}",
                        finding=finding_str[:500] + '...' if len(finding_str) > 500 else finding_str,
                        reliability=ReliabilityLevel.HIGH,
                        verification_status="VERIFIED",
                        relationship="Declares explicit pinned dependency versions.",
                        supports_claim="Project uses specific package versions that may have breaking incompatibilities."
                    )

            elif action == "read_file":
                fpath = result.get("file_path", arguments.get("target", ""))
                content = result.get("content", "")
                if content and len(content.strip()) > 0:
                    is_error_log = "error" in str(fpath).lower() or "traceback" in content.lower() or str(fpath).lower().endswith(".log")
                    category = EvidenceCategory.ERROR_TRACE if is_error_log else EvidenceCategory.LOCAL_CODE
                    self.add_evidence(
                        source="Local File Inspection",
                        source_type=SourceType.LOCAL_REPO,
                        category=category,
                        title=f"Local File: {fpath}",
                        url_or_path=str(fpath),
                        finding=content[:800] + '...' if len(content) > 800 else content,
                        reliability=ReliabilityLevel.HIGH,
                        verification_status="VERIFIED",
                        relationship="Direct local code pattern or captured runtime stack trace.",
                        supports_claim="Shows exact code implementation or error triggering the issue."
                    )

            elif action == "search_code":
                matches = result.get("matches", [])
                for m in matches[:5]:
                    self.add_evidence(
                        source="Local Code Search",
                        source_type=SourceType.LOCAL_REPO,
                        category=EvidenceCategory.LOCAL_CODE,
                        title=f"Code match in {m.get('file')}:{m.get('line_number')}",
                        url_or_path=f"{repo_path}/{m.get('file')}",
                        finding=f"Line {m.get('line_number')}: {m.get('line', '')}",
                        reliability=ReliabilityLevel.HIGH,
                        verification_status="VERIFIED",
                        relationship="Relevant local usage pattern matching search term."
                    )

        elif tool_name == "search_github_issues":
            issues = result.get("issues", [])
            for issue in issues[:4]:
                title = issue.get("title", "GitHub Issue")
                url = issue.get("url", "https://github.com")
                body = issue.get("body_snippet", "")
                if not body or len(body.strip()) < 15:
                    continue
                
                is_official = "official" in title.lower() or "fastapi" in url.lower() or "pydantic" in url.lower()
                rel = ReliabilityLevel.HIGH if is_official else ReliabilityLevel.MEDIUM
                
                self.add_evidence(
                    source="GitHub Research",
                    source_type=SourceType.GITHUB_ISSUE,
                    category=EvidenceCategory.COMMUNITY_REPORT,
                    title=title,
                    url_or_path=url,
                    finding=body,
                    reliability=rel,
                    verification_status="RETRIEVED",
                    relationship="Community report or issue tracker discussion regarding the problem."
                )

        elif tool_name == "search_web":
            results = result.get("results", [])
            for r in results[:4]:
                url = r.get("url", "")
                snippet = r.get("snippet", "")
                if not snippet or len(snippet.strip()) < 20:
                    continue

                is_doc = any(d in url for d in ["docs.", "python.org", "fastapi.tiangolo.com", "pydantic.dev", "pydantic.run"])
                stype = SourceType.OFFICIAL_DOCS if is_doc else SourceType.WEB_SEARCH
                cat = EvidenceCategory.OFFICIAL_DOC if is_doc else EvidenceCategory.COMMUNITY_REPORT
                rel = ReliabilityLevel.HIGH if is_doc else ReliabilityLevel.MEDIUM
                # A search engine snippet is only a candidate.  It must be
                # fetched and its content assessed before it can be verified.
                vstatus = "RETRIEVED"

                self.add_evidence(
                    source="Official Documentation" if is_doc else "Web Research",
                    source_type=stype,
                    category=cat,
                    title=r.get("title", "Web Finding"),
                    url_or_path=url,
                    finding=snippet,
                    reliability=rel,
                    verification_status=vstatus,
                    relationship="Public documentation or technical advisory finding.",
                    supports_claim=None,
                    relevant=True,
                )

        elif tool_name == "fetch_web_document":
            url = result.get("url", "")
            title = result.get("title", "Web Document")
            text = result.get("text", "")
            if text and len(text.strip()) > 30:
                is_doc = any(d in url for d in ["docs.", "python.org", "fastapi.tiangolo.com", "pydantic.dev"])
                stype = SourceType.OFFICIAL_DOCS if is_doc else SourceType.WEB_SEARCH
                self.add_evidence(
                    source="Web Document Extraction",
                    source_type=stype,
                    category=EvidenceCategory.OFFICIAL_DOC if is_doc else EvidenceCategory.GENERAL,
                    title=title,
                    url_or_path=url,
                    finding=text[:1000] + '...' if len(text) > 1000 else text,
                    reliability=ReliabilityLevel.HIGH if is_doc else ReliabilityLevel.MEDIUM,
                    verification_status="VERIFIED",
                    relationship="Extracted web page content for detailed verification.",
                    supports_claim="Supports a documented compatibility or migration claim.",
                    relevant=True,
                )

    def get_all_evidence(self) -> List[EvidenceItem]:
        return self.items

    def get_verified_evidence(self) -> List[EvidenceItem]:
        return [e for e in self.items if e.verification_status == "VERIFIED" and e.relevant]

    def format_evidence_for_prompt(self) -> str:
        if not self.items:
            return "No evidence collected yet."
        
        lines = []
        for item in self.items:
            lines.append(f"[{item.id}] Source: {item.source} ({item.source_type.value} | {item.category.value})")
            lines.append(f"  Title: {item.title}")
            lines.append(f"  URL/Path: {item.url_or_path}")
            lines.append(f"  Reliability: {item.reliability.value} | Status: {item.verification_status}")
            lines.append(f"  Finding: {item.finding}")
            if item.supports_claim:
                lines.append(f"  Supports Claim: {item.supports_claim}")
            lines.append("")
        return "\n".join(lines)
