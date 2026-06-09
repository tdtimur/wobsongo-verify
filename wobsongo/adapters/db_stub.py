"""
wobsongo.adapters.db_stub
~~~~~~~~~~~~~~~~~~~~~~~~~~
In-memory stub implementations of JobStoreProtocol and DocumentStoreProtocol.

Used in service-level tests — no disk I/O, no SQLite.
"""

from __future__ import annotations

from uuid import UUID

from wobsongo.core.domain import IngestionJob, SourceDocument, User


class StubJobStore:
    """In-memory JobStoreProtocol for tests."""

    def __init__(self) -> None:
        self._jobs: dict[UUID, IngestionJob] = {}

    async def save_job(self, job: IngestionJob) -> None:
        self._jobs[job.id] = job

    async def get_job(self, job_id: UUID) -> IngestionJob | None:
        return self._jobs.get(job_id)

    async def list_jobs(
        self, status: str | None, page: int, page_size: int
    ) -> tuple[list[IngestionJob], int]:
        items = [
            j for j in self._jobs.values()
            if status is None or j.status == status
        ]
        items.sort(key=lambda j: j.created_at, reverse=True)
        start = (page - 1) * page_size
        return items[start : start + page_size], len(items)

    async def claim_next_job(self) -> IngestionJob | None:
        pending = sorted(
            (j for j in self._jobs.values() if j.status == "pending"),
            key=lambda j: j.created_at,
        )
        if not pending:
            return None
        job = pending[0]
        job.status = "processing"
        return job

    async def update_job(self, job_id: UUID, **fields: object) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        for k, v in fields.items():
            setattr(job, k, v)


class StubDocumentStore:
    """In-memory DocumentStoreProtocol for tests."""

    def __init__(self) -> None:
        self._docs: dict[UUID, SourceDocument] = {}

    async def save_document(self, doc: SourceDocument) -> None:
        self._docs[doc.id] = doc

    async def get_document(self, doc_id: UUID) -> SourceDocument | None:
        return self._docs.get(doc_id)

    async def get_document_by_hash(self, content_hash: str) -> SourceDocument | None:
        return next((d for d in self._docs.values() if d.content_hash == content_hash), None)

    async def list_documents(
        self, page: int, page_size: int
    ) -> tuple[list[SourceDocument], int]:
        items = sorted(self._docs.values(), key=lambda d: d.ingested_at, reverse=True)
        start = (page - 1) * page_size
        return items[start : start + page_size], len(items)

    async def delete_document(self, doc_id: UUID) -> None:
        self._docs.pop(doc_id, None)

    async def count_chunks_for_doc(self, doc_id: UUID) -> int:
        return 0

    async def count_facts_for_doc(self, doc_id: UUID) -> int:
        return 0


class StubUserStore:
    """In-memory UserStoreProtocol for tests."""

    def __init__(self) -> None:
        self._users: dict[UUID, User] = {}

    async def save_user(self, user: User) -> None:
        self._users[user.id] = user

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def get_user_by_email(self, email: str) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    async def list_users(self, page: int, page_size: int) -> tuple[list[User], int]:
        items = sorted(self._users.values(), key=lambda u: u.created_at, reverse=True)
        start = (page - 1) * page_size
        return items[start : start + page_size], len(items)

    async def update_user(self, user_id: UUID, **fields: object) -> None:
        user = self._users.get(user_id)
        if user is None:
            return
        for k, v in fields.items():
            setattr(user, k, v)

    async def delete_user(self, user_id: UUID) -> None:
        self._users.pop(user_id, None)
