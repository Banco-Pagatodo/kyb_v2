# Let's build a model to use for this sample
import logging
from azure.ai.documentintelligence import DocumentIntelligenceAdministrationClient
from azure.core.credentials import AzureKeyCredential
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()  # Load environment variables from a .env file if present
endpoint = os.environ["DI_ENDPOINT"]
key = os.environ["DI_KEY"]

document_intelligence_admin_client = DocumentIntelligenceAdministrationClient(
    endpoint, 
    AzureKeyCredential(key)
    )

account_details = document_intelligence_admin_client.get_resource_details()
print(
    f"Our resource has {account_details.custom_document_models.count} custom models, "
    f"and we can have at most {account_details.custom_document_models.limit} custom models"
)

# Next, we get a paged list of all of our custom models
models = document_intelligence_admin_client.list_models()

logger.info("We have the following 'ready' models with IDs and descriptions:")
for model in models:
    logger.info(f"{model.model_id} | {model.description}")