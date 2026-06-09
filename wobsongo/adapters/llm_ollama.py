"""
wobsongo.adapters.llm_ollama
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
OllamaLLMClient — LLMClientProtocol backed by Ollama Cloud.

Uses the same JSON-extraction approach as OllamaFactExtractor:
passes the schema as a format hint and parses the first JSON object
from the response, since not all models honour the format constraint.

Environment variables:
  OLLAMA_BASE_URL  Ollama server host (default: http://localhost:11434)
  OLLAMA_MODEL     Model name (default: gemma3:4b)
  OLLAMA_API_KEY   Bearer token for Ollama Cloud
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from ollama import AsyncClient

_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")
_API_KEY = os.getenv("OLLAMA_API_KEY") or ""
_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class OllamaLLMClient:
    """LLMClientProtocol implementation using Ollama."""

    def __init__(
        self,
        base_url: str = _BASE_URL,
        model: str = _MODEL,
        api_key: str = _API_KEY,
        timeout: float = _TIMEOUT,
    ) -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = AsyncClient(host=base_url, headers=headers, timeout=timeout)
        self._model = model

    async def generate_json(
        self,
        prompt: str,
        json_schema: dict[str, object],
    ) -> dict[str, object]:
        response = await self._client.chat(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            format=json_schema,
            stream=False,
        )
        content = response.message.content or ""
        match = _JSON_RE.search(content)
        try:
            data: dict[str, Any] = json.loads(match.group()) if match else {}
        except json.JSONDecodeError:
            data = {}
        return data
