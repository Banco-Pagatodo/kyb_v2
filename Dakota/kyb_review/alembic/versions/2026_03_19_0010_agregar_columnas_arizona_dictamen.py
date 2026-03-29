"""Recrear tabla dictamenes_pld con columnas Arizona:
dictamen_json (JSONB) y dictamen_txt (TEXT) para almacenar
el dictamen completo generado por Arizona.

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Limpiar tabla anterior si existe (0007 pudo no haberse aplicado)
    op.execute("DROP TABLE IF EXISTS dictamenes_pld CASCADE")

    op.create_table(
        "dictamenes_pld",
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
            comment="APROBADO | APROBADO_CON_CONDICIONES | ESCALADO_A_COMITE | RECHAZADO",
        ),
        sa.Column(
            "nivel_riesgo_residual", sa.String(20), nullable=False,
            comment="BAJO | MEDIO | ALTO",
        ),
        sa.Column(
            "dictamen_json", JSONB, nullable=True,
            comment="Dictamen PLD/FT completo generado por Arizona (JSON)",
        ),
        sa.Column(
            "dictamen_txt", sa.Text(), nullable=True,
            comment="Dictamen PLD/FT formateado en texto plano",
        ),
        sa.Column(
            "agente", sa.Text(), nullable=False,
            server_default="Arizona v2.3",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index("ix_dictamenes_pld_empresa_id", "dictamenes_pld", ["empresa_id"])
    op.create_index("ix_dictamenes_pld_rfc", "dictamenes_pld", ["rfc"])
    op.create_index("ix_dictamenes_pld_dictamen", "dictamenes_pld", ["dictamen"])
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
