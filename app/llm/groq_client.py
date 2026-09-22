"""
Groq API Client — drop-in replacement for OllamaClient.
Uses Groq's OpenAI-compatible REST API for fast cloud LLM inference.
Compatible interface: chat(), check_health(), extract_json()
"""

import json
import time
import logging
import requests
from typing import List, Dict, Any, Optional
from app.llm.models import ChatMessage

logger = logging.getLogger(__name__)

# Top models available on this endpoint ranked by capability
GROQ_MODELS = [
    "openai/gpt-oss-120b",          # 120B Flagship Model — Extremely capable
    "qwen/qwen3.8-27b",             # 27B Fast & Strong reasoning
    "openai/gpt-oss-20b",           # 20B Lightweight
    "qwen/qwen3.6-27b",             # 27B alternative
    "llama-3.3-70b-versatile",      # If available on standard Groq
    "llama-3.1-8b-instant",
]

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqClient:
    """
    Client for Groq Cloud API (OpenAI-compatible endpoint).
    Provides the same interface as OllamaClient so it can be used
    as a drop-in replacement throughout the agent system.
    """

    def __init__(self, api_key: str, default_model: str = "openai/gpt-oss-120b", timeout: float = 60.0):
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.available_models = []

    def check_health(self) -> Dict[str, Any]:
        """Check Groq API connectivity by listing available models."""
        url = f"{GROQ_BASE_URL}/models"
        try:
            start = time.time()
            resp = requests.get(url, headers=self._headers, timeout=8.0)
            latency = round(time.time() - start, 3)
            if resp.status_code == 200:
                data = resp.json()
                raw_models = [m["id"] for m in data.get("data", [])]
                # Filter out audio/guard models to only list chat models
                chat_models = [m for m in raw_models if not any(x in m.lower() for x in ["whisper", "guard", "audio", "orpheus"])]
                # Sort preferred models first
                preferred = [m for m in GROQ_MODELS if m in chat_models]
                other = [m for m in chat_models if m not in preferred]
                self.available_models = preferred + other
                if not self.available_models:
                    self.available_models = raw_models

                # Ensure default_model is valid
                if self.default_model not in self.available_models and self.available_models:
                    self.default_model = self.available_models[0]

                return {
                    "status": "healthy",
                    "latency_sec": latency,
                    "models": self.available_models,
                    "default_model_available": True,
                    "provider": "groq",
                }
            elif resp.status_code == 401:
                return {"status": "unhealthy", "error": "Invalid Groq API key. Check at https://console.groq.com"}
            else:
                return {"status": "unhealthy", "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except requests.exceptions.ConnectionError:
            return {"status": "unavailable", "error": "Cannot reach Groq API. Check internet connection."}
        except Exception as e:
            return {"status": "unavailable", "error": str(e)}

    def chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.2,
        format_json: bool = False,
    ) -> Dict[str, Any]:
        """
        Send a chat completion request to Groq API.
        Automatically resolves model name and falls back if an invalid model is requested.
        """
        # Resolve target model: if None or an Ollama/unsupported model name is passed, use default
        target_model = model or self.default_model
        if any(target_model.startswith(x) for x in ["llama3.2:", "qwen3.5:", "mistral:", "llama3.1:8b"]):
            target_model = self.default_model
        elif self.available_models and target_model not in self.available_models:
            target_model = self.default_model

        url = f"{GROQ_BASE_URL}/chat/completions"

        def _send(m_name: str, use_json_mode: bool) -> requests.Response:
            payload: Dict[str, Any] = {
                "model": m_name,
                "messages": [{"role": m.role.value, "content": m.content} for m in messages],
                "temperature": temperature,
                "stream": False,
                "max_tokens": 4096,
            }
            if use_json_mode:
                payload["response_format"] = {"type": "json_object"}
            return requests.post(url, headers=self._headers, json=payload, timeout=self.timeout)

        start = time.time()
        try:
            resp = _send(target_model, format_json)
            
            # If 404 (model not found) and we didn't already use default, retry with default_model
            if resp.status_code == 404 and target_model != self.default_model:
                target_model = self.default_model
                resp = _send(target_model, format_json)

            # If 400 (e.g. model doesn't support json_object mode), retry without json_object
            if resp.status_code == 400 and format_json:
                resp = _send(target_model, False)

            # If 429 (rate limit), back off 2s and retry, or fallback to lighter model
            if resp.status_code == 429:
                time.sleep(2.0)
                resp = _send(target_model, format_json)
                if resp.status_code == 429:
                    # Fallback to 27B / 20B model which has much higher rate limits
                    fallback_model = "qwen/qwen3.8-27b" if target_model != "qwen/qwen3.8-27b" else "openai/gpt-oss-20b"
                    target_model = fallback_model
                    resp = _send(target_model, format_json)

            latency = round(time.time() - start, 3)

            if resp.status_code == 200:
                data = resp.json()
                choice = data.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "")
                usage = data.get("usage", {})
                return {
                    "success": True,
                    "content": content,
                    "latency_sec": latency,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "eval_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "model": target_model,
                    "error": None,
                    "provider": "groq",
                }
            elif resp.status_code == 401:
                return {
                    "success": False, "content": "", "latency_sec": latency,
                    "error": "Groq API authentication failed. Check your API key.",
                    "prompt_tokens": 0, "eval_tokens": 0
                }
            elif resp.status_code == 429:
                return {
                    "success": False, "content": "", "latency_sec": latency,
                    "error": "Groq rate limit exceeded. Wait a moment and retry.",
                    "prompt_tokens": 0, "eval_tokens": 0
                }
            else:
                return {
                    "success": False, "content": "", "latency_sec": latency,
                    "error": f"Groq HTTP {resp.status_code}: {resp.text[:300]}",
                    "prompt_tokens": 0, "eval_tokens": 0
                }
        except requests.exceptions.Timeout:
            return {
                "success": False, "content": "",
                "latency_sec": round(time.time() - start, 3),
                "error": f"Groq request timed out after {self.timeout}s",
                "prompt_tokens": 0, "eval_tokens": 0
            }
        except Exception as e:
            return {
                "success": False, "content": "",
                "latency_sec": round(time.time() - start, 3),
                "error": f"Groq connection error: {str(e)}",
                "prompt_tokens": 0, "eval_tokens": 0
            }

    @staticmethod
    def extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Identical JSON extractor to OllamaClient — shared static utility."""
        if not text:
            return None
        text_clean = text.strip()

        try:
            return json.loads(text_clean)
        except Exception:
            pass

        if "```" in text_clean:
            for block in text_clean.split("```"):
                b = block.strip()
                if b.startswith("json"):
                    b = b[4:].strip()
                try:
                    return json.loads(b)
                except Exception:
                    continue

        start_idx = text_clean.find("{")
        end_idx = text_clean.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                return json.loads(text_clean[start_idx:end_idx + 1])
            except Exception:
                pass

        return None
