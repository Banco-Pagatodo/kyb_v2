"""Crear tabla analisis_pld para persistir resultados de Arizona

Revision ID: 0006
Revises: 0005
Create Date: 2026-02-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analisis_pld",
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
        # Etapa del análisis PLD
        sa.Column(
            "etapa", sa.String(30), nullable=False,
            comment="ETAPA_1_COMPLETITUD | ETAPA_2_SCREENING | ETAPA_3_VERIFICACION | etc.",
        ),
        # Resultado de la etapa
        sa.Column(
            "resultado", sa.String(30), nullable=False,
            comment="COMPLETO | PARCIAL | INCOMPLETO (Etapa 1) | OK | ALERTA | COINCIDENCIA (Etapa 2)",
        ),
        # Porcentaje de completitud (Etapa 1)
        sa.Column(
            "porcentaje_completitud", sa.Float(), nullable=True,
            comment="% de items presentes sobre total (solo Etapa 1)",
        ),
        sa.Column("items_presentes", sa.Integer(), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=True),
        sa.Column("items_criticos_faltantes", sa.Integer(), nullable=True),
        # Detalle en JSONB
        sa.Column(
            "items", JSONB, nullable=False, server_default="[]",
            comment="Lista de ItemCompletitud verificados",
        ),
        sa.Column(
            "personas_identificadas", JSONB, nullable=False, server_default="[]",
            comment="Lista de personas encontradas en expediente",
        ),
        sa.Column("documentos_presentes", JSONB, nullable=False, server_default="[]"),
        sa.Column("documentos_faltantes", JSONB, nullable=False, server_default="[]"),
        sa.Column("recomendaciones", JSONB, nullable=False, server_default="[]"),
        # Screening (Etapa 2)
        sa.Column(
            "screening_results", JSONB, nullable=True,
            comment="Resultados de búsqueda en listas negras/PEPs",
        ),
        # Referencia a Colorado
        sa.Column("dictamen_colorado", sa.String(50), nullable=True),
        sa.Column("hallazgos_colorado_criticos", JSONB, nullable=True),
        sa.Column("resumen_colorado", JSONB, nullable=True),
        # Flag poder cuenta bancaria
        sa.Column(
            "poder_cuenta_bancaria", sa.Boolean(), nullable=True,
            comment="True si se detectó poder para operar cuentas bancarias",
        ),
        # Timestamps
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=True, onupdate=sa.text("NOW()"),
        ),
    )
    
    # Índices para queries frecuentes
    op.create_index(
        "ix_analisis_pld_empresa_id",
        "analisis_pld", ["empresa_id"],
    )
    op.create_index(
        "ix_analisis_pld_rfc",
        "analisis_pld", ["rfc"],
    )
    op.create_index(
        "ix_analisis_pld_etapa",
        "analisis_pld", ["etapa"],
    )
    # Constraint único para evitar duplicados por empresa/etapa
    op.create_unique_constraint(
        "uq_analisis_pld_empresa_etapa",
        "analisis_pld", ["empresa_id", "etapa"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_analisis_pld_empresa_etapa", "analisis_pld")
    op.drop_index("ix_analisis_pld_etapa", "analisis_pld")
    op.drop_index("ix_analisis_pld_rfc", "analisis_pld")
    op.drop_index("ix_analisis_pld_empresa_id", "analisis_pld")
    op.drop_table("analisis_pld")
