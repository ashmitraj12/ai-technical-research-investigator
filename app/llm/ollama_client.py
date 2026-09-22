"""
Ollama API Client for Local LLM Inference with Latency Measurement and Error Handling.
"""

import json
import time
import logging
import requests
from typing import List, Dict, Any, Optional
from app.llm.models import ChatMessage, OllamaChatRequest, OllamaChatResponse, Role

logger = logging.getLogger(__name__)


class OllamaClient:
    """Client for local Ollama service."""

    def __init__(self, host: str = "http://localhost:11434", default_model: str = "llama3.2:1b", timeout: float = 60.0):
        self.host = host.rstrip('/')
        self.default_model = default_model
        self.timeout = timeout

    def check_health(self) -> Dict[str, Any]:
        """Check if Ollama server is responsive and return available models."""
        url = f"{self.host}/api/tags"
        try:
            start_time = time.time()
            resp = requests.get(url, timeout=5.0)
            latency = time.time() - start_time
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name") for m in data.get("models", [])]
                return {
                    "status": "healthy",
                    "latency_sec": round(latency, 3),
                    "models": models,
                    "default_model_available": self.default_model in models or any(self.default_model in m for m in models)
                }
            else:
                return {"status": "unhealthy", "error": f"HTTP status {resp.status_code}"}
        except Exception as e:
            return {"status": "unavailable", "error": str(e)}

    def chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.2,
        format_json: bool = False
    ) -> Dict[str, Any]:
        """
        Send a chat completion request to Ollama.
        Returns a dict containing response text, latency, token counts, and success status.
        """
        target_model = model or self.default_model
        url = f"{self.host}/api/chat"

        payload = {
            "model": target_model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "options": {"temperature": temperature},
            "stream": False
        }
        if format_json:
            payload["format"] = "json"

        start_time = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            latency = time.time() - start_time

            if resp.status_code == 200:
                data = resp.json()
                message_content = data.get("message", {}).get("content", "")
                
                # Token counts (Ollama outputs nanoseconds and token counts)
                prompt_tokens = data.get("prompt_eval_count", 0)
                eval_tokens = data.get("eval_count", 0)

                return {
                    "success": True,
                    "content": message_content,
                    "latency_sec": round(latency, 3),
                    "prompt_tokens": prompt_tokens,
                    "eval_tokens": eval_tokens,
                    "total_tokens": prompt_tokens + eval_tokens,
                    "model": target_model,
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "content": "",
                    "latency_sec": round(latency, 3),
                    "error": f"Ollama HTTP {resp.status_code}: {resp.text}"
                }
        except requests.exceptions.Timeout:
            latency = time.time() - start_time
            return {
                "success": False,
                "content": "",
                "latency_sec": round(latency, 3),
                "error": f"Ollama request timed out after {self.timeout}s"
            }
        except Exception as e:
            latency = time.time() - start_time
            return {
                "success": False,
                "content": "",
                "latency_sec": round(latency, 3),
                "error": f"Ollama connection error: {str(e)}"
            }

    @staticmethod
    def extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Utility to extract JSON block or object from LLM response text."""
        if not text:
            return None
        text_clean = text.strip()
        
        # Try direct json load
        try:
            return json.loads(text_clean)
        except Exception:
            pass

        # Try markdown block extraction ```json ... ```
        if "```" in text_clean:
            blocks = text_clean.split("```")
            for block in blocks:
                b = block.strip()
                if b.startswith("json"):
                    b = b[4:].strip()
                try:
                    return json.loads(b)
                except Exception:
                    continue

        # Try searching for { ... }
        start_idx = text_clean.find("{")
        end_idx = text_clean.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                return json.loads(text_clean[start_idx:end_idx+1])
            except Exception:
                pass

        return None
