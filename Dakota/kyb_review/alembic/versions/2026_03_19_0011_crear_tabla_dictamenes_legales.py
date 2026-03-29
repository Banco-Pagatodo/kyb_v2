"""Crear tabla dictamenes_legales para persistir resultados de Nevada (Dictamen Jurídico)

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-19

Tabla de salida del agente Nevada (Dictamen Jurídico Legal).
Persiste el dictamen DJ-1 generado para cada empresa.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dictamenes_legales",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "empresa_id", UUID(as_uuid=True),
            sa.ForeignKey("empresas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rfc", sa.String(13), nullable=False),
        sa.Column("razon_social", sa.Text(), nullable=False),
        sa.Column(
            "dictamen", sa.String(40), nullable=False,
            comment="FAVORABLE | FAVORABLE_CON_CONDICIONES | NO_FAVORABLE",
        ),
        sa.Column("fundamento_legal", sa.Text(), nullable=True),
        sa.Column(
            "dictamen_json", JSONB, nullable=False,
            comment="Dictamen completo estructurado (DJ-1)",
        ),
        sa.Column(
            "dictamen_texto", sa.Text(), nullable=True,
            comment="Versión texto plano del dictamen",
        ),
        sa.Column(
            "datos_expediente", JSONB, nullable=True,
            comment="Snapshot de datos leídos de la BD",
        ),
        sa.Column(
            "reglas_aplicadas", JSONB, nullable=True,
            comment="Resultado de evaluar cada regla del dictamen",
        ),
        sa.Column(
            "version", sa.String(20), nullable=True,
            server_default="Nevada v1.0.0",
        ),
        sa.Column(
            "generado_por", sa.String(50), nullable=True,
            server_default="legal_agent",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
    )

    op.create_index(
        "idx_dictamenes_legales_empresa",
        "dictamenes_legales",
        ["empresa_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_dictamenes_legales_empresa")
    op.drop_table("dictamenes_legales")
