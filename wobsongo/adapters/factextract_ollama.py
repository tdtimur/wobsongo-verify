"""
wobsongo.adapters.factextract_ollama
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
OllamaFactExtractor — FactExtractorProtocol backed by Ollama.

Uses the `ollama` Python package with AsyncClient and native structured
output (format field) so the model is schema-constrained.

Required dependency: ollama (install via `uv pip install -e ".[ollama]"`)

Environment variables:
  OLLAMA_BASE_URL   Ollama server host (default: http://localhost:11434)
                    Ollama Cloud: https://ollama.com
  OLLAMA_MODEL      Model name (default: gemma3:4b)
  OLLAMA_API_KEY    Bearer token — required for Ollama Cloud, omit for local
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from ollama import AsyncClient

from wobsongo.core.domain import ExtractedFact

_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")
_API_KEY = os.getenv("OLLAMA_API_KEY") or ""
_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))

_PROMPT = """\
Extract all factual claims from the following text as subject-predicate-object triples.

Rules:
- Each fact must be atomic and independently verifiable.
- subject: the entity the fact is about (noun phrase, concise).
- predicate: the relationship or action (verb phrase, concise).
- object: the value, quantity, or target entity.
- truth_tier:
    1 = axiomatic / universally true
    2 = time-bound (fact was true at a specific time)
    3 = conditional (true only under specific conditions)
    4 = expert opinion / attributed claim

Respond with valid JSON only. No prose, no markdown, no explanation.

Output format:
{{"facts": [{{"subject": "...", "predicate": "...", "object": "...", "truth_tier": 1}}]}}

Text:
{text}
"""

# Extracts the first {...} JSON object from a string, handles markdown code fences.
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_FORMAT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object": {"type": "string"},
                    "truth_tier": {"type": "integer", "minimum": 1, "maximum": 4},
                },
                "required": ["subject", "predicate", "object", "truth_tier"],
            },
        }
    },
    "required": ["facts"],
}


class OllamaFactExtractor:
    """Extracts SPO triples from text using an Ollama-hosted model."""

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

    async def extract_facts(self, text: str) -> list[ExtractedFact]:
        response = await self._client.chat(
            model=self._model,
            messages=[{"role": "user", "content": _PROMPT.format(text=text)}],
            format=_FORMAT,
            stream=False,
        )
        content = response.message.content or ""
        match = _JSON_RE.search(content)
        try:
            data: dict[str, Any] = json.loads(match.group()) if match else {}
        except json.JSONDecodeError:
            data = {}

        facts: list[ExtractedFact] = []
        for raw in data.get("facts", []):
            if not isinstance(raw, dict):
                continue
            try:
                facts.append(
                    ExtractedFact(
                        subject=str(raw["subject"]),
                        predicate=str(raw["predicate"]),
                        object=str(raw["object"]),
                        truth_tier=int(raw["truth_tier"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return facts
