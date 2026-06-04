"""
Wobsongo ingestion worker.

Polls the ingestion_jobs table for pending jobs, downloads each PDF from
object storage, parses it, and runs the DocumentIngestor pipeline.

Setup:
  Add S3_* and WOBSONGO_* vars to .env, then:
  uv run python worker.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from wobsongo.adapters.db_sqlite import SQLiteRepository
from wobsongo.adapters.embed_ollama import OllamaEmbedder
from wobsongo.adapters.llm_ollama import OllamaLLMClient
from wobsongo.adapters.pdf_parser import parse_document
from wobsongo.adapters.storage_s3 import S3Storage
from wobsongo.core.domain import IngestionJob
from wobsongo.core.services.ingestion import DocumentIngestor

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


async def process_job(
    job: IngestionJob,
    repo: SQLiteRepository,
    storage: S3Storage,
    ingestor: DocumentIngestor,
) -> None:
    tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=".pdf")
    tmp_path = Path(tmp_path_str)
    os.close(tmp_fd)
    try:
        log.info("Downloading %s → %s", job.storage_key, tmp_path)
        await storage.download_file(job.storage_key, tmp_path)

        log.info("Parsing %s", job.filename)
        doc = parse_document(tmp_path, title=job.title)
        log.info("Parsed: %d pages, %d chunks", doc.metadata.num_pages, len(doc.chunks))

        facts = await ingestor.ingest_document(doc)
        log.info("Ingested. Facts extracted: %d", len(facts))

        await repo.update_job(
            job.id,
            status="done",
            content_hash=doc.metadata.content_hash,
            chunks_stored=len(doc.chunks),
            facts_extracted=len(facts),
            finished_at=_now_iso(),
        )
    finally:
        tmp_path.unlink(missing_ok=True)


async def run() -> None:
    db_path = os.getenv("WOBSONGO_DB_PATH", "wobsongo.db")
    poll_interval = int(os.getenv("WORKER_POLL_INTERVAL", "10"))

    repo = SQLiteRepository(db_path)
    storage = S3Storage(
        bucket=os.environ["S3_BUCKET"],
        endpoint_url=os.getenv("S3_ENDPOINT_URL"),
    )
    llm = OllamaLLMClient()
    embedder = OllamaEmbedder()
    ingestor = DocumentIngestor(llm=llm, embedder=embedder, repo=repo)

    log.info("Worker started. DB=%s, poll every %ds.", db_path, poll_interval)

    while True:
        job = await repo.claim_next_job()
        if job is None:
            await asyncio.sleep(poll_interval)
            continue

        log.info("Claimed job %s (%s)", job.id, job.filename)
        try:
            await process_job(job, repo, storage, ingestor)
            log.info("Job %s done.", job.id)
        except Exception as exc:
            log.exception("Job %s failed: %s", job.id, exc)
            await repo.update_job(
                job.id,
                status="failed",
                error_message=str(exc),
                finished_at=_now_iso(),
            )


if __name__ == "__main__":
    asyncio.run(run())
