"""
wobsongo.adapters.db_sqlite
~~~~~~~~~~~~~~~~~~~~~~~~~~~
SQLiteRepository — satisfies RepositoryProtocol.

Uses stdlib sqlite3 only. Blocking calls wrapped in asyncio.to_thread().
Schema created synchronously on __init__ (one-time startup cost).

Embedding serialization: struct.pack/unpack ('Nf' * len) for compact BLOB.
Vector search via sqlite-vec: a vec0 virtual table mirrors chunk embeddings.
sqlite-vec is loaded on __init__; if the extension is absent the repo still
works but get_chunks_by_vector() returns [].
WAL mode enabled for better concurrent read performance.

Foreign keys are declared in the DDL for documentation but enforcement is
intentionally left off (PRAGMA foreign_keys is not set) so that tests can
insert chunks and facts independently without needing a parent document row.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import struct
from datetime import date
from pathlib import Path
from uuid import UUID

from wobsongo.core.domain import DocumentChunk, IngestionJob, SourceDocument, User, VerifiedFact

log = logging.getLogger(__name__)

try:
    import sqlite_vec

    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    _SQLITE_VEC_AVAILABLE = False

_VEC_TOP_K = 10  # number of nearest neighbours returned by vector search

_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    content_hash    TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    filename        TEXT NOT NULL,
    file_type       TEXT NOT NULL,
    file_size       INTEGER NOT NULL,
    num_pages       INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    modified_at     TEXT NOT NULL,
    ingested_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id                  TEXT PRIMARY KEY,
    source_doc_id       TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    text                TEXT NOT NULL,
    embedding           BLOB,
    topic_path          TEXT NOT NULL,
    factuality_score    REAL NOT NULL DEFAULT 0.0,
    page                INTEGER NOT NULL DEFAULT 0,
    chapter             TEXT,
    line_start          INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_chunks_source_doc ON document_chunks(source_doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_topic      ON document_chunks(topic_path);
CREATE INDEX IF NOT EXISTS idx_chunks_score      ON document_chunks(factuality_score);

CREATE TABLE IF NOT EXISTS verified_facts (
    id              TEXT PRIMARY KEY,
    source_chunk_id TEXT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    source_doc_id   TEXT REFERENCES documents(id) ON DELETE CASCADE,
    subject         TEXT NOT NULL,
    predicate       TEXT NOT NULL,
    object          TEXT NOT NULL,
    truth_tier      INTEGER NOT NULL CHECK (truth_tier BETWEEN 1 AND 4),
    topic_path      TEXT NOT NULL,
    valid_from      TEXT,
    conditions      TEXT
);

CREATE INDEX IF NOT EXISTS idx_facts_subject ON verified_facts(subject);
CREATE INDEX IF NOT EXISTS idx_facts_doc     ON verified_facts(source_doc_id);
CREATE INDEX IF NOT EXISTS idx_facts_topic   ON verified_facts(topic_path);
CREATE INDEX IF NOT EXISTS idx_facts_tier    ON verified_facts(truth_tier);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id              TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'pending',
    title           TEXT NOT NULL,
    filename        TEXT NOT NULL,
    storage_key     TEXT NOT NULL,
    content_hash    TEXT,
    chunks_stored   INTEGER,
    facts_extracted INTEGER,
    error_message   TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON ingestion_jobs(status, created_at);

CREATE TABLE IF NOT EXISTS users (
    id                  TEXT PRIMARY KEY,
    email               TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,
    role                TEXT NOT NULL DEFAULT 'viewer',
    is_active           INTEGER NOT NULL DEFAULT 1,
    is_email_verified   INTEGER NOT NULL DEFAULT 0,
    last_login_at       TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
"""


def _pack_embedding(embedding: list[float]) -> bytes:
    n = len(embedding)
    return struct.pack(f"{n}f", *embedding)


def _unpack_embedding(blob: bytes) -> list[float]:
    n = len(blob) // struct.calcsize("f")
    return list(struct.unpack(f"{n}f", blob))


