"""
wobsongo.adapters.embed_ollama
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
OllamaEmbedder — EmbeddingClientProtocol backed by Ollama.

Uses the Ollama embed endpoint (POST /api/embed) via the `ollama` Python
package. Designed for local Ollama — Ollama Cloud does not expose /api/embed.

Required dependency: ollama (install via `uv pip install -e ".[ollama]"`)

Local setup:
  ollama pull embeddinggemma:300m   # or nomic-embed-text

Environment variables:
  OLLAMA_EMBED_BASE_URL  Ollama host for embeddings (default: http://localhost:11434)
  OLLAMA_EMBED_MODEL     Embedding model name (default: nomic-embed-text)
  OLLAMA_EMBED_API_KEY   Bearer token if your local Ollama requires auth (usually unset)
"""

from __future__ import annotations

import asyncio
import os

import ollama

_BASE_URL = os.getenv("OLLAMA_EMBED_BASE_URL", "http://localhost:11434")
_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
_API_KEY = os.getenv("OLLAMA_EMBED_API_KEY") or ""
_TIMEOUT = float(os.getenv("OLLAMA_EMBED_TIMEOUT", os.getenv("OLLAMA_TIMEOUT", "60")))


class OllamaEmbedder:
    """Generates text embeddings using an Ollama-hosted model."""

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
        self._client = ollama.Client(host=base_url, headers=headers, timeout=timeout)
        self._model = model

    async def embed_text(self, text: str) -> list[float]:
        response = await asyncio.to_thread(
            self._client.embed,
            model=self._model,
            input=text,
        )
        if not response.embeddings:
            raise RuntimeError(
                f"Ollama embed returned no embeddings for model {self._model!r}"
            )
        return list(response.embeddings[0])

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single request."""
        response = await asyncio.to_thread(
            self._client.embed,
            model=self._model,
            input=texts,
        )
        if len(response.embeddings) != len(texts):
            raise RuntimeError(
                f"Ollama embed returned {len(response.embeddings)} embeddings, "
                f"expected {len(texts)}"
            )
        return [list(e) for e in response.embeddings]
