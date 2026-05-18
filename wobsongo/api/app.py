"""
wobsongo.api.app
~~~~~~~~~~~~~~~~
Litestar HTTP API — primary adapter.

Routes:
  POST /api/v1/verify   — verify a text claim
  POST /api/v1/ingest   — ingest a markdown document

PipelineController injected via Litestar dependency injection.

Adapter selection via environment variables:
  WOBSONGO_LLM      — "openai" (default: stub)
  WOBSONGO_EMBEDDER — "bge"    (default: stub)
  WOBSONGO_DB_PATH  — path to SQLite file (default: wobsongo.db)
  OPENAI_API_KEY    — required when WOBSONGO_LLM=openai
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from uuid import uuid4

from litestar import Litestar, post
from litestar.datastructures import UploadFile
from litestar.di import Provide
from litestar.enums import RequestEncodingType
from litestar.params import Body

from wobsongo.adapters.db_sqlite import SQLiteRepository
from wobsongo.adapters.llm_stub import StubLLMClient
from wobsongo.core.domain import Post, TaxonomyTag, VerificationResult
from wobsongo.core.pipeline import PipelineController

# ------------------------------------------------------------------
# Request / Response dataclasses
# ------------------------------------------------------------------


@dataclass
class VerifyRequest:
    text: str
    source: str = "manual"
    language: str = "en"
    topic_path: str | None = None


@dataclass
class IngestResponse:
    facts_extracted: int
    chunks_stored: int
    source_doc_id: str


# ------------------------------------------------------------------
# Stub embedder (used when WOBSONGO_EMBEDDER != "bge")
# ------------------------------------------------------------------


class _StubEmbedder:
    async def embed_text(self, text: str) -> list[float]:
        return [0.0] * 768  # bge-m3 dim placeholder


# ------------------------------------------------------------------
# Dependency factory — adapter selection via env vars
# ------------------------------------------------------------------


def make_controller() -> PipelineController:
    db_path = os.environ.get("WOBSONGO_DB_PATH", "wobsongo.db")
    repo = SQLiteRepository(db_path)

    llm_choice = os.environ.get("WOBSONGO_LLM", "stub").lower()
    if llm_choice == "openai":
        from wobsongo.adapters.llm_openai import OpenAILLMClient  # lazy import

        llm: object = OpenAILLMClient()
    else:
        llm = StubLLMClient()

    embed_choice = os.environ.get("WOBSONGO_EMBEDDER", "stub").lower()
    if embed_choice == "bge":
        from wobsongo.adapters.embed_bge import BGEEmbedder  # lazy import

        embedder: object = BGEEmbedder()
    else:
        embedder = _StubEmbedder()

    return PipelineController(repo=repo, llm=llm, embedder=embedder)  # type: ignore[arg-type]


# ------------------------------------------------------------------
# Route handlers
# ------------------------------------------------------------------


@post("/api/v1/verify")
async def verify_handler(
    data: VerifyRequest,
    pipeline: PipelineController,
) -> dict[str, object]:
    topic_tag = (
        TaxonomyTag(path=data.topic_path, label=data.topic_path)
        if data.topic_path
        else None
    )
    post_obj = Post(
        id=uuid4(),
        raw_text=data.text,
        source=data.source,
        language=data.language,
        topic_tag=topic_tag,
    )
    result: VerificationResult = await pipeline.verify(post_obj)
    return dataclasses.asdict(result)


@post("/api/v1/ingest")
async def ingest_handler(
    data: UploadFile = Body(media_type=RequestEncodingType.MULTI_PART),
    pipeline: PipelineController = Body(default=None),  # injected via DI
) -> IngestResponse:
    content = await data.read()
    markdown = content.decode("utf-8", errors="replace")
    source_doc_id = uuid4()

    facts = await pipeline.ingest_document(markdown, source_doc_id)

    # count paragraphs as proxy for chunks stored
    chunks_stored = len([p for p in markdown.split("\n\n") if p.strip()])

    return IngestResponse(
        facts_extracted=len(facts),
        chunks_stored=chunks_stored,
        source_doc_id=str(source_doc_id),
    )


# ------------------------------------------------------------------
# App
# ------------------------------------------------------------------


app = Litestar(
    route_handlers=[verify_handler, ingest_handler],
    dependencies={"pipeline": Provide(make_controller, sync_to_thread=False)},
)
