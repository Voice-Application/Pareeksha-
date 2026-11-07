"""Knowledge bases and their documents (docs/superpowers/plans/2026-11-07-rag-lab.md, Task 2)."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Response, UploadFile
from sqlalchemy import func, select

from pareeksha.api.auth import ReadKey, WriteKey
from pareeksha.api.crud import flush, get_or_404, paginate
from pareeksha.api.deps import AUTH_ERRORS, Blobs, Db, Pagination, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.routers.integrations import _secret_box
from pareeksha.audit.ingest import MAX_UPLOAD_BYTES
from pareeksha.db.models import KbDocuments, KnowledgeBases
from pareeksha.rag.extract import ExtractionError, extract_text
from pareeksha.schemas.common import Page
from pareeksha.schemas.rag import (
    KbDocumentDetail,
    KbDocumentOut,
    KbSecrets,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
)

router = APIRouter(tags=["knowledge-bases"], responses=AUTH_ERRORS)

MAX_DOCUMENTS = 200
MAX_CHARS = 2_000_000
EXTRACT_TIMEOUT_S = 30
_DUPLICATE = "A knowledge base with this name already exists"


def _out(row: KnowledgeBases) -> KnowledgeBaseOut:
    out = KnowledgeBaseOut.model_validate(row)
    out.has_secrets = bool(row.secrets_encrypted)
    return out


def _encrypt(secrets: KbSecrets | None) -> bytes | None:
    """Fernet token for the write-only keys; nothing (or ``{}``) clears them."""
    data = secrets.model_dump(exclude_none=True) if secrets else {}
    return _secret_box().encrypt(data).encode() if data else None


@router.post(
    "/knowledge-bases",
    status_code=201,
    responses=errors(409),
    summary="Create a knowledge base",
)
async def create_knowledge_base(
    body: KnowledgeBaseCreate, key: WriteKey, session: Db
) -> KnowledgeBaseOut:
    row = KnowledgeBases(
        project_id=key.project_id,
        name=body.name,
        description=body.description,
        local_only=body.local_only,
        secrets_encrypted=_encrypt(body.secrets),
    )
    session.add(row)
    await flush(session, _DUPLICATE, refresh=row)
    return _out(row)


@router.get("/knowledge-bases", summary="List knowledge bases")
async def list_knowledge_bases(
    key: ReadKey, session: Db, page: Pagination
) -> Page[KnowledgeBaseOut]:
    rows, next_cursor = await paginate(
        session, KnowledgeBases, [KnowledgeBases.project_id == key.project_id], page
    )
    return Page(items=[_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/knowledge-bases/{kb_id}", responses=errors(404), summary="Get a knowledge base")
async def get_knowledge_base(kb_id: UUID, key: ReadKey, session: Db) -> KnowledgeBaseOut:
    return _out(await get_or_404(session, KnowledgeBases, kb_id, key.project_id, "Knowledge base"))


@router.patch(
    "/knowledge-bases/{kb_id}", responses=errors(404, 409), summary="Update a knowledge base"
)
async def update_knowledge_base(
    kb_id: UUID, body: KnowledgeBaseUpdate, key: WriteKey, session: Db
) -> KnowledgeBaseOut:
    row = await get_or_404(session, KnowledgeBases, kb_id, key.project_id, "Knowledge base")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    if body.secrets is not None:
        row.secrets_encrypted = _encrypt(body.secrets)
    row.updated_at = datetime.now(UTC)
    await flush(session, _DUPLICATE)
    return _out(row)


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    status_code=201,
    responses=errors(404, 409, 413, 422),
    summary="Upload a document (txt, md, html, csv, json, pdf, docx; up to 10 MB)",
)
async def upload_document(
    kb_id: UUID,
    key: WriteKey,
    session: Db,
    blobs: Blobs,
    response: Response,
    file: Annotated[UploadFile, File(description="At most 10 MB")],
) -> KbDocumentOut:
    kb = await get_or_404(session, KnowledgeBases, kb_id, key.project_id, "Knowledge base")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiError(
            413, "file_too_large", "File is larger than 10 MB", {"max_bytes": MAX_UPLOAD_BYTES}
        )
    digest = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(
        select(KbDocuments).where(KbDocuments.kb_id == kb.id, KbDocuments.sha256 == digest)
    )
    if existing is not None and existing.deleted_at is None:
        response.status_code = 200
        return KbDocumentOut.model_validate(existing)

    filename = (file.filename or "document")[:200]
    if existing is not None:  # soft-deleted earlier: bring it back, no need to extract again
        mime, text = existing.mime, existing.text
    else:
        try:
            mime, text = await asyncio.wait_for(
                asyncio.to_thread(extract_text, filename, data), EXTRACT_TIMEOUT_S
            )
        except TimeoutError as exc:
            raise ApiError(422, "extraction_failed", "Extraction took too long") from exc
        except ExtractionError as exc:
            code = (
                "unsupported_document"
                if exc.code == "unsupported_document"
                else "extraction_failed"
            )
            raise ApiError(422, code, f"Could not read document: {exc.code}") from exc

    count, chars = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(KbDocuments.char_count), 0)).where(
                KbDocuments.kb_id == kb.id, KbDocuments.deleted_at.is_(None)
            )
        )
    ).one()
    if count >= MAX_DOCUMENTS or chars + len(text) > MAX_CHARS:
        raise ApiError(
            409,
            "kb_limit_reached",
            "Knowledge base is full",
            {"max_documents": MAX_DOCUMENTS, "max_chars": MAX_CHARS},
        )

    if existing is not None:
        row = existing
        row.deleted_at = None
        row.filename = filename
        row.created_at = datetime.now(UTC)
    else:
        row = KbDocuments(
            kb_id=kb.id,
            project_id=key.project_id,
            filename=filename,
            mime=mime,
            sha256=digest,
            text=text,
            char_count=len(text),
            blob_key=f"kb/{kb.id}/{digest}",
        )
        session.add(row)
    await flush(session, "Document already exists", refresh=row)
    await blobs.put(row.blob_key, data)
    return KbDocumentOut.model_validate(row)


@router.get("/knowledge-bases/{kb_id}/documents", responses=errors(404), summary="List documents")
async def list_documents(
    kb_id: UUID, key: ReadKey, session: Db, page: Pagination
) -> Page[KbDocumentOut]:
    await get_or_404(session, KnowledgeBases, kb_id, key.project_id, "Knowledge base")
    rows, next_cursor = await paginate(
        session,
        KbDocuments,
        [
            KbDocuments.kb_id == kb_id,
            KbDocuments.project_id == key.project_id,
            KbDocuments.deleted_at.is_(None),
        ],
        page,
    )
    return Page(items=[KbDocumentOut.model_validate(r) for r in rows], next_cursor=next_cursor)


async def _document(
    session: Db, kb_id: UUID, doc_id: UUID, project_id: UUID, include_deleted: bool = False
) -> KbDocuments:
    row = await get_or_404(session, KbDocuments, doc_id, project_id, "Document")
    if row.kb_id != kb_id or (row.deleted_at is not None and not include_deleted):
        raise ApiError(404, "not_found", "Document not found", {"id": str(doc_id)})
    return row  # type: ignore[no-any-return]


@router.get(
    "/knowledge-bases/{kb_id}/documents/{doc_id}",
    responses=errors(404),
    summary="Get a document with its extracted text",
)
async def get_document(kb_id: UUID, doc_id: UUID, key: ReadKey, session: Db) -> KbDocumentDetail:
    return KbDocumentDetail.model_validate(await _document(session, kb_id, doc_id, key.project_id))


@router.delete(
    "/knowledge-bases/{kb_id}/documents/{doc_id}",
    status_code=204,
    responses=errors(404),
    summary="Delete a document (soft delete; existing indexes keep their chunks)",
)
async def delete_document(kb_id: UUID, doc_id: UUID, key: WriteKey, session: Db) -> Response:
    row = await _document(session, kb_id, doc_id, key.project_id, include_deleted=True)
    if row.deleted_at is None:
        row.deleted_at = datetime.now(UTC)
    return Response(status_code=204)
