from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CreateJobRequest:
    title: str
    filename: str


@dataclass
class JobCreatedResponse:
    job_id: str
    storage_key: str
    upload_url: str
    status: str = "pending"


@dataclass
class JobItem:
    id: str
    title: str
    filename: str
    status: str
    created_at: str
    chunks_stored: int | None = None
    facts_extracted: int | None = None
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class PaginatedJobs:
    items: list[JobItem] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


@dataclass
class RetryJobResponse:
    job_id: str
    status: str = "pending"
