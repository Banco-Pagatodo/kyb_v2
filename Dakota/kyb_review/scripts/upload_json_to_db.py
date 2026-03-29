"""
Script para insertar/actualizar JSONs de Actas Constitutivas y Reformas de Estatutos
en la base de datos PostgreSQL de kyb_review.

Uso:
    cd Dakota/kyb_review
    python scripts/upload_json_to_db.py

Actualiza documentos existentes (mismo rfc + doc_type) o inserta nuevos.
"""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime

# Ajustar path para importar módulos del proyecto
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path="api/service/.env")

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.session import init_db, get_db
from api.db.models import Empresa, Documento

# ─── Configuración ───────────────────────────────────────────────────────

JSON_DIR = Path("temp/json")

# Mapeo: archivo JSON → (RFC, doc_type, file_name original)
DOCUMENTS = [
    # Actas Constitutivas
    {
        "json_file": "acta_07__Acta_Constitutiva_Capital_X.json",
        "rfc": "SCX190531824",
        "doc_type": "acta_constitutiva",
        "file_name": "07. Acta Constitutiva Capital X.pdf",
    },
    {
        "json_file": "acta_07__Acta_Constitutiva_Almirante_Capital.json",
        "rfc": "ACA230223IA7",
        "doc_type": "acta_constitutiva",
        "file_name": "07. Acta Constitutiva Almirante Capital.pdf",
    },
    {
        "json_file": "acta_07__Acta_Constitutiva_Arenosos_Opciones_en_construcción.json",
        "rfc": "AOC1502098V7",
        "doc_type": "acta_constitutiva",
        "file_name": "07. Acta Constitutiva Arenosos Opciones en construcción.pdf",
    },
    {
        "json_file": "acta_07__Acta_Constitutiva_Avanza_Solido.json",
        "rfc": "ASO110413438",
        "doc_type": "acta_constitutiva",
        "file_name": "07. Acta Constitutiva Avanza Solido.pdf",
    },
    # Reformas de Estatutos
    {
        "json_file": "reforma_08__Ultima_Reforma_de_Estatutos.json",
        "rfc": "ASO110413438",  # Avanza Sólido
        "doc_type": "reforma_estatutos",
        "file_name": "08. Ultima Reforma de Estatutos.pdf",
    },
    {
        "json_file": "reforma_08__Ultima_Reforma_de_Estatutos_1.json",
        "rfc": "SCX190531824",  # Capital X
        "doc_type": "reforma_estatutos",
        "file_name": "08. Ultima Reforma de Estatutos 1.pdf",
    },
]


async def upload_all():
    """Carga todos los JSONs definidos en DOCUMENTS a la BD."""
    await init_db()

    async for session in get_db():
        for doc_info in DOCUMENTS:
            json_path = JSON_DIR / doc_info["json_file"]

            if not json_path.exists():
                print(f"  ⚠  SKIP: {doc_info['json_file']} no encontrado")
                continue

            # Cargar JSON
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Extraer datos_extraidos (puede venir como campo o ser el root)
            datos = data.get("datos_extraidos", data)

            rfc = doc_info["rfc"]
            doc_type = doc_info["doc_type"]
            file_name = doc_info["file_name"]

            # Buscar empresa
            stmt = select(Empresa).where(Empresa.rfc == rfc)
            result = await session.execute(stmt)
            empresa = result.scalar_one_or_none()

            if not empresa:
                print(f"  ⚠  Empresa RFC={rfc} no encontrada, creando...")
                razon = datos.get("denominacion_social", {})
                razon_social = razon.get("valor", f"Empresa {rfc}") if isinstance(razon, dict) else str(razon) or f"Empresa {rfc}"
                empresa = Empresa(rfc=rfc, razon_social=razon_social)
                session.add(empresa)
                await session.flush()

            # Buscar documento existente (mismo empresa + doc_type)
            stmt_doc = (
                select(Documento)
                .where(Documento.empresa_id == empresa.id)
                .where(Documento.doc_type == doc_type)
            )
            result_doc = await session.execute(stmt_doc)
            existing_doc = result_doc.scalar_one_or_none()

            if existing_doc:
                # Actualizar
                existing_doc.datos_extraidos = datos
                existing_doc.file_name = file_name
                action = "UPDATED"
            else:
                # Insertar
                new_doc = Documento(
                    empresa_id=empresa.id,
                    doc_type=doc_type,
                    file_name=file_name,
                    datos_extraidos=datos,
                )
                session.add(new_doc)
                action = "INSERTED"

            print(f"  ✓  {action}: {doc_type} → {rfc} ({file_name})")

        await session.commit()
        print(f"\n{'='*60}")
        print(f"  Completado: {len(DOCUMENTS)} documentos procesados")
        print(f"{'='*60}")
        break  # Solo necesitamos una iteración del generator


if __name__ == "__main__":
    print(f"\n{'='*60}")
    print(f"  Upload JSON → PostgreSQL (kyb)")
    print(f"{'='*60}\n")
    asyncio.run(upload_all())
