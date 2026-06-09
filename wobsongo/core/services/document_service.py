"""wobsongo.core.services.document_service"""

from __future__ import annotations

from uuid import UUID

from wobsongo.core.domain import SourceDocument
from wobsongo.core.exceptions import NotFoundError
from wobsongo.core.ports import DocumentStoreProtocol


class DocumentService:
    def __init__(self, store: DocumentStoreProtocol) -> None:
        self._store = store

    async def list_documents(
        self, page: int, page_size: int
    ) -> tuple[list[SourceDocument], int]:
        return await self._store.list_documents(page=page, page_size=page_size)

    async def get_document(
        self, doc_id: UUID
    ) -> tuple[SourceDocument, int, int]:
        doc = await self._store.get_document(doc_id)
        if doc is None:
            raise NotFoundError("Document not found")
        chunks_count = await self._store.count_chunks_for_doc(doc_id)
        facts_count = await self._store.count_facts_for_doc(doc_id)
        return doc, chunks_count, facts_count

    async def delete_document(self, doc_id: UUID) -> None:
        doc = await self._store.get_document(doc_id)
        if doc is None:
            raise NotFoundError("Document not found")
        await self._store.delete_document(doc_id)
