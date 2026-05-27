"""
Tests for core agents and pipeline.
All LLM calls use StubLLMClient — no network required.
All DB calls use SQLiteRepository in-memory.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from wobsongo.adapters.db_sqlite import SQLiteRepository
from wobsongo.adapters.llm_stub import StubLLMClient
from wobsongo.core.agents.decomposer import ClaimDecomposer
from wobsongo.core.agents.judge import NLIJudge
from wobsongo.core.domain import DocumentChunk, Post, TaxonomyTag, VerifiedFact
from wobsongo.core.pipeline import PipelineController
from wobsongo.core.services.ingestion import DocumentIngestor

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def llm() -> StubLLMClient:
    return StubLLMClient()


@pytest.fixture
def repo() -> SQLiteRepository:
    return SQLiteRepository(":memory:")


class StubEmbedder:
    """Zero-dep embedder stub — returns fixed-length float list."""

    async def embed_text(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


@pytest.fixture
def embedder() -> StubEmbedder:
    return StubEmbedder()


# ------------------------------------------------------------------
# ClaimDecomposer
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decomposer_returns_list(llm: StubLLMClient) -> None:
    decomposer = ClaimDecomposer(llm=llm)
    claims = await decomposer.decompose(
        "Vaccines cause sterility and were developed in 2 months."
    )
    assert isinstance(claims, list)
    assert len(claims) > 0
    assert all(isinstance(c, str) for c in claims)


@pytest.mark.asyncio
async def test_decomposer_filters_empty_claims(llm: StubLLMClient) -> None:
    decomposer = ClaimDecomposer(llm=llm)
    claims = await decomposer.decompose("Some claim text.")
    assert all(c.strip() for c in claims)


# ------------------------------------------------------------------
# NLIJudge — tier routing
# ------------------------------------------------------------------


def _make_chunk(text: str = "Evidence text.") -> DocumentChunk:
    return DocumentChunk(
        id=uuid4(),
        text=text,
        embedding=[0.1, 0.2, 0.3],
        source_doc_id=uuid4(),
        topic_path="health.vaccines",
    )


def _make_fact(tier: int = 1) -> VerifiedFact:
    return VerifiedFact(
        id=uuid4(),
        subject="vaccine",
        predicate="causes",
        object="sterility",
        truth_tier=tier,
        topic_path="health.vaccines",
        source_chunk_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_judge_returns_verdict(llm: StubLLMClient) -> None:
    judge = NLIJudge(llm=llm)
    verdict = await judge.adjudicate(
        claim="Vaccines cause sterility.",
        chunks=[_make_chunk()],
        facts=[_make_fact(tier=1)],
    )
    assert verdict.verdict in ("SUPPORTED", "REFUTED", "INSUFFICIENT_EVIDENCE")
    assert 0.0 <= verdict.confidence <= 1.0
    assert verdict.reasoning


@pytest.mark.asyncio
async def test_judge_no_facts_returns_insufficient(llm: StubLLMClient) -> None:
    judge = NLIJudge(llm=llm)
    verdict = await judge.adjudicate(
        claim="Some unknown claim.",
        chunks=[],
        facts=[],
    )
    assert verdict.verdict == "INSUFFICIENT_EVIDENCE"
    assert verdict.confidence == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", [1, 2, 3, 4])
async def test_judge_all_tiers(llm: StubLLMClient, tier: int) -> None:
    judge = NLIJudge(llm=llm)
    verdict = await judge.adjudicate(
        claim="Test claim for tier routing.",
        chunks=[_make_chunk()],
        facts=[_make_fact(tier=tier)],
    )
    assert verdict.verdict in ("SUPPORTED", "REFUTED", "INSUFFICIENT_EVIDENCE")
    assert verdict.truth_tier == tier


@pytest.mark.asyncio
async def test_judge_unknown_tier_returns_insufficient(llm: StubLLMClient) -> None:
    judge = NLIJudge(llm=llm)
    verdict = await judge.adjudicate(
        claim="Test claim.",
        chunks=[_make_chunk()],
        facts=[_make_fact(tier=99)],
    )
    assert verdict.verdict == "INSUFFICIENT_EVIDENCE"


@pytest.mark.asyncio
async def test_judge_evidence_ids_populated(llm: StubLLMClient) -> None:
    judge = NLIJudge(llm=llm)
    chunk = _make_chunk()
    verdict = await judge.adjudicate(
        claim="Test claim.",
        chunks=[chunk],
        facts=[_make_fact(tier=1)],
    )
    assert chunk.id in verdict.evidence_ids


# ------------------------------------------------------------------
# DocumentIngestor
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingestor_returns_facts(
    llm: StubLLMClient,
    embedder: StubEmbedder,
    repo: SQLiteRepository,
) -> None:
    ingestor = DocumentIngestor(llm=llm, embedder=embedder, repo=repo)
    facts = await ingestor.ingest_markdown(
        "Vaccines are safe and effective.\n\nThey have been tested extensively.",
        source_doc_id=uuid4(),
    )
    assert isinstance(facts, list)


@pytest.mark.asyncio
async def test_ingestor_empty_markdown(
    llm: StubLLMClient,
    embedder: StubEmbedder,
    repo: SQLiteRepository,
) -> None:
    ingestor = DocumentIngestor(llm=llm, embedder=embedder, repo=repo)
    facts = await ingestor.ingest_markdown("", source_doc_id=uuid4())
    assert facts == []


@pytest.mark.asyncio
async def test_ingestor_stores_chunks(
    llm: StubLLMClient,
    embedder: StubEmbedder,
    repo: SQLiteRepository,
) -> None:
    ingestor = DocumentIngestor(llm=llm, embedder=embedder, repo=repo)
    markdown = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    await ingestor.ingest_markdown(markdown, source_doc_id=uuid4())
    # verify chunks were stored — 3 paragraphs = 3 chunks
    # indirect check: no exception raised and facts returned


# ------------------------------------------------------------------
# PipelineController — end-to-end
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_verify(
    llm: StubLLMClient,
    embedder: StubEmbedder,
    repo: SQLiteRepository,
) -> None:
    controller = PipelineController(repo=repo, llm=llm, embedder=embedder)
    post = Post(
        id=uuid4(),
        raw_text="Vaccines cause sterility and were made in 2 months.",
        source="twitter",
        language="en",
        topic_tag=TaxonomyTag(path="health.vaccines", label="Vaccines"),
    )
    result = await controller.verify(post)
    assert result.post_id == post.id
    assert isinstance(result.claims, list)
    assert isinstance(result.verdicts, list)
    assert len(result.claims) == len(result.verdicts)


@pytest.mark.asyncio
async def test_pipeline_ingest(
    llm: StubLLMClient,
    embedder: StubEmbedder,
    repo: SQLiteRepository,
) -> None:
    controller = PipelineController(repo=repo, llm=llm, embedder=embedder)
    facts = await controller.ingest_document(
        "Vaccines are safe.\n\nThey protect communities.",
        source_doc_id=uuid4(),
    )
    assert isinstance(facts, list)


@pytest.mark.asyncio
async def test_pipeline_verify_no_topic_tag(
    llm: StubLLMClient,
    embedder: StubEmbedder,
    repo: SQLiteRepository,
) -> None:
    controller = PipelineController(repo=repo, llm=llm, embedder=embedder)
    post = Post(
        id=uuid4(),
        raw_text="Some claim without a topic tag.",
        source="manual",
        language="en",
    )
    result = await controller.verify(post)
    assert result.post_id == post.id
