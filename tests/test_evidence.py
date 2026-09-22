"""
Unit tests for Evidence Manager and structured Evidence objects.
"""

import pytest
from app.evidence.manager import EvidenceManager
from app.evidence.models import SourceType, ReliabilityLevel


def test_evidence_addition_and_deduplication():
    mgr = EvidenceManager()
    item1 = mgr.add_evidence(
        source="Official Docs",
        source_type=SourceType.OFFICIAL_DOCS,
        title="FastAPI Release Notes",
        url_or_path="https://fastapi.tiangolo.com",
        finding="Python 3.14 deprecation note",
        reliability=ReliabilityLevel.HIGH
    )
    
    assert item1.id == "EVD-001"
    assert len(mgr.items) == 1

    # Add exact duplicate
    item2 = mgr.add_evidence(
        source="Official Docs",
        source_type=SourceType.OFFICIAL_DOCS,
        title="FastAPI Release Notes",
        url_or_path="https://fastapi.tiangolo.com",
        finding="Python 3.14 deprecation note",
        reliability=ReliabilityLevel.HIGH
    )
    assert len(mgr.items) == 1
    assert item2.id == "EVD-001"


def test_mcp_result_ingestion_github():
    mgr = EvidenceManager()
    github_mock_result = {
        "issues": [
            {
                "title": "FastAPI fails on Python 3.14",
                "url": "https://github.com/fastapi/fastapi/issues/999",
                "body_snippet": "Pydantic v2 core compatibility issue on 3.14 alpha"
            }
        ]
    }
    
    mgr.ingest_mcp_result(
        tool_name="search_github_issues",
        arguments={"query": "fastapi python 3.14"},
        result=github_mock_result
    )
    
    assert len(mgr.items) == 1
    assert mgr.items[0].source_type == SourceType.GITHUB_ISSUE
    assert "FastAPI fails" in mgr.items[0].title
