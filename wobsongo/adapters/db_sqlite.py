"""
wobsongo.adapters.db_sqlite
~~~~~~~~~~~~~~~~~~~~~~~~~~~
SQLiteRepository — satisfies RepositoryProtocol.

Uses stdlib sqlite3 only. Blocking calls wrapped in asyncio.to_thread().
Schema created synchronously on __init__ (one-time startup cost).

Embedding serialization: struct.pack/unpack ('Nf' * len) for compact BLOB.
sqlite-vec loading is deferred — vector search stubs to [] if ext absent.
WAL mode enabled for better concurrent read performance.
"""

from __future__ import annotations

import asyncio
import sqlite3
import struct
from datetime import date
from pathlib import Path
from uuid import UUID

from wobsongo.core.domain import DocumentChunk, VerifiedFact

_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS document_chunks (
    id              TEXT PRIMARY KEY,
    text            TEXT NOT NULL,
    embedding       BLOB,
    source_doc_id   TEXT NOT NULL,
    topic_path      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verified_facts (
    id              TEXT PRIMARY KEY,
    subject         TEXT NOT NULL,
    predicate       TEXT NOT NULL,
    object          TEXT NOT NULL,
    truth_tier      INTEGER NOT NULL,
    topic_path      TEXT NOT NULL,
    valid_from      TEXT,
    conditions      TEXT,
    source_chunk_id TEXT NOT NULL
);
"""


def _pack_embedding(embedding: list[float]) -> bytes:
    n = len(embedding)
    return struct.pack(f"{n}f", *embedding)


def _unpack_embedding(blob: bytes) -> list[float]:
    n = len(blob) // struct.calcsize("f")
    return list(struct.unpack(f"{n}f", blob))


def _row_to_chunk(row: sqlite3.Row) -> DocumentChunk:
    return DocumentChunk(
        id=UUID(row["id"]),
        text=row["text"],
        embedding=_unpack_embedding(row["embedding"]) if row["embedding"] else [],
        source_doc_id=UUID(row["source_doc_id"]),
        topic_path=row["topic_path"],
    )


def _row_to_fact(row: sqlite3.Row) -> VerifiedFact:
    return VerifiedFact(
        id=UUID(row["id"]),
        subject=row["subject"],
        predicate=row["predicate"],
        object=row["object"],
        truth_tier=row["truth_tier"],
        topic_path=row["topic_path"],
        source_chunk_id=UUID(row["source_chunk_id"]),
        valid_from=date.fromisoformat(row["valid_from"]) if row["valid_from"] else None,
        conditions=row["conditions"],
    )


class SQLiteRepository:
    """SQLite-backed repository. Satisfies RepositoryProtocol."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public async interface (RepositoryProtocol)
    # ------------------------------------------------------------------

    async def save_fact(self, fact: VerifiedFact) -> None:
        await asyncio.to_thread(self._save_fact_sync, fact)

    async def save_chunk(self, chunk: DocumentChunk) -> None:
        await asyncio.to_thread(self._save_chunk_sync, chunk)

    async def get_chunks_by_vector(
        self,
        vector: list[float],
        topic_filter: str,
    ) -> list[DocumentChunk]:
        # sqlite-vec deferred — return [] stub until extension loaded
        return []

    async def get_facts_by_subject(self, subject: str) -> list[VerifiedFact]:
        return await asyncio.to_thread(self._get_facts_by_subject_sync, subject)

    # ------------------------------------------------------------------
    # Private sync implementations
    # ------------------------------------------------------------------

    def _save_fact_sync(self, fact: VerifiedFact) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO verified_facts
                (id, subject, predicate, object, truth_tier, topic_path,
                 valid_from, conditions, source_chunk_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(fact.id),
                fact.subject,
                fact.predicate,
                fact.object,
                fact.truth_tier,
                fact.topic_path,
                fact.valid_from.isoformat() if fact.valid_from else None,
                fact.conditions,
                str(fact.source_chunk_id),
            ),
        )
        self._conn.commit()

    def _save_chunk_sync(self, chunk: DocumentChunk) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO document_chunks
                (id, text, embedding, source_doc_id, topic_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(chunk.id),
                chunk.text,
                _pack_embedding(chunk.embedding) if chunk.embedding else None,
                str(chunk.source_doc_id),
                chunk.topic_path,
            ),
        )
        self._conn.commit()

    def _get_facts_by_subject_sync(self, subject: str) -> list[VerifiedFact]:
        cursor = self._conn.execute(
            "SELECT * FROM verified_facts WHERE subject LIKE ?",
            (f"%{subject}%",),
        )
        return [_row_to_fact(row) for row in cursor.fetchall()]

    def close(self) -> None:
        self._conn.close()
