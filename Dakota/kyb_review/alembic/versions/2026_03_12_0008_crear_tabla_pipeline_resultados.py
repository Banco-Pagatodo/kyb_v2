"""Crear tabla pipeline_resultados para estado unificado del pipeline KYB

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-12

Tabla centralizada que consolida el estado end-to-end de cada empresa
a través de los 4 agentes (Dakota → Colorado → Arizona → Nevada).
El Orquestador o cualquier agente puede leerla para obtener un resumen
rápido del progreso del expediente.

Cada agente actualiza sus columnas al finalizar:
  - Dakota  → dakota_status, dakota_ts
  - Colorado → colorado_status, colorado_dictamen, colorado_ts
  - Arizona  → arizona_status, arizona_resultado, arizona_ts
  - Nevada   → nevada_status, nevada_dictamen, nevada_ts
  - Orquestador → pipeline_status, completed_at
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_resultados",
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
        # Snapshot de identidad
        sa.Column("rfc", sa.String(13), nullable=False),
        sa.Column("razon_social", sa.Text(), nullable=False),

        # ── Estado global del pipeline ───────────────────────────
        sa.Column(
            "pipeline_status", sa.String(30), nullable=False,
            server_default="EN_PROCESO",
            comment="EN_PROCESO | COMPLETADO | ERROR | PARCIAL",
        ),

        # ── Dakota (Extracción) ──────────────────────────────────
        sa.Column(
            "dakota_status", sa.String(30), nullable=True,
            comment="COMPLETADO | ERROR | PENDIENTE",
        ),
        sa.Column(
            "documentos_extraidos", sa.Integer(), nullable=True,
            comment="Cantidad de documentos procesados por Dakota",
        ),
        sa.Column(
            "tipos_documentos", JSONB, nullable=True,
            comment="Lista de doc_types procesados [csf, acta_constitutiva, ...]",
        ),
        sa.Column("dakota_ts", sa.DateTime(timezone=True), nullable=True),

        # ── Colorado (Validación cruzada) ────────────────────────
        sa.Column(
            "colorado_status", sa.String(30), nullable=True,
            comment="COMPLETADO | ERROR | PENDIENTE | OMITIDO",
        ),
        sa.Column(
            "colorado_dictamen", sa.String(40), nullable=True,
            comment="APROBADO | APROBADO_CON_OBSERVACIONES | RECHAZADO",
        ),
        sa.Column("colorado_hallazgos", sa.Integer(), nullable=True),
        sa.Column("colorado_criticos", sa.Integer(), nullable=True),
        sa.Column("colorado_ts", sa.DateTime(timezone=True), nullable=True),

        # ── Arizona (PLD/AML) ────────────────────────────────────
        sa.Column(
            "arizona_status", sa.String(30), nullable=True,
            comment="COMPLETADO | ERROR | PENDIENTE",
        ),
        sa.Column(
            "arizona_resultado", sa.String(30), nullable=True,
            comment="COMPLETO | PARCIAL | INCOMPLETO",
        ),
        sa.Column("arizona_completitud_pct", sa.Float(), nullable=True),
        sa.Column(
            "arizona_screening", sa.String(40), nullable=True,
            comment="SIN_COINCIDENCIAS | COINCIDENCIA_PROBABLE | COINCIDENCIA_CRITICA | ...",
        ),
        sa.Column("arizona_ts", sa.DateTime(timezone=True), nullable=True),

        # ── Nevada (Dictamen PLD/FT) ─────────────────────────────
        sa.Column(
            "nevada_status", sa.String(30), nullable=True,
            comment="COMPLETADO | ERROR | PENDIENTE",
        ),
        sa.Column(
            "nevada_dictamen", sa.String(40), nullable=True,
            comment="APROBADO | APROBADO_CON_CONDICIONES | ESCALADO_A_COMITE | RECHAZADO",
        ),
        sa.Column(
            "nevada_nivel_riesgo", sa.String(20), nullable=True,
            comment="BAJO | MEDIO | ALTO",
        ),
        sa.Column("nevada_riesgo_residual", sa.Numeric(8, 4), nullable=True),
        sa.Column("nevada_ts", sa.DateTime(timezone=True), nullable=True),

        # ── Resumen de tiempos ───────────────────────────────────
        sa.Column(
            "tiempos_ms", JSONB, nullable=True,
            comment='{"dakota_ms": ..., "colorado_ms": ..., "arizona_ms": ..., "nevada_ms": ..., "total_ms": ...}',
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
        sa.Column(
            "completed_at", sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp de finalización del pipeline completo",
        ),
    )

    # Índices
    op.create_index("ix_pipeline_resultados_empresa_id", "pipeline_resultados", ["empresa_id"])
    op.create_index("ix_pipeline_resultados_rfc", "pipeline_resultados", ["rfc"])
    op.create_index("ix_pipeline_resultados_status", "pipeline_resultados", ["pipeline_status"])

    # Un resultado por empresa (UPSERT target)
    op.create_unique_constraint(
        "uq_pipeline_resultados_empresa",
        "pipeline_resultados",
        ["empresa_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_pipeline_resultados_empresa", "pipeline_resultados")
    op.drop_index("ix_pipeline_resultados_status", "pipeline_resultados")
    op.drop_index("ix_pipeline_resultados_rfc", "pipeline_resultados")
    op.drop_index("ix_pipeline_resultados_empresa_id", "pipeline_resultados")
    op.drop_table("pipeline_resultados")
