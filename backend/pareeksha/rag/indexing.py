"""Build one knowledge-base index (plans/2026-11-07-rag-lab.md, Task 5).

Idempotent: only a ``pending`` row is built. Vectors are reused from any READY index of the same KB
with the same embedding config and chunk text, so a rebuild with a new chunking only pays for the
chunks it has not seen.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from pareeksha.agent_llm.base import AgentLLMError
from pareeksha.events.topics import MAX_ATTEMPTS
from pareeksha.integrations.crypto import SecretBox
from pareeksha.rag.chunking import chunk_document
from pareeksha.rag.embeddings import Embedder, build_embedder
from pareeksha.rag.guard import LocalOnlyError, require_local_embedding
from pareeksha.schemas.rag import ChunkingConfig, EmbeddingConfig

log = logging.getLogger(__name__)
MAX_ERROR_CHARS = 500
INSERT_BATCH = 500

EmbedderFor = Callable[[EmbeddingConfig, str | None], Embedder]


def default_embedder_for(cfg: EmbeddingConfig, api_key: str | None) -> Embedder:
    return build_embedder(cfg, api_key=api_key)


def _api_key(blob: Any) -> str | None:
    if not blob:
        return None
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        raise ValueError("SECRET_KEY is not configured")
    return SecretBox(secret).decrypt(bytes(blob).decode()).get("embedding_api_key")


async def _fail(
    conn: psycopg.AsyncConnection[Any], index_id: uuid.UUID, error: str, api_key: str | None
) -> None:
    if api_key:  # belt and braces: provider errors are already key-free
        error = error.replace(api_key, "***")
    await conn.execute(
        "UPDATE kb_indexes SET status = 'failed', error = %s, finished_at = now() WHERE id = %s",
        (error[:MAX_ERROR_CHARS], index_id),
    )


async def build_index(
    conn: psycopg.AsyncConnection[Any],
    index_id: uuid.UUID,
    *,
    embedder_for: EmbedderFor = default_embedder_for,
    attempt: int = 1,
) -> None:
    cur = await conn.execute(
        "SELECT status, kb_id, chunking, embedding, document_ids FROM kb_indexes "
        "WHERE id = %s FOR UPDATE",
        (index_id,),
    )
    row = await cur.fetchone()
    if row is None or row[0] != "pending":  # gone, or a redelivered request already handled
        return
    _, kb_id, chunking_raw, embedding_raw, document_ids = row
    cur = await conn.execute(
        "SELECT local_only, secrets_encrypted FROM knowledge_bases WHERE id = %s", (kb_id,)
    )
    kb = await cur.fetchone()
    # fail closed: a KB (or flag) that cannot be read is treated as local-only
    local_only = kb is None or kb[0] is None or bool(kb[0])
    secrets = None if kb is None else kb[1]
    api_key: str | None = None
    try:
        # a savepoint: after a SQL error the transaction stays usable for the ``failed`` update
        async with conn.transaction():
            embedding = EmbeddingConfig.model_validate(embedding_raw)
            require_local_embedding(local_only, embedding)
            api_key = _api_key(secrets)
            await conn.execute(
                "UPDATE kb_indexes SET status = 'building' WHERE id = %s", (index_id,)
            )
            stats = await _build(
                conn,
                index_id,
                kb_id,
                ChunkingConfig.model_validate(chunking_raw),
                embedder_for(embedding, api_key),
                [uuid.UUID(d) for d in document_ids],
                embedding_raw,
            )
    except LocalOnlyError as exc:
        await _fail(conn, index_id, str(exc), api_key)
        return
    except (AgentLLMError, TimeoutError, OSError, psycopg.OperationalError) as exc:
        if attempt < MAX_ATTEMPTS and (
            not isinstance(exc, AgentLLMError) or exc.retryable
        ):  # transient: rolls back to pending and the framework retries
            raise
        await _fail(conn, index_id, f"embedding failed: {exc}", api_key)
        return
    except Exception as exc:  # bad config, unreadable secrets, a bug: retrying cannot help
        # every path ends ready or failed, never left ``pending`` for the DLQ to forget
        log.warning("index %s build failed: %s", index_id, type(exc).__name__)
        await _fail(conn, index_id, f"index build failed: {exc or type(exc).__name__}", api_key)
        return
    await conn.execute(
        "UPDATE kb_indexes SET status = 'ready', chunk_count = %s, stats = %s, error = NULL, "
        "finished_at = now() WHERE id = %s",
        (stats["chunks"], Jsonb(stats), index_id),
    )


async def _build(
    conn: psycopg.AsyncConnection[Any],
    index_id: uuid.UUID,
    kb_id: uuid.UUID,
    chunking: ChunkingConfig,
    embedder: Embedder,
    document_ids: list[uuid.UUID],
    embedding_raw: dict[str, Any],
) -> dict[str, Any]:
    cur = await conn.execute(
        "SELECT id, text FROM kb_documents WHERE id = ANY(%s)", (document_ids,)
    )
    texts = dict(await cur.fetchall())
    chunks: list[tuple[uuid.UUID, Any, str]] = []  # (document_id, Chunk, sha)
    for doc_id in document_ids:
        for chunk in chunk_document(texts.get(doc_id, ""), chunking):
            sha = hashlib.sha256(chunk.text.encode()).hexdigest()
            chunks.append((doc_id, chunk, sha))

    shas = sorted({sha for _, _, sha in chunks})
    cur = await conn.execute(
        "SELECT DISTINCT ON (c.text_sha) c.text_sha, c.embedding FROM kb_chunks c "
        "JOIN kb_indexes i ON i.id = c.index_id "
        "WHERE i.kb_id = %s AND i.status = 'ready' AND i.embedding = %s "
        "AND c.text_sha = ANY(%s) AND c.embedding IS NOT NULL",
        (kb_id, Jsonb(embedding_raw), shas),
    )
    vectors: dict[str, list[float]] = dict(await cur.fetchall())
    reused = sum(1 for _, _, sha in chunks if sha in vectors)

    to_embed: dict[str, str] = {}
    for _, chunk, sha in chunks:
        if sha not in vectors:
            to_embed.setdefault(sha, chunk.text)
    embed_ms = input_tokens = 0
    if to_embed:
        res = await embedder.embed(list(to_embed.values()), kind="document")
        if len(res.vectors) != len(to_embed):
            raise ValueError("embedding provider returned the wrong number of vectors")
        vectors.update(zip(to_embed, res.vectors, strict=True))
        embed_ms, input_tokens = res.latency_ms, res.input_tokens

    rows = [
        (
            uuid.uuid4(),
            index_id,
            doc_id,
            ordinal,
            c.text,
            c.start,
            c.end,
            c.parent_start,
            c.parent_end,
            sha,
            vectors[sha],
        )
        for ordinal, (doc_id, c, sha) in enumerate(chunks)
    ]
    sql = (
        "INSERT INTO kb_chunks (id, index_id, document_id, ordinal, text, start_char, end_char, "
        "parent_start, parent_end, text_sha, embedding) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    async with conn.cursor() as ins:
        for i in range(0, len(rows), INSERT_BATCH):
            await ins.executemany(sql, rows[i : i + INSERT_BATCH])
    return {
        "documents": len(document_ids),
        "chunks": len(chunks),
        "embedded": len(chunks) - reused,
        "reused": reused,
        "embed_ms": embed_ms,
        "input_tokens": input_tokens,
    }
