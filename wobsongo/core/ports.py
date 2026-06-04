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

from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from wobsongo.core.domain import (
    DocumentChunk,
    ExtractedFact,
    IngestionJob,
    SourceDocument,
    User,
    VerifiedFact,
)


@runtime_checkable
class RepositoryProtocol(Protocol):
    """Persistence port — abstract over any storage backend."""

    async def save_document(self, doc: SourceDocument) -> None: ...

    async def get_document_by_hash(self, content_hash: str) -> SourceDocument | None: ...

    async def save_chunk(self, chunk: DocumentChunk) -> None: ...

    async def get_chunks_by_vector(
        self,
        vector: list[float],
        topic_filter: str,
    ) -> list[DocumentChunk]: ...

    async def save_fact(self, fact: VerifiedFact) -> None: ...

    async def get_facts_by_subject(self, subject: str) -> list[VerifiedFact]: ...

    async def get_facts_by_chunk_ids(self, chunk_ids: list[UUID]) -> list[VerifiedFact]: ...

    async def get_facts_by_topic_path(self, topic_path: str) -> list[VerifiedFact]: ...

    async def get_facts_by_truth_tier(self, truth_tier: int) -> list[VerifiedFact]: ...


@runtime_checkable
class FactExtractorProtocol(Protocol):
    """Fact extraction port — abstract over any SPO extraction backend."""

    async def extract_facts(self, text: str) -> list[ExtractedFact]: ...


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


@runtime_checkable
class JobStoreProtocol(Protocol):
    """Persistence port for ingestion job lifecycle tracking."""

    async def save_job(self, job: IngestionJob) -> None: ...

    async def get_job(self, job_id: UUID) -> IngestionJob | None: ...

    async def list_jobs(
        self, status: str | None, page: int, page_size: int
    ) -> tuple[list[IngestionJob], int]: ...

    async def claim_next_job(self) -> IngestionJob | None: ...

    async def update_job(self, job_id: UUID, **fields: object) -> None: ...


@runtime_checkable
class UserStoreProtocol(Protocol):
    """Persistence port for user accounts."""

    async def save_user(self, user: User) -> None: ...

    async def get_user_by_id(self, user_id: UUID) -> User | None: ...

    async def get_user_by_email(self, email: str) -> User | None: ...

    async def list_users(self, page: int, page_size: int) -> tuple[list[User], int]: ...

    async def update_user(self, user_id: UUID, **fields: object) -> None: ...

    async def delete_user(self, user_id: UUID) -> None: ...


@runtime_checkable
class ObjectStorageProtocol(Protocol):
    """Object storage port — abstract over S3, MinIO, R2, etc."""

    def generate_upload_url(self, key: str, expires_in: int = 3600) -> str: ...

    async def download_file(self, key: str, dest_path: Path) -> None: ...


@runtime_checkable
class DocumentStoreProtocol(Protocol):
    """Persistence port for the document knowledge base."""

    async def save_document(self, doc: SourceDocument) -> None: ...

    async def get_document(self, doc_id: UUID) -> SourceDocument | None: ...

    async def get_document_by_hash(self, content_hash: str) -> SourceDocument | None: ...

    async def list_documents(
        self, page: int, page_size: int
    ) -> tuple[list[SourceDocument], int]: ...

    async def delete_document(self, doc_id: UUID) -> None: ...

    async def count_chunks_for_doc(self, doc_id: UUID) -> int: ...

    async def count_facts_for_doc(self, doc_id: UUID) -> int: ...
