"""Añadir constraints UNIQUE para upsert idempotente

- documentos: UNIQUE(empresa_id, doc_type)  → un solo registro por tipo de doc por empresa
- validaciones_cruzadas: UNIQUE(empresa_id) → una sola validación vigente por empresa

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_doc_empresa_type", "documentos", ["empresa_id", "doc_type"],
    )
    op.create_unique_constraint(
        "uq_vc_empresa", "validaciones_cruzadas", ["empresa_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_vc_empresa", "validaciones_cruzadas", type_="unique")
    op.drop_constraint("uq_doc_empresa_type", "documentos", type_="unique")
