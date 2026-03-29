"""Verificar modelos INE en recurso DI destino."""
import os
import sys

from azure.ai.documentintelligence import DocumentIntelligenceAdministrationClient
from azure.core.credentials import AzureKeyCredential

endpoint = os.getenv("AZURE_DI_ENDPOINT", "https://eastus.api.cognitive.microsoft.com/")
api_key = os.getenv("AZURE_DI_KEY")
if not api_key:
    print("ERROR: Definir variable de entorno AZURE_DI_KEY")
    sys.exit(1)

client = DocumentIntelligenceAdministrationClient(endpoint, AzureKeyCredential(api_key))

info = client.get_resource_details()
print(f"Modelos custom: {info.custom_document_models.count}/{info.custom_document_models.limit}")
print()

for m in client.list_models():
    if m.model_id.startswith("INE"):
        print(f"  Modelo: {m.model_id}")
        detail = client.get_model(m.model_id)
        print(f"    Creado: {detail.created_date_time}")
        if detail.doc_types:
            dt_keys = list(detail.doc_types.keys())
            print(f"    Doc types: {dt_keys}")
            for dt_name, dt_info in detail.doc_types.items():
                fields = list(dt_info.field_schema.keys()) if dt_info.field_schema else []
                print(f"    Campos [{dt_name}]: {fields}")
        else:
            print("    Doc types: N/A")
        print()

print("OK - Verificacion completa")
