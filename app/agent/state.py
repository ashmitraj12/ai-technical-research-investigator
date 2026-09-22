"""
Agent State Management object.
"""

from typing import List, Dict, Any, Optional, Set
from app.evidence.manager import EvidenceManager
from app.logging.logger import EventLogger
from app.evaluation.tracker import MetricsTracker


class AgentState:
    """Encapsulates mutable state during an investigation run."""

    def __init__(
        self,
        objective: str,
        repo_path: Optional[str] = None,
        max_iterations: int = 6,
        max_mcp_calls: int = 5,
        temperature: float = 0.2
    ):
        self.objective = objective
        self.repo_path = repo_path
        self.max_iterations = max_iterations
        self.max_mcp_calls = max_mcp_calls
        self.temperature = temperature
        
        self.iteration = 0
        self.mcp_call_count = 0
        self.tools_used: List[str] = []
        self.history: List[Dict[str, Any]] = []
        self.unresolved_questions: List[str] = []
        self.current_status_message: str = "Initializing investigation..."
        self.is_completed: bool = False
        self.query_classification: Dict[str, Any] = {}
        self.successful_tool_signatures: Set[str] = set()
        self.failed_tool_signatures: Set[str] = set()
        self.failed_call_count: int = 0
        # Track URLs that have been dispatched to fetch_web_document (regardless of success)
        # to avoid the interceptor re-selecting already-attempted URLs in a loop.
        self.fetched_urls: Set[str] = set()
        
        self.evidence_mgr = EvidenceManager()
        self.logger = EventLogger()
        self.tracker = MetricsTracker()

    def add_history(self, role: str, content: str, tool_name: Optional[str] = None):
        self.history.append({
            "iteration": self.iteration,
            "role": role,
            "content": content,
            "tool_name": tool_name
        })

    def can_continue(self) -> bool:
        """Checks whether iteration and tool limits allow continuing."""
        return (
            not self.is_completed
            and self.iteration < self.max_iterations
            and self.mcp_call_count < self.max_mcp_calls
        )

