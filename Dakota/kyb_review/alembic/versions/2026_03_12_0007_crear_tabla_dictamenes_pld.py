"""Crear tabla dictamenes_pld para persistir resultados de Nevada

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-12

Tabla de salida del agente Nevada (Oficial de Cumplimiento PLD/FT).
Almacena el dictamen completo: scoring determinista MER v7.0,
narrativa LLM + RAG, condiciones, acciones de seguimiento y
fundamento legal.  UPSERT por (empresa_id) → un dictamen vigente
por empresa.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Eliminar tabla vieja si existe (creada por Nevada inline con SERIAL PK
    # y empresa_id TEXT — incompatible con el esquema formal).
    op.execute("DROP TABLE IF EXISTS dictamenes_pld CASCADE")

    op.create_table(
        "dictamenes_pld",
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
        # ── Dictamen ─────────────────────────────────────────────
        sa.Column(
            "dictamen", sa.String(40), nullable=False,
            comment="APROBADO | APROBADO_CON_CONDICIONES | ESCALADO_A_COMITE | RECHAZADO | SUSPENDIDO",
        ),
        sa.Column(
            "nivel_riesgo_residual", sa.String(20), nullable=False,
            comment="BAJO | MEDIO | ALTO",
        ),
        sa.Column(
            "riesgo_residual", sa.Numeric(8, 4), nullable=True,
            comment="Score numérico 0.00-4.00 del riesgo residual MER",
        ),
        # ── Narrativa LLM ────────────────────────────────────────
        sa.Column(
            "justificacion", sa.Text(), nullable=True,
            comment="Texto generado por LLM + RAG con referencia a la MER",
        ),
        sa.Column(
            "condiciones", JSONB, nullable=False, server_default="[]",
            comment="Condiciones específicas si dictamen = APROBADO_CON_CONDICIONES",
        ),
        sa.Column(
            "acciones_seguimiento", JSONB, nullable=False, server_default="[]",
            comment="Acciones requeridas: EDD, monitoreo, etc.",
        ),
        sa.Column(
            "fundamento_legal", JSONB, nullable=False, server_default="[]",
            comment="Artículos / disposiciones citadas en el dictamen",
        ),
        # ── Score completo (snapshot) ────────────────────────────
        sa.Column(
            "score_completo", JSONB, nullable=True,
            comment="ScoreResult serializado: indicadores, inherente, mitigantes, residual",
        ),
        # ── Trazabilidad ─────────────────────────────────────────
        sa.Column(
            "hash_dictamen", sa.String(64), nullable=True,
            comment="SHA-256 del dictamen para integridad / auditoría",
        ),
        sa.Column(
            "agente", sa.Text(), nullable=False,
            server_default="Nevada v1.0.0",
            comment="Versión del agente que generó el dictamen",
        ),
        sa.Column(
            "mer_version", sa.String(10), nullable=False,
            server_default="7.0",
            comment="Versión de la MER usada para el scoring",
        ),
        # ── Timestamps ───────────────────────────────────────────
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Índices
    op.create_index("ix_dictamenes_pld_empresa_id", "dictamenes_pld", ["empresa_id"])
    op.create_index("ix_dictamenes_pld_rfc", "dictamenes_pld", ["rfc"])
    op.create_index("ix_dictamenes_pld_dictamen", "dictamenes_pld", ["dictamen"])

    # Un dictamen vigente por empresa (UPSERT target)
    op.create_unique_constraint(
        "uq_dictamenes_pld_empresa",
        "dictamenes_pld",
        ["empresa_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_dictamenes_pld_empresa", "dictamenes_pld")
    op.drop_index("ix_dictamenes_pld_dictamen", "dictamenes_pld")
    op.drop_index("ix_dictamenes_pld_rfc", "dictamenes_pld")
    op.drop_index("ix_dictamenes_pld_empresa_id", "dictamenes_pld")
    op.drop_table("dictamenes_pld")
