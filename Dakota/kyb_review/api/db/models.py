# api/db/models.py
# Modelos ORM — PostgreSQL con SQLAlchemy 2.0
#
# Esquema multi-tenant: todas las empresas comparten una sola BD.
# Los datos extraídos de cada documento se guardan como JSONB flexible.

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


# ---------------------------------------------------------------------------
# Base declarativa
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Base para todos los modelos ORM."""
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Tabla: empresas
# ---------------------------------------------------------------------------

class Empresa(Base):
    """
    Registro de cada empresa (tenant).
    El RFC es el identificador natural de negocio; el UUID es el PK técnico.
    """
    __tablename__ = "empresas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rfc: Mapped[str] = mapped_column(
        String(13), unique=True, nullable=False, index=True,
        comment="RFC de la empresa (12-13 caracteres)",
    )
    razon_social: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Razón social / nombre legal",
    )
    fecha_registro: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow,
    )
    metadata_extra: Mapped[dict | None] = mapped_column(
        JSONB, default=dict, server_default="{}",
        comment="Metadatos opcionales de la empresa",
    )

    # Relación 1→N con documentos
    documentos: Mapped[list["Documento"]] = relationship(
        back_populates="empresa",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Empresa rfc={self.rfc!r}>"


# ---------------------------------------------------------------------------
# Tabla: documentos
# ---------------------------------------------------------------------------

class Documento(Base):
    """
    Un documento procesado, vinculado a una empresa.
    Los campos extraídos se guardan en `datos_extraidos` (JSONB flexible).
    """
    __tablename__ = "documentos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    empresa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("empresas.id", ondelete="CASCADE"),
        nullable=False,
    )
    doc_type: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="Tipo de documento: csf, acta_constitutiva, poder, etc.",
    )
    file_name: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Nombre original del archivo subido",
    )

    # ----- Datos extraídos (flexible por tipo de documento) -----
    datos_extraidos: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}",
        comment="Campos extraídos del documento (estructura varía por doc_type)",
    )

    # ----- Auditoría -----
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow,
    )

    # Relación N→1 con empresa
    empresa: Mapped["Empresa"] = relationship(back_populates="documentos")

    __table_args__ = (
        UniqueConstraint("empresa_id", "doc_type", name="uq_doc_empresa_type"),
        Index("idx_doc_empresa", "empresa_id"),
        Index("idx_doc_type", "doc_type"),
        Index("idx_doc_datos", "datos_extraidos", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return (
            f"<Documento type={self.doc_type!r} "
            f"empresa_id={self.empresa_id!r}>"
        )
