"""
wobsongo.adapters.embed_bge
~~~~~~~~~~~~~~~~~~~~~~~~~~~
BGEEmbedder — satisfies EmbeddingClientProtocol.

Uses BAAI/bge-m3 via sentence-transformers (open source, Apache 2.0).
sentence-transformers imported lazily — raises RuntimeError if absent.
Model inference is CPU/GPU blocking — wrapped in asyncio.to_thread().

Install: uv sync --extra embed
"""

from __future__ import annotations

import asyncio


class BGEEmbedder:
    """BGE-M3 multilingual embedder. Satisfies EmbeddingClientProtocol."""

    MODEL_NAME = "BAAI/bge-m3"

    def __init__(self) -> None:
        self._model = None  # lazy loaded on first call

    def _load_model(self) -> object:
        if self._model is None:
            try:
                from sentence_transformers import (  # type: ignore[import-not-found]
                    SentenceTransformer,
                )
            except ImportError as e:
                raise RuntimeError(
                    "sentence-transformers not installed. "
                    "Run: uv sync --extra embed"
                ) from e
            self._model = SentenceTransformer(self.MODEL_NAME)
        return self._model

    def _embed_sync(self, text: str) -> list[float]:
        model = self._load_model()
        result: list[float] = model.encode(text, normalize_embeddings=True).tolist()  # type: ignore[attr-defined]
        return result

    async def embed_text(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_sync, text)
