"""
Tests for SQLiteRepository adapter.
Uses in-memory SQLite — no disk I/O, no teardown needed.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from wobsongo.adapters.db_sqlite import SQLiteRepository
from wobsongo.adapters.llm_stub import StubLLMClient
from wobsongo.core.domain import DocumentChunk, VerifiedFact
from wobsongo.core.ports import (
    LLMClientProtocol,
    RepositoryProtocol,
)

# ------------------------------------------------------------------
# Protocol conformance
# ------------------------------------------------------------------


def test_sqlite_repo_satisfies_protocol() -> None:
    repo = SQLiteRepository(":memory:")
    assert isinstance(repo, RepositoryProtocol)


def test_stub_llm_satisfies_protocol() -> None:
    stub = StubLLMClient()
    assert isinstance(stub, LLMClientProtocol)


# ------------------------------------------------------------------
# VerifiedFact round-trip
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_retrieve_fact() -> None:
    repo = SQLiteRepository(":memory:")
    chunk_id = uuid4()

    fact = VerifiedFact(
        id=uuid4(),
        subject="vaccine",
        predicate="causes",
        object="sterility",
        truth_tier=1,
        topic_path="health.vaccines",
        source_chunk_id=chunk_id,
    )

    await repo.save_fact(fact)
    results = await repo.get_facts_by_subject("vaccine")

    assert len(results) == 1
    retrieved = results[0]
    assert retrieved.id == fact.id
    assert retrieved.subject == fact.subject
    assert retrieved.predicate == fact.predicate
    assert retrieved.object == fact.object
    assert retrieved.truth_tier == fact.truth_tier
    assert retrieved.topic_path == fact.topic_path
    assert retrieved.source_chunk_id == fact.source_chunk_id
    assert retrieved.valid_from is None
    assert retrieved.conditions is None


@pytest.mark.asyncio
async def test_save_fact_with_optional_fields() -> None:
    repo = SQLiteRepository(":memory:")
    chunk_id = uuid4()

    fact = VerifiedFact(
        id=uuid4(),
        subject="aspirin",
        predicate="is safe",
        object="adults",
        truth_tier=3,
        topic_path="health.medication",
        source_chunk_id=chunk_id,
        valid_from=date(2020, 1, 1),
        conditions="dosage < 500mg",
    )

    await repo.save_fact(fact)
    results = await repo.get_facts_by_subject("aspirin")

    assert len(results) == 1
    retrieved = results[0]
    assert retrieved.valid_from == date(2020, 1, 1)
    assert retrieved.conditions == "dosage < 500mg"


@pytest.mark.asyncio
async def test_get_facts_by_subject_partial_match() -> None:
    repo = SQLiteRepository(":memory:")
    chunk_id = uuid4()

    for subject in ("covid vaccine", "flu vaccine", "unrelated"):
        await repo.save_fact(
            VerifiedFact(
                id=uuid4(),
                subject=subject,
                predicate="is",
                object="safe",
                truth_tier=1,
                topic_path="health.vaccines",
                source_chunk_id=chunk_id,
            )
        )

    results = await repo.get_facts_by_subject("vaccine")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_save_fact_upsert() -> None:
    repo = SQLiteRepository(":memory:")
    chunk_id = uuid4()
    fact_id = uuid4()

    fact = VerifiedFact(
        id=fact_id,
        subject="earth",
        predicate="is",
        object="round",
        truth_tier=1,
        topic_path="science.astronomy",
        source_chunk_id=chunk_id,
    )
    await repo.save_fact(fact)

    # upsert same id with different object
    updated = VerifiedFact(
        id=fact_id,
        subject="earth",
        predicate="is",
        object="an oblate spheroid",
        truth_tier=1,
        topic_path="science.astronomy",
        source_chunk_id=chunk_id,
    )
    await repo.save_fact(updated)

    results = await repo.get_facts_by_subject("earth")
    assert len(results) == 1
    assert results[0].object == "an oblate spheroid"


# ------------------------------------------------------------------
# DocumentChunk round-trip
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_chunk() -> None:
    repo = SQLiteRepository(":memory:")

    chunk = DocumentChunk(
        id=uuid4(),
        text="Vaccines are safe and effective.",
        embedding=[0.1, 0.2, 0.3],
        source_doc_id=uuid4(),
        topic_path="health.vaccines",
    )

    # should not raise
    await repo.save_chunk(chunk)


@pytest.mark.asyncio
async def test_save_chunk_empty_embedding() -> None:
    repo = SQLiteRepository(":memory:")

    chunk = DocumentChunk(
        id=uuid4(),
        text="No embedding yet.",
        embedding=[],
        source_doc_id=uuid4(),
        topic_path="health.general",
    )

    await repo.save_chunk(chunk)


# ------------------------------------------------------------------
# StubLLMClient
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_llm_decompose() -> None:
    stub = StubLLMClient()
    result = await stub.generate_json("decompose this text into atomic claims", {})
    assert "claims" in result
    assert isinstance(result["claims"], list)


@pytest.mark.asyncio
async def test_stub_llm_verdict() -> None:
    stub = StubLLMClient()
    result = await stub.generate_json("adjudicate verdict for this claim", {})
    assert result["verdict"] in ("SUPPORTED", "REFUTED", "INSUFFICIENT_EVIDENCE")
    assert isinstance(result["confidence"], float)


@pytest.mark.asyncio
async def test_stub_llm_topic() -> None:
    stub = StubLLMClient()
    result = await stub.generate_json("classify topic taxonomy for document", {})
    assert "topic_path" in result


@pytest.mark.asyncio
async def test_stub_llm_extract() -> None:
    stub = StubLLMClient()
    result = await stub.generate_json("extract subject predicate object triples", {})
    assert "facts" in result
    assert isinstance(result["facts"], list)


@pytest.mark.asyncio
async def test_stub_llm_fallback() -> None:
    stub = StubLLMClient()
    result = await stub.generate_json("unrecognized prompt type", {})
    assert result == {}
