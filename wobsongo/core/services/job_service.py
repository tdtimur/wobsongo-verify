"""wobsongo.core.services.job_service"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from wobsongo.core.domain import IngestionJob
from wobsongo.core.exceptions import ConflictError, NotFoundError
from wobsongo.core.ports import JobStoreProtocol, ObjectStorageProtocol


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class JobService:
    def __init__(
        self,
        job_store: JobStoreProtocol,
        storage: ObjectStorageProtocol,
    ) -> None:
        self._store = job_store
        self._storage = storage

    async def create_job(self, title: str, filename: str) -> tuple[IngestionJob, str]:
        key = f"documents/{uuid4()}/{filename}"
        job = IngestionJob(
            id=uuid4(),
            status="pending",
            title=title,
            filename=filename,
            storage_key=key,
            created_at=_now_iso(),
        )
        await self._store.save_job(job)
        upload_url = self._storage.generate_upload_url(key)
        return job, upload_url

    async def list_jobs(
        self, status: str | None, page: int, page_size: int
    ) -> tuple[list[IngestionJob], int]:
        return await self._store.list_jobs(status=status, page=page, page_size=page_size)

    async def get_job(self, job_id: UUID) -> IngestionJob:
        job = await self._store.get_job(job_id)
        if job is None:
            raise NotFoundError("Job not found")
        return job

    async def retry_job(self, job_id: UUID) -> IngestionJob:
        job = await self._store.get_job(job_id)
        if job is None:
            raise NotFoundError("Job not found")
        if job.status != "failed":
            raise ConflictError("Job is not in failed state")
        await self._store.update_job(
            job_id,
            status="pending",
            error_message=None,
            started_at=None,
            finished_at=None,
        )
        updated = await self._store.get_job(job_id)
        if updated is None:
            raise NotFoundError("Job not found after retry update")
        return updated
