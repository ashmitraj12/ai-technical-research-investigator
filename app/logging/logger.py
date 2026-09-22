"""
Event Logger and Observability Stream Sink for real-time application logging.
"""

import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
from pydantic import BaseModel, Field


class LogLevel:
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LogCategory:
    AGENT = "AGENT"
    MCP = "MCP"
    LLM = "LLM"
    REFLECTION = "REFLECTION"
    SYSTEM = "SYSTEM"


class LogEvent(BaseModel):
    timestamp: str = Field(description="Formatted time e.g. 14:02:01")
    level: str = Field(description="DEBUG, INFO, WARNING, ERROR")
    category: str = Field(description="AGENT, MCP, LLM, REFLECTION, SYSTEM")
    message: str = Field(description="Log message text")
    details: Optional[Dict[str, Any]] = None


class EventLogger:
    """Thread-safe execution logger sink."""

    def __init__(self):
        self.logs: List[LogEvent] = []
        self.listeners: List[Callable[[LogEvent], None]] = []

    def log(
        self,
        level: str,
        category: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> LogEvent:
        now_str = datetime.now().strftime("%H:%M:%S")
        event = LogEvent(
            timestamp=now_str,
            level=level,
            category=category,
            message=message,
            details=details
        )
        self.logs.append(event)
        for listener in self.listeners:
            try:
                listener(event)
            except Exception:
                pass
        return event

    def info(self, category: str, message: str, details: Optional[Dict[str, Any]] = None):
        return self.log(LogLevel.INFO, category, message, details)

    def debug(self, category: str, message: str, details: Optional[Dict[str, Any]] = None):
        return self.log(LogLevel.DEBUG, category, message, details)

    def warning(self, category: str, message: str, details: Optional[Dict[str, Any]] = None):
        return self.log(LogLevel.WARNING, category, message, details)

    def error(self, category: str, message: str, details: Optional[Dict[str, Any]] = None):
        return self.log(LogLevel.ERROR, category, message, details)

    def subscribe(self, callback: Callable[[LogEvent], None]):
        self.listeners.append(callback)

    def clear(self):
        self.logs.clear()

    def get_formatted_logs(self) -> List[str]:
        return [f"[{e.timestamp}] [{e.level}] [{e.category}] {e.message}" for e in self.logs]
