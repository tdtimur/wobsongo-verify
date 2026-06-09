from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DocumentListItem:
    id: str
    title: str
    filename: str
    num_pages: int
    ingested_at: str
    chunks_stored: int | None = None


@dataclass
class DocumentDetail:
    id: str
    title: str
    filename: str
    file_type: str
    file_size: int
    num_pages: int
    content_hash: str
    ingested_at: str
    chunks_stored: int | None = None
    facts_extracted: int | None = None


@dataclass
class PaginatedDocuments:
    items: list[DocumentListItem] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
