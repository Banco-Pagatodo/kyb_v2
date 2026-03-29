"""Simplificar esquema: solo doc_type, file_name, texto_ocr, datos_extraidos

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Tabla empresas: quitar status_kyb y su constraint ──
    op.drop_constraint("ck_empresa_status", "empresas", type_="check")
    op.drop_column("empresas", "status_kyb")

    # ── Tabla documentos: quitar columnas e índices sobrantes ──
    # Primero índices que referencian columnas a eliminar
    op.drop_index("idx_doc_verdict", table_name="documentos")
    op.drop_index("idx_doc_hash", table_name="documentos")

    # Columnas a eliminar
    op.drop_column("documentos", "verdict")
    op.drop_column("documentos", "compliance_score")
    op.drop_column("documentos", "kyb_compliance")
    op.drop_column("documentos", "errores")
    op.drop_column("documentos", "document_identification")
    op.drop_column("documentos", "is_correct")
    op.drop_column("documentos", "confidence")
    op.drop_column("documentos", "file_hash")
    op.drop_column("documentos", "blob_url")
    op.drop_column("documentos", "processing_time_ms")


def downgrade() -> None:
    # ── Restaurar columnas de documentos ──
    op.add_column("documentos", sa.Column("processing_time_ms", sa.Integer(), nullable=True))
    op.add_column("documentos", sa.Column("blob_url", sa.Text(), nullable=True))
    op.add_column("documentos", sa.Column("file_hash", sa.String(64), nullable=True))
    op.add_column("documentos", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("documentos", sa.Column("is_correct", sa.Boolean(), nullable=True))
    op.add_column("documentos", sa.Column("document_identification", sa.dialects.postgresql.JSONB(), nullable=True))
    op.add_column("documentos", sa.Column("errores", sa.dialects.postgresql.JSONB(), server_default="[]", nullable=True))
    op.add_column("documentos", sa.Column("kyb_compliance", sa.dialects.postgresql.JSONB(), nullable=True))
    op.add_column("documentos", sa.Column("compliance_score", sa.Float(), nullable=True))
    op.add_column("documentos", sa.Column("verdict", sa.String(25), nullable=True))

    op.create_index("idx_doc_hash", "documentos", ["file_hash"])
    op.create_index("idx_doc_verdict", "documentos", ["verdict"])

    # ── Restaurar status_kyb en empresas ──
    op.add_column("empresas", sa.Column("status_kyb", sa.String(20), nullable=False, server_default="PENDIENTE"))
    op.create_check_constraint(
        "ck_empresa_status", "empresas",
        "status_kyb IN ('PENDIENTE','APROBADO','REVISION','RECHAZADO')"
    )
