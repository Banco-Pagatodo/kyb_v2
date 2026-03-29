"""Crear tabla validaciones_cruzadas para persistir reportes de Colorado

Revision ID: 0004
Revises: 0003
Create Date: 2026-02-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "validaciones_cruzadas",
        # PK
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        # FK → empresas
        sa.Column(
            "empresa_id", UUID(as_uuid=True),
            sa.ForeignKey("empresas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Snapshot de identidad (útil para queries sin JOIN)
        sa.Column("rfc", sa.String(13), nullable=False),
        sa.Column("razon_social", sa.Text(), nullable=False),
        # Resultado
        sa.Column(
            "dictamen", sa.String(30), nullable=False,
            comment="APROBADO | APROBADO_CON_OBSERVACIONES | RECHAZADO",
        ),
        sa.Column("total_pasan", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_criticos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_medios", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_informativos", sa.Integer(), nullable=False, server_default="0"),
        # Detalle completo en JSONB (hallazgos, recomendaciones, docs presentes)
        sa.Column("hallazgos", JSONB, nullable=False, server_default="[]"),
        sa.Column("recomendaciones", JSONB, nullable=False, server_default="[]"),
        sa.Column("documentos_presentes", JSONB, nullable=False, server_default="[]"),
        # Flags para saber qué se ejecutó
        sa.Column(
            "portales_ejecutados", sa.Boolean(),
            nullable=False, server_default="false",
        ),
        sa.Column(
            "modulos_portales", JSONB, nullable=True,
            comment='["fiel","rfc","ine"] o null si no se ejecutaron portales',
        ),
        # Reporte completo en texto y resumen estructurado por bloques
        sa.Column(
            "reporte_texto", sa.Text(), nullable=True,
            comment="Reporte completo formateado (tal como se ve en CLI)",
        ),
        sa.Column(
            "resumen_bloques", JSONB, nullable=True,
            server_default="{}",
            comment="Conteos agrupados por bloque: {1: {nombre, pasan, fallan, ...}}",
        ),
        # Timestamps
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    # Índices
    op.create_index(
        "idx_vc_empresa", "validaciones_cruzadas", ["empresa_id"],
    )
    op.create_index(
        "idx_vc_rfc", "validaciones_cruzadas", ["rfc"],
    )
    op.create_index(
        "idx_vc_dictamen", "validaciones_cruzadas", ["dictamen"],
    )
    op.create_index(
        "idx_vc_created", "validaciones_cruzadas", ["created_at"],
    )
    # GIN en hallazgos para queries JSONB
    op.create_index(
        "idx_vc_hallazgos", "validaciones_cruzadas", ["hallazgos"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_table("validaciones_cruzadas")
