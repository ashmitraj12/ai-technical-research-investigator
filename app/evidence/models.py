"""
Evidence Data Models for Technical Research Investigator.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum


class ReliabilityLevel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class SourceType(str, Enum):
    OFFICIAL_DOCS = "Official Documentation"
    GITHUB_ISSUE = "GitHub Issue / PR"
    LOCAL_REPO = "Local Repository / Code"
    WEB_SEARCH = "Web Advisory / Article"
    RELEASE_NOTES = "Release Notes / Changelog"
    UNKNOWN = "Unknown Source"


class EvidenceCategory(str, Enum):
    ERROR_TRACE = "Error Information"
    DEPENDENCY = "Dependency Specification"
    LOCAL_CODE = "Local Source Code"
    OFFICIAL_DOC = "Official Documentation"
    COMMUNITY_REPORT = "Community Report / Issue"
    GENERAL = "General Technical Fact"


class EvidenceItem(BaseModel):
    id: str = Field(description="Unique evidence identifier e.g. EVD-001")
    source: str = Field(description="Source identifier or site name")
    source_type: SourceType = Field(default=SourceType.UNKNOWN)
    category: EvidenceCategory = Field(default=EvidenceCategory.GENERAL)
    title: str = Field(description="Title of source document or snippet")
    url_or_path: str = Field(description="URL or local file path")
    finding: str = Field(description="Direct evidence finding or excerpt")
    reliability: ReliabilityLevel = Field(default=ReliabilityLevel.MEDIUM)
    verification_status: str = Field(default="VERIFIED", description="VERIFIED, RETRIEVED, or UNVERIFIED")
    supports_claim: Optional[str] = Field(default=None, description="Specific claim supported by this evidence")
    relationship_to_conclusion: str = Field(default="Supports investigation objective", description="How evidence relates to final problem/conclusion")
    timestamp: Optional[str] = None
    # Search retrieval is intentionally separate from validation.  A URL in a
    # search result is not evidence until its content has been read and assessed.
    relevant: bool = False
    retrieved_at: Optional[str] = None

    @property
    def evidence_id(self) -> str:
        return self.id
