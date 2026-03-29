"""Eliminar columna texto_ocr de documentos

Revision ID: 0003
Revises: 0002
Create Date: 2026-02-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("documentos", "texto_ocr")


def downgrade() -> None:
    op.add_column("documentos", sa.Column("texto_ocr", sa.Text(), nullable=True))
