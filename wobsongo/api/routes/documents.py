"""GET /api/v3/documents, GET/DELETE /api/v3/documents/{doc_id}"""

from __future__ import annotations

from uuid import UUID

from litestar import delete, get
from litestar.exceptions import HTTPException

from wobsongo.api.schemas.documents import (
    DocumentDetail,
    DocumentListItem,
    PaginatedDocuments,
)
from wobsongo.core.exceptions import NotFoundError
from wobsongo.core.services.document_service import DocumentService


@get("/api/v3/documents")
async def list_documents_handler(
    document_service: DocumentService,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedDocuments:
    if page < 1 or not (1 <= page_size <= 100):
        raise HTTPException(status_code=422, detail="page must be ≥ 1; page_size must be 1-100")
    docs, total = await document_service.list_documents(page=page, page_size=page_size)
    items = [
        DocumentListItem(
            id=str(doc.id),
            title=doc.title,
            filename=doc.filename,
            num_pages=doc.num_pages,
            ingested_at=doc.ingested_at,
        )
        for doc in docs
    ]
    return PaginatedDocuments(items=items, total=total, page=page, page_size=page_size)


@get("/api/v3/documents/{doc_id:uuid}")
async def get_document_handler(
    doc_id: UUID,
    document_service: DocumentService,
) -> DocumentDetail:
    try:
        doc, chunks_count, facts_count = await document_service.get_document(doc_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DocumentDetail(
        id=str(doc.id),
        title=doc.title,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        num_pages=doc.num_pages,
        content_hash=doc.content_hash,
        ingested_at=doc.ingested_at,
        chunks_stored=chunks_count,
        facts_extracted=facts_count,
    )


@delete("/api/v3/documents/{doc_id:uuid}", status_code=204)
async def delete_document_handler(
    doc_id: UUID,
    document_service: DocumentService,
) -> None:
    try:
        await document_service.delete_document(doc_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
