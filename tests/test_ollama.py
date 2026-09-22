"""
Unit tests for Ollama API Client.
"""

import pytest
from app.llm.ollama_client import OllamaClient
from app.llm.models import ChatMessage, Role


def test_extract_json_direct():
    raw = '{"action": "tool_call", "tool_name": "search_web"}'
    parsed = OllamaClient.extract_json(raw)
    assert parsed is not None
    assert parsed["action"] == "tool_call"
    assert parsed["tool_name"] == "search_web"


def test_extract_json_markdown():
    raw = """Here is the response:
```json
{
    "action": "final_answer",
    "thought": "I have enough evidence"
}
```
Done."""
    parsed = OllamaClient.extract_json(raw)
    assert parsed is not None
    assert parsed["action"] == "final_answer"
    assert parsed["thought"] == "I have enough evidence"


def test_ollama_health_check():
    client = OllamaClient()
    res = client.check_health()
    assert res["status"] in ["healthy", "unavailable"]
    assert "models" in res
    assert isinstance(res["models"], list)
