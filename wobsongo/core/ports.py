"""
wobsongo.core.ports
~~~~~~~~~~~~~~~~~~~
Port definitions (Protocols) for the Wobsongo hexagonal architecture.

All protocols are async-first and runtime_checkable.
Sync adapters satisfy these protocols by wrapping blocking calls
in asyncio.to_thread() internally.

Zero business logic here — only interface contracts.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from wobsongo.core.domain import DocumentChunk, VerifiedFact


@runtime_checkable
class RepositoryProtocol(Protocol):
    """Persistence port — abstract over any storage backend."""

    async def save_fact(self, fact: VerifiedFact) -> None: ...

    async def save_chunk(self, chunk: DocumentChunk) -> None: ...

    async def get_chunks_by_vector(
        self,
        vector: list[float],
        topic_filter: str,
    ) -> list[DocumentChunk]: ...

    async def get_facts_by_subject(self, subject: str) -> list[VerifiedFact]: ...


@runtime_checkable
class LLMClientProtocol(Protocol):
    """LLM port — abstract over any language model provider."""

    async def generate_json(
        self,
        prompt: str,
        json_schema: dict[str, object],
    ) -> dict[str, object]: ...


@runtime_checkable
class EmbeddingClientProtocol(Protocol):
    """Embedding port — abstract over any embedding model."""

    async def embed_text(self, text: str) -> list[float]: ...
