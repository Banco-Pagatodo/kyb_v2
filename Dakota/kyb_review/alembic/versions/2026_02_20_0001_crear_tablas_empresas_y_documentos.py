"""Crear tablas empresas y documentos

Revision ID: 0001
Revises: None
Create Date: 2026-02-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Extensiones de PostgreSQL ---
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')

    # --- Tabla: empresas ---
    op.create_table(
        "empresas",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("rfc", sa.String(13), nullable=False, unique=True),
        sa.Column("razon_social", sa.Text(), nullable=False),
        sa.Column("status_kyb", sa.String(20), nullable=False, server_default="PENDIENTE"),
        sa.Column("fecha_registro", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("metadata_extra", JSONB, server_default="{}"),
        sa.CheckConstraint(
            "status_kyb IN ('PENDIENTE','APROBADO','REVISION','RECHAZADO')",
            name="ck_empresa_status",
        ),
    )
    op.create_index("idx_empresa_rfc", "empresas", ["rfc"])
    op.create_index("idx_empresa_status", "empresas", ["status_kyb"])
    op.create_index(
        "idx_empresa_trgm", "empresas", ["razon_social"],
        postgresql_using="gin",
        postgresql_ops={"razon_social": "gin_trgm_ops"},
    )

    # --- Tabla: documentos ---
    op.create_table(
        "documentos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("empresa_id", UUID(as_uuid=True), sa.ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("doc_type", sa.String(30), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("blob_url", sa.Text(), nullable=True),
        sa.Column("datos_extraidos", JSONB, nullable=False, server_default="{}"),
        sa.Column("document_identification", JSONB, nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("compliance_score", sa.Float(), nullable=True),
        sa.Column("verdict", sa.String(25), nullable=True),
        sa.Column("kyb_compliance", JSONB, nullable=True),
        sa.Column("errores", JSONB, server_default="[]"),
        sa.Column("texto_ocr", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
    )
    op.create_index("idx_doc_empresa", "documentos", ["empresa_id"])
    op.create_index("idx_doc_type", "documentos", ["doc_type"])
    op.create_index("idx_doc_verdict", "documentos", ["verdict"])
    op.create_index("idx_doc_hash", "documentos", ["file_hash"])
    op.create_index(
        "idx_doc_datos", "documentos", ["datos_extraidos"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_table("documentos")
    op.drop_table("empresas")
