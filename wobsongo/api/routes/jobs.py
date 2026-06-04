"""GET/POST /api/v3/jobs, GET /api/v3/jobs/{job_id}, POST /api/v3/jobs/{job_id}/retry"""

from __future__ import annotations

from uuid import UUID

from litestar import get, post
from litestar.exceptions import HTTPException

from wobsongo.api.schemas.jobs import (
    CreateJobRequest,
    JobCreatedResponse,
    JobItem,
    PaginatedJobs,
    RetryJobResponse,
)
from wobsongo.core.domain import IngestionJob
from wobsongo.core.exceptions import ConflictError, NotFoundError
from wobsongo.core.services.job_service import JobService


def _job_to_item(job: IngestionJob) -> JobItem:
    return JobItem(
        id=str(job.id),
        title=job.title,
        filename=job.filename,
        status=job.status,
        created_at=job.created_at,
        chunks_stored=job.chunks_stored,
        facts_extracted=job.facts_extracted,
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@get("/api/v3/jobs")
async def list_jobs_handler(
    job_service: JobService,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedJobs:
    if page < 1 or not (1 <= page_size <= 100):
        raise HTTPException(status_code=422, detail="page must be ≥ 1; page_size must be 1-100")
    jobs, total = await job_service.list_jobs(status=status, page=page, page_size=page_size)
    return PaginatedJobs(
        items=[_job_to_item(j) for j in jobs],
        total=total,
        page=page,
        page_size=page_size,
    )


@post("/api/v3/jobs", status_code=201)
async def create_job_handler(
    data: CreateJobRequest,
    job_service: JobService,
) -> JobCreatedResponse:
    job, upload_url = await job_service.create_job(title=data.title, filename=data.filename)
    return JobCreatedResponse(
        job_id=str(job.id),
        storage_key=job.storage_key,
        upload_url=upload_url,
        status=job.status,
    )


@get("/api/v3/jobs/{job_id:uuid}")
async def get_job_handler(
    job_id: UUID,
    job_service: JobService,
) -> JobItem:
    try:
        job = await job_service.get_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _job_to_item(job)


@post("/api/v3/jobs/{job_id:uuid}/retry")
async def retry_job_handler(
    job_id: UUID,
    job_service: JobService,
) -> RetryJobResponse:
    try:
        job = await job_service.retry_job(job_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RetryJobResponse(job_id=str(job.id), status=job.status)
