"""
Script para copiar modelos custom INE_Front e INE_Back
del recurso DI original al nuevo recurso DI (kyb-document-intelligence-qa).

Uso:
    python scripts/copy_ine_models.py
"""
import os
import time
import logging
from azure.ai.documentintelligence import DocumentIntelligenceAdministrationClient
from azure.ai.documentintelligence.models import (
    AuthorizeCopyRequest,
)
from azure.core.credentials import AzureKeyCredential

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Recurso ORIGEN (DI original donde están los modelos entrenados) ──
SOURCE_ENDPOINT = os.environ["DI_SOURCE_ENDPOINT"]
SOURCE_KEY = os.environ["DI_SOURCE_KEY"]

# ── Recurso DESTINO (kyb-document-intelligence-qa en RG-KYB) ──
TARGET_ENDPOINT = os.environ["DI_TARGET_ENDPOINT"]
TARGET_KEY = os.environ["DI_TARGET_KEY"]

# Modelos a copiar
MODELS_TO_COPY = ["INE_Front", "INE_Back"]


def copy_model(source_client, target_client, model_id: str):
    """Copia un modelo del recurso origen al destino."""
    logger.info(f"{'='*60}")
    logger.info(f"Copiando modelo: {model_id}")
    logger.info(f"{'='*60}")

    # 1. Verificar que el modelo existe en el origen
    try:
        source_model = source_client.get_model(model_id)
        logger.info(f"  Modelo encontrado en origen: {source_model.model_id}")
        logger.info(f"  Descripción: {source_model.description or 'N/A'}")
        logger.info(f"  Creado: {source_model.created_date_time}")
        logger.info(f"  Doc types: {list(source_model.doc_types.keys()) if source_model.doc_types else 'N/A'}")
    except Exception as e:
        logger.error(f"  ERROR: No se encontró el modelo '{model_id}' en el recurso origen: {e}")
        return False

    # 2. Autorizar la copia en el destino
    logger.info(f"  Autorizando copia en destino...")
    try:
        auth_request = AuthorizeCopyRequest(
            model_id=model_id,
            description=source_model.description or f"Copia de {model_id} desde recurso original",
        )
        auth = target_client.authorize_model_copy(body=auth_request)
        logger.info(f"  Autorización obtenida: target_model_id={auth.target_model_id}")
    except Exception as e:
        logger.error(f"  ERROR al autorizar copia: {e}")
        return False

    # 3. Ejecutar la copia desde el origen
    logger.info(f"  Iniciando copia desde origen...")
    try:
        poller = source_client.begin_copy_model_to(
            model_id=model_id,
            body=auth,
        )
        logger.info(f"  Esperando a que la copia termine...")
        result = poller.result()
        logger.info(f"  ✓ Modelo '{model_id}' copiado exitosamente!")
        logger.info(f"    Model ID: {result.model_id}")
        logger.info(f"    Creado: {result.created_date_time}")
        return True
    except Exception as e:
        logger.error(f"  ERROR durante la copia: {e}")
        return False


def main():
    logger.info("Conectando a recurso ORIGEN...")
    source_client = DocumentIntelligenceAdministrationClient(
        SOURCE_ENDPOINT, AzureKeyCredential(SOURCE_KEY)
    )
    
    logger.info("Conectando a recurso DESTINO...")
    target_client = DocumentIntelligenceAdministrationClient(
        TARGET_ENDPOINT, AzureKeyCredential(TARGET_KEY)
    )

    # Mostrar info de ambos recursos
    source_info = source_client.get_resource_details()
    target_info = target_client.get_resource_details()
    logger.info(f"ORIGEN: {source_info.custom_document_models.count}/{source_info.custom_document_models.limit} modelos")
    logger.info(f"DESTINO: {target_info.custom_document_models.count}/{target_info.custom_document_models.limit} modelos")

    # Copiar cada modelo
    results = {}
    for model_id in MODELS_TO_COPY:
        success = copy_model(source_client, target_client, model_id)
        results[model_id] = success

    # Resumen
    logger.info(f"\n{'='*60}")
    logger.info("RESUMEN DE COPIA")
    logger.info(f"{'='*60}")
    for model_id, success in results.items():
        status = "✓ OK" if success else "✗ FALLÓ"
        logger.info(f"  {model_id}: {status}")

    # Verificar modelos en destino
    logger.info(f"\nModelos en recurso DESTINO:")
    for model in target_client.list_models():
        logger.info(f"  - {model.model_id} (creado: {model.created_date_time})")

    if all(results.values()):
        logger.info("\n✓ Todos los modelos copiados exitosamente!")
        return 0
    else:
        logger.error("\n✗ Algunos modelos fallaron. Revisar errores arriba.")
        return 1


if __name__ == "__main__":
    exit(main())
