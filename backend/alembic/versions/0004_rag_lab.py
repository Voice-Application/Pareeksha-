"""RAG lab: knowledge bases, documents, indexes, chunks, retrievals, metrics, matrices, prices

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _id() -> sa.Column[sa.Uuid]:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _ts(name: str) -> sa.Column[sa.DateTime]:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _jsonb(name: str, default: str | None = None) -> sa.Column[postgresql.JSONB]:
    server_default = sa.text(f"'{default}'") if default else None
    return sa.Column(name, postgresql.JSONB(), server_default=server_default, nullable=False)


def _fk(col: str, target: str, table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], [f"{target}.id"], ondelete="CASCADE", name=f"{table}_{col}_fkey"
    )


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        _id(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("local_only", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("secrets_encrypted", sa.LargeBinary(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        _fk("project_id", "projects", "knowledge_bases"),
        sa.PrimaryKeyConstraint("id", name="knowledge_bases_pkey"),
        sa.UniqueConstraint("project_id", "name", name="knowledge_bases_project_id_name_key"),
    )
    op.create_table(
        "kb_documents",
        _id(),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("blob_key", sa.Text(), nullable=False),
        _ts("created_at"),
        _fk("kb_id", "knowledge_bases", "kb_documents"),
        _fk("project_id", "projects", "kb_documents"),
        sa.PrimaryKeyConstraint("id", name="kb_documents_pkey"),
        sa.UniqueConstraint("kb_id", "sha256", name="kb_documents_kb_id_sha256_key"),
    )
    op.create_table(
        "kb_indexes",
        _id(),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("index_key", sa.Text(), nullable=False),
        _jsonb("chunking"),
        _jsonb("embedding"),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        _jsonb("document_ids", "[]"),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _jsonb("stats", "{}"),
        _ts("created_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status = ANY (ARRAY['pending'::text, 'building'::text, "
            "'ready'::text, 'failed'::text])",
            name="kb_indexes_status_check",
        ),
        _fk("kb_id", "knowledge_bases", "kb_indexes"),
        _fk("project_id", "projects", "kb_indexes"),
        sa.PrimaryKeyConstraint("id", name="kb_indexes_pkey"),
        sa.UniqueConstraint("kb_id", "version", name="kb_indexes_kb_id_version_key"),
    )
    op.create_index("kb_indexes_kb_key_status_idx", "kb_indexes", ["kb_id", "index_key", "status"])
    op.create_table(
        "kb_chunks",
        _id(),
        sa.Column("index_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("parent_start", sa.Integer(), nullable=False),
        sa.Column("parent_end", sa.Integer(), nullable=False),
        sa.Column("text_sha", sa.Text(), nullable=False),
        sa.Column("embedding", sa.ARRAY(sa.REAL()), nullable=True),
        _fk("index_id", "kb_indexes", "kb_chunks"),
        _fk("document_id", "kb_documents", "kb_chunks"),
        sa.PrimaryKeyConstraint("id", name="kb_chunks_pkey"),
    )
    op.create_index("kb_chunks_index_id_idx", "kb_chunks", ["index_id"])
    op.create_index("kb_chunks_text_sha_idx", "kb_chunks", ["text_sha"])
    op.create_table(
        "retrievals",
        _id(),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("turn_idx", sa.Integer(), nullable=False),
        _jsonb("rag_config"),
        sa.Column("index_id", sa.Uuid(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        _jsonb("queries", "[]"),
        _jsonb("results", "[]"),
        sa.Column("context_chars", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _jsonb("timings", "{}"),
        _jsonb("usage", "{}"),
        _ts("created_at"),
        _fk("call_id", "calls", "retrievals"),
        sa.PrimaryKeyConstraint("id", name="retrievals_pkey"),
    )
    op.create_index("retrievals_call_id_idx", "retrievals", ["call_id"])
    op.create_table(
        "rag_metrics",
        sa.Column("call_id", sa.Uuid(), nullable=False),
        _jsonb("metrics", "{}"),
        _jsonb("skipped", "[]"),
        _ts("created_at"),
        _ts("updated_at"),
        _fk("call_id", "calls", "rag_metrics"),
        sa.PrimaryKeyConstraint("call_id", name="rag_metrics_pkey"),
    )
    op.create_table(
        "rag_matrices",
        _id(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version_id", sa.Uuid(), nullable=False),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        _jsonb("request"),
        _jsonb("entries", "[]"),
        _ts("created_at"),
        _fk("project_id", "projects", "rag_matrices"),
        _fk("agent_id", "agents", "rag_matrices"),
        _fk("prompt_version_id", "prompt_versions", "rag_matrices"),
        _fk("kb_id", "knowledge_bases", "rag_matrices"),
        sa.PrimaryKeyConstraint("id", name="rag_matrices_pkey"),
    )
    op.create_table(
        "price_overrides",
        _id(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_per_m_inr", sa.Numeric(), nullable=False),
        sa.Column("output_per_m_inr", sa.Numeric(), nullable=True),
        _ts("updated_at"),
        sa.CheckConstraint(
            "kind = ANY (ARRAY['llm'::text, 'embedding'::text, 'rerank'::text])",
            name="price_overrides_kind_check",
        ),
        _fk("project_id", "projects", "price_overrides"),
        sa.PrimaryKeyConstraint("id", name="price_overrides_pkey"),
        sa.UniqueConstraint(
            "project_id", "kind", "provider", "model", name="price_overrides_project_kind_key"
        ),
    )
    op.add_column("scenarios", sa.Column("rag_expectation", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("scenarios", "rag_expectation")
    for table in (
        "price_overrides",
        "rag_matrices",
        "rag_metrics",
        "retrievals",
        "kb_chunks",
        "kb_indexes",
        "kb_documents",
        "knowledge_bases",
    ):
        op.drop_table(table)
