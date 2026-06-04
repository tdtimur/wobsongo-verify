# Worker Plan — Background PDF Ingestion Service

## What this covers

The background worker process: job lifecycle, object storage adapter, polling loop, and the `parsing.py` service extraction. The API endpoints that *trigger* jobs are in `api-plan.md`.

---

## Flow

```
Admin
  POST /api/v3/jobs  →  job row (status=pending) + presigned S3 PUT URL
  PUT <presigned_url>  →  PDF lands in object storage (no app server involved)

Worker (worker.py — separate process)
  poll ingestion_jobs WHERE status='pending'
  → claim atomically (UPDATE … RETURNING)
  → download PDF from S3 to tempfile
  → parse_pdf_to_document()
  → DocumentIngestor.ingest_document()
  → update job: done | failed
```

---

## New Domain Object — `wobsongo/core/domain.py`

```python
@dataclass
class IngestionJob:
    id: UUID
    status: str           # pending | processing | done | failed
    title: str
    filename: str
    storage_key: str      # S3 object key
    created_at: str
    content_hash: str | None = None
    chunks_stored: int | None = None
    facts_extracted: int | None = None
    error_message: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
```

---

## New Protocols — `wobsongo/core/ports.py`

```python
class JobStoreProtocol(Protocol):
    async def save_job(self, job: IngestionJob) -> None: ...
    async def get_job(self, job_id: UUID) -> IngestionJob | None: ...
    async def list_jobs(
        self, status: str | None, page: int, page_size: int
    ) -> tuple[list[IngestionJob], int]: ...
    async def claim_next_job(self) -> IngestionJob | None: ...
    async def update_job(self, job_id: UUID, **fields: object) -> None: ...

class ObjectStorageProtocol(Protocol):
    def generate_upload_url(self, key: str, expires_in: int = 3600) -> str: ...
    async def download_file(self, key: str, dest_path: Path) -> None: ...
```

---

## DB Changes — `wobsongo/adapters/db_sqlite.py`

Append to `_SCHEMA`:

```sql
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
```

Atomic claim — transitions one row `pending → processing` in a single statement (SQLite `RETURNING` requires ≥ 3.35):

```sql
UPDATE ingestion_jobs
SET status = 'processing', started_at = ?
WHERE id = (
    SELECT id FROM ingestion_jobs
    WHERE status = 'pending'
    ORDER BY created_at LIMIT 1
)
RETURNING *
```

Add to `SQLiteRepository` (implementing `JobStoreProtocol`):
- `save_job(job: IngestionJob) -> None`
- `get_job(job_id: UUID) -> IngestionJob | None`
- `list_jobs(status, page, page_size) -> tuple[list[IngestionJob], int]`
- `claim_next_job() -> IngestionJob | None`
- `update_job(job_id, **fields) -> None`

---

## Object Storage Adapter — `wobsongo/adapters/storage_s3.py` (new)

Uses `boto3` (sync) wrapped in `asyncio.to_thread`.  
Supports AWS S3, MinIO, and Cloudflare R2 via `endpoint_url`.

```python
class S3Storage:
    def __init__(self, bucket: str, endpoint_url: str | None = None):
        self._bucket = bucket
        self._client = boto3.client("s3", endpoint_url=endpoint_url)

    def generate_upload_url(self, key: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def download_file(self, key: str, dest_path: Path) -> None:
        await asyncio.to_thread(
            self._client.download_file, self._bucket, key, str(dest_path)
        )
```

Environment variables:
```
S3_ENDPOINT_URL        # omit for AWS; set for MinIO / Cloudflare R2
S3_BUCKET
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_DEFAULT_REGION     # default: us-east-1
```

---

## Stub Storage — `wobsongo/adapters/storage_stub.py` (new)

```python
class StubStorage:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def generate_upload_url(self, key: str, expires_in: int = 3600) -> str:
        return f"stub://{key}"

    async def download_file(self, key: str, dest_path: Path) -> None:
        dest_path.write_bytes(self.store.get(key, b""))
```

---

## Parsing Service — `wobsongo/core/services/parsing.py` (new)

Extract from `parser.py` so both `parser.py` and `worker.py` can import it:

```python
def parse_pdf_to_document(pdf_path: Path, title: str) -> ParsedDocument:
    """Parse a PDF file into a ParsedDocument with chunk metadata."""
    ...
```

`parser.py` becomes a thin wrapper that calls this function.

---

## Worker — `worker.py` (new)

Standalone async script. No web framework.

