"""
LLM Data Models and Schemas for Ollama interaction.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    role: Role
    content: str


class OllamaChatRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    options: Optional[Dict[str, Any]] = None
    stream: bool = False


class OllamaChatResponse(BaseModel):
    model: str
    created_at: str
    message: ChatMessage
    done: bool
    total_duration: Optional[int] = None
    load_duration: Optional[int] = None
    prompt_eval_count: Optional[int] = None
    prompt_eval_duration: Optional[int] = None
    eval_count: Optional[int] = None
    eval_duration: Optional[int] = None


class ParsedToolCall(BaseModel):
    tool_name: str = Field(description="Name of the selected MCP tool")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments for tool call")
    thought: str = Field(default="", description="High level reasoning for selecting tool")


class LLMDecision(BaseModel):
    action: str = Field(description="'tool_call' or 'final_answer'")
    tool_call: Optional[ParsedToolCall] = None
    final_summary: Optional[str] = None
    user_status_message: Optional[str] = Field(default="", description="Safe user-facing progress message")
    unresolved_questions: List[str] = Field(default_factory=list)