def _row_to_document(row: sqlite3.Row) -> SourceDocument:
    return SourceDocument(
        id=UUID(row["id"]),
        content_hash=row["content_hash"],
        title=row["title"],
        filename=row["filename"],
        file_type=row["file_type"],
        file_size=row["file_size"],
        num_pages=row["num_pages"],
        created_at=row["created_at"],
        modified_at=row["modified_at"],
        ingested_at=row["ingested_at"],
    )


def _row_to_chunk(row: sqlite3.Row) -> DocumentChunk:
    keys = row.keys()
    return DocumentChunk(
        id=UUID(row["id"]),
        source_doc_id=UUID(row["source_doc_id"]),
        text=row["text"],
        embedding=_unpack_embedding(row["embedding"]) if row["embedding"] else [],
        topic_path=row["topic_path"],
        factuality_score=row["factuality_score"],
        page=row["page"],
        chapter=row["chapter"],
        line_start=row["line_start"],
        source_doc_title=row["doc_title"] if "doc_title" in keys else None,
    )


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=UUID(row["id"]),
        email=row["email"],
        password_hash=row["password_hash"],
        role=row["role"],
        is_active=bool(row["is_active"]),
        is_email_verified=bool(row["is_email_verified"]),
        last_login_at=row["last_login_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_job(row: sqlite3.Row) -> IngestionJob:
    return IngestionJob(
        id=UUID(row["id"]),
        status=row["status"],
        title=row["title"],
        filename=row["filename"],
        storage_key=row["storage_key"],
        created_at=row["created_at"],
        content_hash=row["content_hash"],
        chunks_stored=row["chunks_stored"],
        facts_extracted=row["facts_extracted"],
        error_message=row["error_message"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
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
        source_doc_id=UUID(row["source_doc_id"]) if row["source_doc_id"] else None,
        valid_from=date.fromisoformat(row["valid_from"]) if row["valid_from"] else None,
        conditions=row["conditions"],
    )


class SQLiteRepository:
    """SQLite-backed repository. Satisfies RepositoryProtocol."""

    def __init__(self, db_path: str | Path = ":memory:", embedding_dim: int = 768) -> None:
        self._db_path = str(db_path)
        self._embedding_dim = embedding_dim
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        self._vec_enabled = False
        if _SQLITE_VEC_AVAILABLE:
            try:
                self._conn.enable_load_extension(True)
                sqlite_vec.load(self._conn)
                self._conn.enable_load_extension(False)
                self._vec_enabled = True
            except Exception:
                pass

        self._conn.executescript(_SCHEMA)
        if self._vec_enabled:
            self._conn.executescript(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks "
                f"USING vec0(chunk_id TEXT PRIMARY KEY, embedding float[{embedding_dim}]);"
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    async def save_document(self, doc: SourceDocument) -> None:
        await asyncio.to_thread(self._save_document_sync, doc)

    async def get_document_by_hash(self, content_hash: str) -> SourceDocument | None:
        return await asyncio.to_thread(self._get_document_by_hash_sync, content_hash)

    async def get_document(self, doc_id: UUID) -> SourceDocument | None:
        return await asyncio.to_thread(self._get_document_sync, doc_id)

    async def list_documents(
        self, page: int, page_size: int
    ) -> tuple[list[SourceDocument], int]:
        return await asyncio.to_thread(self._list_documents_sync, page, page_size)

    async def delete_document(self, doc_id: UUID) -> None:
        await asyncio.to_thread(self._delete_document_sync, doc_id)

    async def count_chunks_for_doc(self, doc_id: UUID) -> int:
        return await asyncio.to_thread(self._count_chunks_for_doc_sync, doc_id)

    async def count_facts_for_doc(self, doc_id: UUID) -> int:
        return await asyncio.to_thread(self._count_facts_for_doc_sync, doc_id)

    # ------------------------------------------------------------------
    # Chunks
    # ------------------------------------------------------------------

    async def save_chunk(self, chunk: DocumentChunk) -> None:
        await asyncio.to_thread(self._save_chunk_sync, chunk)

    async def get_chunks_by_vector(
        self,
        vector: list[float],
        topic_filter: str,
    ) -> list[DocumentChunk]:
        return await asyncio.to_thread(self._get_chunks_by_vector_sync, vector, topic_filter)

    # ------------------------------------------------------------------
    # Facts
    # ------------------------------------------------------------------

    async def save_fact(self, fact: VerifiedFact) -> None:
        await asyncio.to_thread(self._save_fact_sync, fact)

    async def get_facts_by_subject(self, subject: str) -> list[VerifiedFact]:
        return await asyncio.to_thread(self._get_facts_by_subject_sync, subject)

    async def get_facts_by_chunk_ids(self, chunk_ids: list[UUID]) -> list[VerifiedFact]:
        return await asyncio.to_thread(self._get_facts_by_chunk_ids_sync, chunk_ids)

    async def get_facts_by_topic_path(self, topic_path: str) -> list[VerifiedFact]:
        return await asyncio.to_thread(self._get_facts_by_topic_path_sync, topic_path)

    async def get_facts_by_truth_tier(self, truth_tier: int) -> list[VerifiedFact]:
        return await asyncio.to_thread(self._get_facts_by_truth_tier_sync, truth_tier)

    # ------------------------------------------------------------------
    # Private sync implementations
    # ------------------------------------------------------------------

    def _save_document_sync(self, doc: SourceDocument) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO documents
                (id, content_hash, title, filename, file_type,
                 file_size, num_pages, created_at, modified_at, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(doc.id),
                doc.content_hash,
                doc.title,
                doc.filename,
                doc.file_type,
                doc.file_size,
                doc.num_pages,
                doc.created_at,
                doc.modified_at,
                doc.ingested_at,
            ),
        )
        self._conn.commit()

    def _get_document_by_hash_sync(self, content_hash: str) -> SourceDocument | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        return _row_to_document(row) if row else None

    def _get_document_sync(self, doc_id: UUID) -> SourceDocument | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE id = ?", (str(doc_id),)
        ).fetchone()
        return _row_to_document(row) if row else None

    def _list_documents_sync(
        self, page: int, page_size: int
    ) -> tuple[list[SourceDocument], int]:
        total: int = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        offset = (page - 1) * page_size
        rows = self._conn.execute(
            "SELECT * FROM documents ORDER BY ingested_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        return [_row_to_document(r) for r in rows], total

    def _delete_document_sync(self, doc_id: UUID) -> None:
        self._conn.execute("DELETE FROM documents WHERE id = ?", (str(doc_id),))
        self._conn.commit()

    def _count_chunks_for_doc_sync(self, doc_id: UUID) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM document_chunks WHERE source_doc_id = ?", (str(doc_id),)
        ).fetchone()
        return int(row[0])

    def _count_facts_for_doc_sync(self, doc_id: UUID) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM verified_facts WHERE source_doc_id = ?", (str(doc_id),)
        ).fetchone()
        return int(row[0])

    def _save_chunk_sync(self, chunk: DocumentChunk) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO document_chunks
                (id, source_doc_id, text, embedding, topic_path,
                 factuality_score, page, chapter, line_start)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(chunk.id),
                str(chunk.source_doc_id),
                chunk.text,
                _pack_embedding(chunk.embedding) if chunk.embedding else None,
                chunk.topic_path,
                chunk.factuality_score,
                chunk.page,
                chunk.chapter,
                chunk.line_start,
            ),
        )
        if self._vec_enabled:
            if len(chunk.embedding) == self._embedding_dim:
                self._conn.execute(
                    "INSERT OR REPLACE INTO vec_chunks(chunk_id, embedding) VALUES (?, ?)",
                    (str(chunk.id), sqlite_vec.serialize_float32(chunk.embedding)),
                )
            else:
                log.warning(
                    "Chunk %s skipped from vector index: embedding dim %d != expected %d",
                    chunk.id,
                    len(chunk.embedding),
                    self._embedding_dim,
                )
        self._conn.commit()

    def _get_chunks_by_vector_sync(
        self, vector: list[float], topic_filter: str
    ) -> list[DocumentChunk]:
        if not self._vec_enabled or len(vector) != self._embedding_dim:
            return []
        query_vec = sqlite_vec.serialize_float32(vector)
        rows = self._conn.execute(
            """
            SELECT dc.*, d.title AS doc_title
            FROM vec_chunks vc
            JOIN document_chunks dc ON dc.id = vc.chunk_id
            LEFT JOIN documents d ON d.id = dc.source_doc_id
            WHERE vc.embedding MATCH ?
              AND vc.k = ?
              AND dc.topic_path LIKE ?
            ORDER BY vc.distance
            """,
            (query_vec, _VEC_TOP_K, f"{topic_filter}%"),
        ).fetchall()
        return [_row_to_chunk(row) for row in rows]

    def _save_fact_sync(self, fact: VerifiedFact) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO verified_facts
                (id, source_chunk_id, source_doc_id, subject, predicate, object,
                 truth_tier, topic_path, valid_from, conditions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(fact.id),
                str(fact.source_chunk_id),
                str(fact.source_doc_id) if fact.source_doc_id else None,
                fact.subject,
                fact.predicate,
                fact.object,
                fact.truth_tier,
                fact.topic_path,
                fact.valid_from.isoformat() if fact.valid_from else None,
                fact.conditions,
            ),
        )
        self._conn.commit()

    def _get_facts_by_subject_sync(self, subject: str) -> list[VerifiedFact]:
        rows = self._conn.execute(
            "SELECT * FROM verified_facts WHERE subject LIKE ?",
            (f"%{subject}%",),
        ).fetchall()
        return [_row_to_fact(row) for row in rows]

    def _get_facts_by_chunk_ids_sync(self, chunk_ids: list[UUID]) -> list[VerifiedFact]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" * len(chunk_ids))
        rows = self._conn.execute(
            f"SELECT * FROM verified_facts WHERE source_chunk_id IN ({placeholders})",
            [str(cid) for cid in chunk_ids],
        ).fetchall()
        return [_row_to_fact(row) for row in rows]

    def _get_facts_by_topic_path_sync(self, topic_path: str) -> list[VerifiedFact]:
        rows = self._conn.execute(
            "SELECT * FROM verified_facts WHERE topic_path LIKE ?",
            (f"{topic_path}%",),
        ).fetchall()
        return [_row_to_fact(row) for row in rows]

    def _get_facts_by_truth_tier_sync(self, truth_tier: int) -> list[VerifiedFact]:
        rows = self._conn.execute(
            "SELECT * FROM verified_facts WHERE truth_tier = ?",
            (truth_tier,),
        ).fetchall()
        return [_row_to_fact(row) for row in rows]

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    async def save_job(self, job: IngestionJob) -> None:
        await asyncio.to_thread(self._save_job_sync, job)

    async def get_job(self, job_id: UUID) -> IngestionJob | None:
        return await asyncio.to_thread(self._get_job_sync, job_id)

    async def list_jobs(
        self, status: str | None, page: int, page_size: int
    ) -> tuple[list[IngestionJob], int]:
        return await asyncio.to_thread(self._list_jobs_sync, status, page, page_size)

    async def claim_next_job(self) -> IngestionJob | None:
        return await asyncio.to_thread(self._claim_next_job_sync)

    async def update_job(self, job_id: UUID, **fields: object) -> None:
        await asyncio.to_thread(self._update_job_sync, job_id, fields)

    def _save_job_sync(self, job: IngestionJob) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO ingestion_jobs
                (id, status, title, filename, storage_key, content_hash,
                 chunks_stored, facts_extracted, error_message,
                 created_at, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(job.id), job.status, job.title, job.filename, job.storage_key,
                job.content_hash, job.chunks_stored, job.facts_extracted,
                job.error_message, job.created_at, job.started_at, job.finished_at,
            ),
        )
        self._conn.commit()

    def _get_job_sync(self, job_id: UUID) -> IngestionJob | None:
        row = self._conn.execute(
            "SELECT * FROM ingestion_jobs WHERE id = ?", (str(job_id),)
        ).fetchone()
        return _row_to_job(row) if row else None

    def _list_jobs_sync(
        self, status: str | None, page: int, page_size: int
    ) -> tuple[list[IngestionJob], int]:
        params: list[object] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        total: int = self._conn.execute(
            f"SELECT COUNT(*) FROM ingestion_jobs {where}", params
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows = self._conn.execute(
            f"SELECT * FROM ingestion_jobs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ).fetchall()
        return [_row_to_job(r) for r in rows], total

    def _claim_next_job_sync(self) -> IngestionJob | None:
        # Atomic: select + update in one statement using RETURNING (SQLite >= 3.35)
        row = self._conn.execute(
            """
            UPDATE ingestion_jobs
            SET status = 'processing', started_at = datetime('now')
            WHERE id = (
                SELECT id FROM ingestion_jobs
                WHERE status = 'pending'
                ORDER BY created_at
                LIMIT 1
            )
            RETURNING *
            """
        ).fetchone()
        self._conn.commit()
        return _row_to_job(row) if row else None

    _ALLOWED_JOB_FIELDS = frozenset({
        "status", "content_hash", "chunks_stored", "facts_extracted",
        "error_message", "started_at", "finished_at",
    })

    def _update_job_sync(self, job_id: UUID, fields: dict[str, object]) -> None:
        updates = {k: v for k, v in fields.items() if k in self._ALLOWED_JOB_FIELDS}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values: list[object] = [*updates.values(), str(job_id)]
        self._conn.execute(
            f"UPDATE ingestion_jobs SET {set_clause} WHERE id = ?", values
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    async def save_user(self, user: User) -> None:
        await asyncio.to_thread(self._save_user_sync, user)

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        return await asyncio.to_thread(self._get_user_by_id_sync, user_id)

    async def get_user_by_email(self, email: str) -> User | None:
        return await asyncio.to_thread(self._get_user_by_email_sync, email)

    async def list_users(self, page: int, page_size: int) -> tuple[list[User], int]:
        return await asyncio.to_thread(self._list_users_sync, page, page_size)

    async def update_user(self, user_id: UUID, **fields: object) -> None:
        await asyncio.to_thread(self._update_user_sync, user_id, fields)

    async def delete_user(self, user_id: UUID) -> None:
        await asyncio.to_thread(self._delete_user_sync, user_id)

    def _save_user_sync(self, user: User) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO users
                (id, email, password_hash, role, is_active, is_email_verified,
                 last_login_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(user.id), user.email, user.password_hash, user.role,
                int(user.is_active), int(user.is_email_verified),
                user.last_login_at, user.created_at, user.updated_at,
            ),
        )
        self._conn.commit()

    def _get_user_by_id_sync(self, user_id: UUID) -> User | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE id = ?", (str(user_id),)
        ).fetchone()
        return _row_to_user(row) if row else None

    def _get_user_by_email_sync(self, email: str) -> User | None:
        row = self._conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
        return _row_to_user(row) if row else None

    def _list_users_sync(self, page: int, page_size: int) -> tuple[list[User], int]:
        total: int = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        offset = (page - 1) * page_size
        rows = self._conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
        return [_row_to_user(r) for r in rows], total

    _ALLOWED_USER_FIELDS = frozenset({
        "email", "password_hash", "role", "is_active",
        "is_email_verified", "last_login_at", "updated_at",
    })

    def _update_user_sync(self, user_id: UUID, fields: dict[str, object]) -> None:
        updates = {k: v for k, v in fields.items() if k in self._ALLOWED_USER_FIELDS}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values: list[object] = [*updates.values(), str(user_id)]
        self._conn.execute(
            f"UPDATE users SET {set_clause} WHERE id = ?", values
        )
        self._conn.commit()

    def _delete_user_sync(self, user_id: UUID) -> None:
        self._conn.execute("DELETE FROM users WHERE id = ?", (str(user_id),))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