```python
async def process_job(
    job: IngestionJob,
    job_store: JobStoreProtocol,
    storage: ObjectStorageProtocol,
    ingestor: DocumentIngestor,
) -> None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        await storage.download_file(job.storage_key, tmp_path)
        doc = parse_pdf_to_document(tmp_path, title=job.title)
        facts = await ingestor.ingest_document(doc)
        await job_store.update_job(
            job.id,
            status="done",
            content_hash=doc.metadata.content_hash,
            chunks_stored=len(doc.chunks),
            facts_extracted=len(facts),
            finished_at=datetime.utcnow().isoformat(),
        )
    finally:
        tmp_path.unlink(missing_ok=True)


async def run() -> None:
    load_dotenv()
    repo = SQLiteRepository(os.getenv("WOBSONGO_DB_PATH", "wobsongo.db"))
    storage = S3Storage(
        bucket=os.environ["S3_BUCKET"],
        endpoint_url=os.getenv("S3_ENDPOINT_URL"),
    )
    llm = OllamaLLMClient()
    embedder = OllamaEmbedder()
    ingestor = DocumentIngestor(llm=llm, embedder=embedder, repo=repo)
    interval = int(os.getenv("WORKER_POLL_INTERVAL", "10"))

    logging.info("Worker started. Polling every %ds.", interval)
    while True:
        job = await repo.claim_next_job()
        if job is None:
            await asyncio.sleep(interval)
            continue
        logging.info("Claimed job %s (%s)", job.id, job.filename)
        try:
            await process_job(job, repo, storage, ingestor)
            logging.info("Job %s done.", job.id)
        except Exception as exc:
            logging.exception("Job %s failed.", job.id)
            await repo.update_job(
                job.id,
                status="failed",
                error_message=str(exc),
                finished_at=datetime.utcnow().isoformat(),
            )
```

---

## Stub Job Store — `wobsongo/adapters/db_stub.py` (new)

```python
class StubJobStore:
    def __init__(self) -> None:
        self._jobs: dict[UUID, IngestionJob] = {}

    async def save_job(self, job: IngestionJob) -> None:
        self._jobs[job.id] = job

    async def get_job(self, job_id: UUID) -> IngestionJob | None:
        return self._jobs.get(job_id)

    async def list_jobs(self, status, page, page_size):
        items = [j for j in self._jobs.values() if status is None or j.status == status]
        start = (page - 1) * page_size
        return items[start : start + page_size], len(items)

    async def claim_next_job(self) -> IngestionJob | None:
        for job in sorted(self._jobs.values(), key=lambda j: j.created_at):
            if job.status == "pending":
                job.status = "processing"
                return job
        return None

    async def update_job(self, job_id: UUID, **fields: object) -> None:
        job = self._jobs.get(job_id)
        if job:
            for k, v in fields.items():
                setattr(job, k, v)
```

---

## Dependencies

```toml
# pyproject.toml
[project.optional-dependencies]
storage = ["boto3>=1.34"]
```

Install: `uv pip install -e ".[storage]"`

---

## Verification

```bash
# 1. Start MinIO (local S3-compatible)
docker run -p 9000:9000 \
  -e MINIO_ROOT_USER=admin \
  -e MINIO_ROOT_PASSWORD=password \
  minio/minio server /data

# 2. Create bucket (MinIO web UI at :9001, or mc cli)

# 3. Add to .env
S3_ENDPOINT_URL=http://localhost:9000
S3_BUCKET=wobsongo
AWS_ACCESS_KEY_ID=admin
AWS_SECRET_ACCESS_KEY=password

# 4. Create a job via API (see api-plan.md), upload the PDF, then:
uv run python worker.py
# → logs: Claimed job <id> (who.pdf) … Job <id> done.

# 5. Verify DB
sqlite3 wobsongo.db \
  "SELECT status, chunks_stored, facts_extracted FROM ingestion_jobs;"
```

---

## Files Changed

| File | Action |
|------|--------|
| `wobsongo/core/domain.py` | Add `IngestionJob` |
| `wobsongo/core/ports.py` | Add `JobStoreProtocol`, `ObjectStorageProtocol` |
| `wobsongo/core/services/parsing.py` | New — extract from `parser.py` |
| `wobsongo/adapters/db_sqlite.py` | Add `ingestion_jobs` table + `JobStoreProtocol` methods |
| `wobsongo/adapters/db_stub.py` | New — `StubJobStore` |
| `wobsongo/adapters/storage_s3.py` | New — `S3Storage` |
| `wobsongo/adapters/storage_stub.py` | New — `StubStorage` |
| `worker.py` | New — polling worker |
| `parser.py` | Thin wrapper over `parsing.py` |
| `pyproject.toml` | Add `storage = ["boto3>=1.34"]` |
