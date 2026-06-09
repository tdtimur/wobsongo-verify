"""
wobsongo.api.app
~~~~~~~~~~~~~~~~
Litestar HTTP API v3.

Base prefix:  /api/v3
Auth:         Bearer JWT (HS256) — all routes except /api/v3/auth/token
OpenAPI docs: /schema  (JSON)  |  /schema/swagger  (UI)

Adapter selection via environment variables:
  WOBSONGO_LLM          — "ollama" | "openai" | "stub" (default)
  WOBSONGO_EMBEDDER     — "ollama" | "bge" | "stub" (default)
  WOBSONGO_DB_PATH      — SQLite file path (default: wobsongo.db)
  S3_BUCKET             — bucket name; if set, uses S3Storage; else StubStorage
  S3_ENDPOINT_URL       — custom endpoint (MinIO / R2); omit for AWS
  AWS_DEFAULT_REGION    — default: us-east-1
  WOBSONGO_JWT_SECRET   — HS256 signing key (required in production)
  WOBSONGO_ADMIN_PASSWORD — password checked at /api/v3/auth/token
  WOBSONGO_JWT_TTL_HOURS  — token lifetime in hours (default: 24)
"""

from __future__ import annotations

import os

from litestar import Litestar
from litestar.di import Provide
from litestar.openapi import OpenAPIConfig
from litestar.openapi.spec import Components, SecurityScheme

from wobsongo.adapters.db_sqlite import SQLiteRepository
from wobsongo.adapters.llm_stub import StubLLMClient
from wobsongo.api.middleware.auth import JWTAuthMiddleware
from wobsongo.api.routes.auth import login_handler
from wobsongo.api.routes.documents import (
    delete_document_handler,
    get_document_handler,
    list_documents_handler,
)
from wobsongo.api.routes.jobs import (
    create_job_handler,
    get_job_handler,
    list_jobs_handler,
    retry_job_handler,
)
from wobsongo.api.routes.verify import verify_handler
from wobsongo.core.pipeline import PipelineController
from wobsongo.core.services.document_service import DocumentService
from wobsongo.core.services.job_service import JobService
from wobsongo.core.services.verification_service import VerificationService

# ------------------------------------------------------------------
# Stub embedder — used when WOBSONGO_EMBEDDER is unset or "stub"
# ------------------------------------------------------------------

class _StubEmbedder:
    async def embed_text(self, text: str) -> list[float]:
        return [0.0] * 768


# ------------------------------------------------------------------
# Adapter builders — lazy-import heavy dependencies
# ------------------------------------------------------------------

def _build_llm() -> object:
    choice = os.environ.get("WOBSONGO_LLM", "stub").lower()
    if choice == "openai":
        from wobsongo.adapters.llm_openai import OpenAILLMClient
        return OpenAILLMClient()
    if choice == "ollama":
        from wobsongo.adapters.llm_ollama import OllamaLLMClient
        return OllamaLLMClient()
    return StubLLMClient()


def _build_embedder() -> object:
    choice = os.environ.get("WOBSONGO_EMBEDDER", "stub").lower()
    if choice == "bge":
        from wobsongo.adapters.embed_bge import BGEEmbedder
        return BGEEmbedder()
    if choice == "ollama":
        from wobsongo.adapters.embed_ollama import OllamaEmbedder
        return OllamaEmbedder()
    return _StubEmbedder()


def _build_storage() -> object:
    bucket = os.environ.get("S3_BUCKET")
    if bucket:
        from wobsongo.adapters.storage_s3 import S3Storage
        return S3Storage(
            bucket=bucket,
            endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
            region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        )
    from wobsongo.adapters.storage_stub import StubStorage
    return StubStorage()


# ------------------------------------------------------------------
# App-level singletons — built once at import time
# ------------------------------------------------------------------

_db_path = os.environ.get("WOBSONGO_DB_PATH", "wobsongo.db")
_embed_dim = int(os.environ.get("WOBSONGO_EMBED_DIM", "768"))
_repo = SQLiteRepository(_db_path, embedding_dim=_embed_dim)
_storage = _build_storage()
_llm = _build_llm()
_embedder = _build_embedder()
_pipeline = PipelineController(repo=_repo, llm=_llm, embedder=_embedder)  # type: ignore[arg-type]

_document_service = DocumentService(_repo)  # type: ignore[arg-type]
_job_service = JobService(_repo, _storage)  # type: ignore[arg-type]
_verification_service = VerificationService(_pipeline)


# ------------------------------------------------------------------
# Dependency providers (thin wrappers that return the singletons)
# ------------------------------------------------------------------

def _provide_document_service() -> DocumentService:
    return _document_service


def _provide_job_service() -> JobService:
    return _job_service


def _provide_verification_service() -> VerificationService:
    return _verification_service


# ------------------------------------------------------------------
# Litestar application
# ------------------------------------------------------------------

app = Litestar(
    route_handlers=[
        login_handler,
        list_documents_handler,
        get_document_handler,
        delete_document_handler,
        list_jobs_handler,
        create_job_handler,
        get_job_handler,
        retry_job_handler,
        verify_handler,
    ],
    middleware=[JWTAuthMiddleware],
    dependencies={
        "document_service": Provide(_provide_document_service, sync_to_thread=False, use_cache=True),
        "job_service": Provide(_provide_job_service, sync_to_thread=False, use_cache=True),
        "verification_service": Provide(
            _provide_verification_service, sync_to_thread=False, use_cache=True
        ),
    },
    openapi_config=OpenAPIConfig(
        title="Wobsongo Verify API",
        version="3.0.0",
        components=Components(
            security_schemes={
                "bearerAuth": SecurityScheme(
                    type="http",
                    scheme="bearer",
                    bearer_format="JWT",
                )
            }
        ),
    ),
)
