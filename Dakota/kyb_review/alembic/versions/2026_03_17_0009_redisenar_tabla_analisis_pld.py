"""Rediseñar tabla analisis_pld: un registro por empresa, estructura tipo Colorado.

Drop-and-recreate: elimina los índices, constraints y tabla anterior,
y crea una nueva con la misma filosofía que validaciones_cruzadas
(un solo registro por empresa_id, detalle en JSONB).

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Eliminar tabla anterior ──────────────────────────────────
    op.drop_constraint("uq_analisis_pld_empresa_etapa", "analisis_pld", type_="unique")
    op.drop_index("ix_analisis_pld_etapa", table_name="analisis_pld")
    op.drop_index("ix_analisis_pld_rfc", table_name="analisis_pld")
    op.drop_index("ix_analisis_pld_empresa_id", table_name="analisis_pld")
    op.drop_table("analisis_pld")

    # ── Crear nueva tabla ────────────────────────────────────────
    op.create_table(
        "analisis_pld",
        # PK
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        # FK → empresas (una sola fila por empresa)
        sa.Column(
            "empresa_id", UUID(as_uuid=True),
            sa.ForeignKey("empresas.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Snapshot de identidad
        sa.Column("rfc", sa.String(13), nullable=False),
        sa.Column("razon_social", sa.Text(), nullable=False),
        # Dictamen final
        sa.Column(
            "dictamen", sa.String(40), nullable=False,
            comment="APROBADO | APROBADO_CON_OBSERVACIONES | RECHAZADO",
        ),
        # Contadores
        sa.Column("total_pasan", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_criticos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_altos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_medios", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_informativos", sa.Integer(), nullable=False, server_default="0"),
        # Detalle en JSONB (como Colorado)
        sa.Column("hallazgos", JSONB, nullable=False, server_default="[]"),
        sa.Column("recomendaciones", JSONB, nullable=False, server_default="[]"),
        sa.Column("documentos_presentes", JSONB, nullable=False, server_default="[]"),
        # Screening ejecutado
        sa.Column(
            "screening_ejecutado", sa.Boolean(),
            nullable=False, server_default="false",
        ),
        sa.Column(
            "screening_results", JSONB, nullable=True,
            comment="Resultado completo del screening contra listas negras",
        ),
        # Reporte completo en texto y resumen por bloques
        sa.Column(
            "reporte_texto", sa.Text(), nullable=True,
            comment="Reporte completo formateado en texto",
        ),
        sa.Column(
            "resumen_bloques", JSONB, nullable=True,
            server_default="{}",
            comment="Conteos agrupados por bloque: {1: {nombre, pasan, fallan, ...}}",
        ),
        # Timestamp
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    # ── Índices ──────────────────────────────────────────────────
    op.create_index("ix_analisis_pld_empresa_id", "analisis_pld", ["empresa_id"])
    op.create_index("ix_analisis_pld_rfc", "analisis_pld", ["rfc"])
    op.create_index("ix_analisis_pld_dictamen", "analisis_pld", ["dictamen"])
    op.create_index("ix_analisis_pld_created", "analisis_pld", ["created_at"])
    op.create_index(
        "ix_analisis_pld_hallazgos", "analisis_pld", ["hallazgos"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_table("analisis_pld")
